"""End-to-end evaluation pipeline.

Phases (run in order, each idempotent — outputs saved to disk):
  1. Generate 50 synthetic test variations from 5 seed cases.
  2. Run the agent on each variation; capture final report + trace.
  3. Judge explanation quality for each result.
  4. (Consistency) Run 10 core tests 3 times each; compute variance.
  5. Aggregate metrics → data/eval_results.csv.

Limitations baked in:
- Judge uses Claude Haiku 4.5 (not GPT-4o-mini) because OPENAI_API_KEY
  is unset. Cross-vendor would be stronger; cross-model-size is a
  weaker but acceptable mitigation. Documented in ADR-001.
"""
from __future__ import annotations

import functools
import json
import os
import sys
import time
import traceback
from pathlib import Path

print = functools.partial(print, flush=True)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command

import agent

DATA = ROOT / "data"
SYNTH_PATH = DATA / "synthetic_tests.json"
EVAL_OUT = DATA / "eval_results.csv"
RAW_OUT = DATA / "eval_raw_outputs.json"

# 10 of the 50+ tests will be flagged as "core" and run 3x for consistency.
CORE_INDICES = list(range(0, 50, 5))  # every 5th: 0, 5, 10, ...
CONSISTENCY_REPEATS = 3

# Default resume value when clarify_node interrupts during eval.
DEFAULT_RESUME = (
    "Senior level. Role focus: framework design. "
    "Must-have skills: rust, async."
)

VARIATION_GENERATOR_PROMPT = """\
You generate evaluation test cases for an AI talent-scout agent.

Given ONE seed test case, produce exactly 10 variations of it. Each
variation keeps the seed's INTENT but varies ONE axis from:
- tone (curt / verbose / informal / formal / passive-aggressive)
- specificity (more detail / less detail / partial detail)
- edge case (very high top_n / unusual criteria phrasing)
- out-of-bounds (top_n > 30, contradictory criteria, etc.)

Output JSON ONLY, shape:
{
  "variations": [
    {
      "id": "<seed_prefix>_v01",
      "parent_seed_id": "<seed id>",
      "category": "<seed category>",
      "variation_axis": "tone | specificity | edge_case | out_of_bounds",
      "query": "...",
      "repo_owner": "tokio-rs",
      "repo_name": "axum",
      "criteria_text": "<the criteria text the agent receives>",
      "top_n": 5,
      "expected_outcome": "<one short sentence>"
    },
    ... 10 entries ...
  ]
}

Use repo_owner=tokio-rs, repo_name=axum unless the seed itself uses a
different repo (e.g. graceful_degradation seeds with 404 repos — keep
those repos as-is).
Vary top_n between 3 and 30 (out-of-bounds may exceed 30; the agent
clamps to 30 server-side).
Do NOT include the literal characters " or ' inside string values unless
escaped with backslash. Keep criteria_text under 200 characters.
"""

JUDGE_PROMPT = """\
You are an independent reviewer evaluating a hiring agent's output. You did
NOT write this output. Score it across four explanation-quality dimensions.

Score each dimension 1-5:
1 = Reasoning Transparency — does the explanation cite specific evidence
    (PR numbers, predicate names) rather than generic praise?
2 = Evidence Linkage — does each claim link back to a verified predicate
    or measured value, not invention?
3 = Clarity — is the writing concise and free of empty filler?
4 = Adherence — does the report follow the requested format (per-candidate
    paragraph + predicate list + evidence URLs)?

Output JSON only:
{"transparency": 1-5, "evidence_linkage": 1-5, "clarity": 1-5,
 "adherence": 1-5, "comment": "<one sentence>"}
"""


def _llm(model: str, temperature: float = 0.0):
    return ChatAnthropic(model=model, temperature=temperature, max_tokens=4096)


def _parse_json_block(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        if text.startswith("json"):
            text = text[len("json") :].lstrip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    return json.loads(text)


# ------------------------------------------------------------------ phase 1
def generate_variations() -> list[dict]:
    """Generate 50 variations from 5 seed cases (one Sonnet call per seed)."""
    if SYNTH_PATH.exists():
        existing = json.loads(SYNTH_PATH.read_text())
        if isinstance(existing, list) and len(existing) >= 50:
            print(f"  reusing existing {len(existing)} variations")
            return existing

    seeds = json.loads((DATA / "seed_cases.json").read_text())
    llm = _llm("claude-sonnet-4-5-20250929", temperature=0.7)
    all_variations: list[dict] = []
    for i, seed in enumerate(seeds, 1):
        print(f"  [{i}/{len(seeds)}] expanding {seed['id']}…", end=" ", flush=True)
        try:
            raw = llm.invoke(
                [
                    SystemMessage(content=VARIATION_GENERATOR_PROMPT),
                    HumanMessage(content=f"Seed: {json.dumps(seed)}"),
                ]
            ).content
            parsed = _parse_json_block(raw)
            v_list = parsed["variations"]
            all_variations.extend(v_list)
            print(f"got {len(v_list)} variations")
        except Exception as e:
            # Save the offending raw text for debugging, then continue.
            debug_path = DATA / f"variation_debug_{seed['id']}.txt"
            try:
                debug_path.write_text(raw)
            except Exception:
                pass
            print(f"FAILED ({type(e).__name__}: {e})")

    SYNTH_PATH.write_text(json.dumps(all_variations, indent=2))
    print(f"  total: {len(all_variations)} variations")
    return all_variations


# ------------------------------------------------------------------ phase 2
def run_one(graph, variation: dict) -> dict:
    """Run the agent on one variation, handling interrupt with default resume."""
    config = {
        "configurable": {
            "thread_id": f"eval-{variation['id']}-{int(time.time()*1000)}"
        }
    }
    init_state = {
        "query": variation["query"],
        "repo_owner": variation["repo_owner"],
        "repo_name": variation["repo_name"],
        "top_n": variation.get("top_n", 5),
        "criteria_text": variation.get("criteria_text", variation["query"]),
        "trace": [],
    }
    t0 = time.time()
    interrupt_fired = False
    try:
        for _ in graph.stream(init_state, config=config, stream_mode="updates"):
            pass
        snap = graph.get_state(config)
        ints = getattr(snap, "interrupts", ()) or ()
        if ints:
            interrupt_fired = True
            for _ in graph.stream(
                Command(resume=DEFAULT_RESUME),
                config=config,
                stream_mode="updates",
            ):
                pass
        elapsed = time.time() - t0
        final = graph.get_state(config).values
        report_str = final.get("final_report", "")
        return {
            "id": variation["id"],
            "ok": True,
            "interrupt_fired": interrupt_fired,
            "elapsed_s": round(elapsed, 1),
            "report": json.loads(report_str) if report_str else [],
            "n_candidates": len(json.loads(report_str)) if report_str else 0,
        }
    except Exception as e:
        return {
            "id": variation["id"],
            "ok": False,
            "interrupt_fired": interrupt_fired,
            "elapsed_s": round(time.time() - t0, 1),
            "error": f"{type(e).__name__}: {e}",
        }


def run_all_variations(variations: list[dict]) -> list[dict]:
    """Run agent on every variation; persist to disk after each."""
    if RAW_OUT.exists():
        prior = json.loads(RAW_OUT.read_text())
        # Keep only the latest OK record per id; drop earlier fails so
        # phase 5 doesn't double-count.
        latest_by_id: dict[str, dict] = {}
        for r in prior:
            rid = r.get("id")
            if not rid:
                continue
            if r.get("ok"):
                latest_by_id[rid] = r
            else:
                latest_by_id.setdefault(rid, r)
        prior = list(latest_by_id.values())
        done_ids = {r["id"] for r in prior if r.get("ok")}
        print(f"  resuming: {len(done_ids)} already complete")
    else:
        prior = []
        done_ids = set()

    graph = agent.build_graph()
    results = list(prior)
    for i, v in enumerate(variations, 1):
        if v["id"] in done_ids:
            continue
        print(f"  [{i:2}/{len(variations)}] {v['id']:>10} (top_n={v.get('top_n',5)})…",
              end=" ", flush=True)
        r = run_one(graph, v)
        if r.get("ok"):
            print(f"OK  n={r['n_candidates']:2}  elapsed={r['elapsed_s']:.1f}s"
                  + (f"  (interrupt resumed)" if r.get("interrupt_fired") else ""))
        else:
            print(f"FAIL {r.get('error','?')}")
        results.append(r)
        RAW_OUT.write_text(json.dumps(results, indent=2))
        if (not r.get("ok")) and "rate limited" in str(r.get("error", "")).lower():
            print("     hit rate limit — sleeping 75s before next run…")
            time.sleep(75)
        else:
            # Activity expansion now capped at 10 → ~30 search calls/run.
            # GitHub Search API limit: 30/min. Sleep 35s to stay safe.
            time.sleep(35)
    return results


# ------------------------------------------------------------------ phase 3
def judge_one(report: list[dict]) -> dict:
    if not report:
        return {
            "transparency": 0,
            "evidence_linkage": 0,
            "clarity": 0,
            "adherence": 0,
            "judge_score": 0.0,
            "comment": "empty report",
        }
    llm = _llm("claude-haiku-4-5", temperature=0.0)
    raw = llm.invoke(
        [
            SystemMessage(content=JUDGE_PROMPT),
            HumanMessage(content=f"Report: {json.dumps(report)[:6000]}"),
        ]
    ).content
    try:
        parsed = _parse_json_block(raw)
        score = (
            parsed["transparency"]
            + parsed["evidence_linkage"]
            + parsed["clarity"]
            + parsed["adherence"]
        ) / 4.0
        return {**parsed, "judge_score": round(score, 2)}
    except Exception as e:
        return {
            "transparency": 0,
            "evidence_linkage": 0,
            "clarity": 0,
            "adherence": 0,
            "judge_score": 0.0,
            "comment": f"judge_parse_error: {e}",
        }


def judge_all(results: list[dict]) -> list[dict]:
    judged = []
    for i, r in enumerate(results, 1):
        if not r.get("ok"):
            judged.append({**r, "judge_score": 0.0, "judge_comment": r.get("error", "?")})
            continue
        print(f"  [{i:2}/{len(results)}] judging {r['id']}…", end=" ", flush=True)
        j = judge_one(r.get("report", []))
        print(f"score={j['judge_score']}")
        judged.append({**r, **{f"judge_{k}": v for k, v in j.items()}})
    return judged


# ------------------------------------------------------------------ phase 4
def run_consistency(variations: list[dict]) -> list[dict]:
    graph = agent.build_graph()
    runs = []
    core = [v for i, v in enumerate(variations) if i in CORE_INDICES]
    for v in core:
        for rep in range(CONSISTENCY_REPEATS):
            print(f"  consistency {v['id']} rep{rep+1}/{CONSISTENCY_REPEATS}…",
                  end=" ", flush=True)
            r = run_one(graph, v)
            r["consistency_rep"] = rep + 1
            r["consistency_id"] = v["id"]
            runs.append(r)
            print(f"{'OK' if r.get('ok') else 'FAIL'}  elapsed={r.get('elapsed_s','?')}s")
            if (not r.get("ok")) and "rate limited" in str(r.get("error", "")).lower():
                time.sleep(75)
            else:
                time.sleep(35)
    return runs


# ------------------------------------------------------------------ phase 5
def aggregate(judged: list[dict], consistency: list[dict]) -> None:
    import pandas as pd

    # Dedup: keep latest OK per test_id, falling back to latest fail.
    by_id: dict[str, dict] = {}
    for r in judged:
        rid = r.get("id")
        if not rid:
            continue
        if r.get("ok"):
            by_id[rid] = r
        else:
            by_id.setdefault(rid, r)
    judged = list(by_id.values())

    rows = []
    for r in judged:
        rows.append(
            {
                "test_id": r["id"],
                "ok": r.get("ok", False),
                "interrupt_fired": r.get("interrupt_fired", False),
                "n_candidates": r.get("n_candidates", 0),
                "elapsed_s": r.get("elapsed_s", 0),
                "judge_transparency": r.get("judge_transparency", 0),
                "judge_evidence_linkage": r.get("judge_evidence_linkage", 0),
                "judge_clarity": r.get("judge_clarity", 0),
                "judge_adherence": r.get("judge_adherence", 0),
                "judge_score": r.get("judge_judge_score", r.get("judge_score", 0)),
                "judge_comment": r.get("judge_comment", r.get("error", "")),
            }
        )
    df = pd.DataFrame(rows)
    success_threshold = 3.5
    df["success_flag"] = (df["judge_score"] >= success_threshold).astype(int)
    df.to_csv(EVAL_OUT, index=False)
    print(f"  wrote {EVAL_OUT}")

    # Consistency variance per test_id
    if consistency:
        crows = []
        for r in consistency:
            crows.append({
                "consistency_id": r.get("consistency_id"),
                "rep": r.get("consistency_rep"),
                "ok": r.get("ok"),
                "n_candidates": r.get("n_candidates", 0),
                "elapsed_s": r.get("elapsed_s", 0),
            })
        cdf = pd.DataFrame(crows)
        var = cdf.groupby("consistency_id")["n_candidates"].agg(["mean", "std", "min", "max"])
        var.to_csv(DATA / "consistency_results.csv")
        print(f"  wrote {DATA / 'consistency_results.csv'}")

    # Headline numbers
    print()
    print("=" * 60)
    print(f"Total tests run     : {len(df)}")
    print(f"Successful runs     : {df['ok'].sum()}/{len(df)}")
    print(f"Mean Judge score    : {df['judge_score'].mean():.2f} / 5")
    print(f"Pass rate (>=3.5)   : {df['success_flag'].mean()*100:.1f}%")
    print(f"Mean elapsed (s)    : {df['elapsed_s'].mean():.1f}")
    print(f"Interrupt fire rate : {df['interrupt_fired'].mean()*100:.1f}%")
    print("=" * 60)


def main() -> int:
    print(f"[{time.strftime('%H:%M:%S')}] Phase 1: generate variations")
    variations = generate_variations()

    print(f"\n[{time.strftime('%H:%M:%S')}] Phase 2: run agent on {len(variations)} variations")
    results = run_all_variations(variations)

    print(f"\n[{time.strftime('%H:%M:%S')}] Phase 3: judge {len(results)} results")
    judged = judge_all(results)

    if os.environ.get("SKIP_CONSISTENCY") == "1":
        print(f"\n[{time.strftime('%H:%M:%S')}] Phase 4: SKIPPED (SKIP_CONSISTENCY=1)")
        consistency = []
    else:
        print(f"\n[{time.strftime('%H:%M:%S')}] Phase 4: consistency on {len(CORE_INDICES)} core × {CONSISTENCY_REPEATS}")
        consistency = run_consistency(variations)

    print(f"\n[{time.strftime('%H:%M:%S')}] Phase 5: aggregate")
    aggregate(judged, consistency)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
