"""Consistency Score: 10 core test cases × 3 repetitions, with proper variance.

For each test case, runs the agent 3 times and measures:
  - Top-N username set overlap (Jaccard) across the 3 reps
  - Top-1 stability (did the rank-1 candidate stay the same?)
  - Spearman ρ of the rankings across reps
  - Judge score variance (3 separate judge calls per test case)

This replaces the prior consistency check which only tracked
`n_candidates` (a trivial metric — the agent always returns top_n).

Output: data/consistency_results.csv
"""
from __future__ import annotations

import functools
import json
import sys
import time
from itertools import combinations
from pathlib import Path

print = functools.partial(print, flush=True)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

import pandas as pd
from scipy.stats import spearmanr

import agent
from langgraph.types import Command

# Reuse eval helpers
sys.path.insert(0, str(ROOT))
from eval import judge_one, run_one, DEFAULT_RESUME  # noqa: E402

DATA = ROOT / "data"
SYNTH_PATH = DATA / "synthetic_tests.json"
OUT_PATH = DATA / "consistency_results.csv"

# Same 10 cases the eval pipeline pinned as "core"
CORE_INDICES = list(range(0, 50, 5))
REPETITIONS = 3
PACING_SECONDS = 35  # GitHub Search API: 30 req/min; ~30 search calls/run


def _ranks(report: list[dict]) -> list[str]:
    """Extract the ordered list of usernames from a report."""
    return [c.get("username") for c in report or [] if c.get("username")]


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0


def _spearman_of_rankings(a: list[str], b: list[str]) -> float | None:
    """Spearman ρ of two rankings, restricted to the intersection."""
    common = [u for u in a if u in b]
    if len(common) < 2:
        return None
    rank_a = {u: i for i, u in enumerate(a)}
    rank_b = {u: i for i, u in enumerate(b)}
    ra = [rank_a[u] for u in common]
    rb = [rank_b[u] for u in common]
    rho, _ = spearmanr(ra, rb)
    return None if pd.isna(rho) else float(rho)


def main() -> int:
    if not SYNTH_PATH.exists():
        print(f"ERROR: {SYNTH_PATH} missing — run eval.py first to generate variations.")
        return 1

    variations = json.loads(SYNTH_PATH.read_text())
    core = [variations[i] for i in CORE_INDICES if i < len(variations)]
    print(f"[{time.strftime('%H:%M:%S')}] consistency: {len(core)} core × {REPETITIONS} reps")

    graph = agent.build_graph()
    rows = []

    for case_i, v in enumerate(core, 1):
        case_id = v["id"]
        rep_results = []
        for rep in range(REPETITIONS):
            print(f"  [{case_i:2}/{len(core)}] {case_id} rep{rep+1}/{REPETITIONS}…", end=" ", flush=True)
            r = run_one(graph, v)
            rep_results.append(r)
            print(f"{'OK' if r.get('ok') else 'FAIL'}  elapsed={r.get('elapsed_s','?')}s")
            time.sleep(PACING_SECONDS)

        # Skip judging if all reps failed (e.g. S05 by-design 404)
        if not any(r.get("ok") for r in rep_results):
            for rep_i, r in enumerate(rep_results, 1):
                rows.append({
                    "consistency_id": case_id,
                    "rep": rep_i,
                    "ok": False,
                    "judge_score": 0.0,
                    "ranking": "",
                    "top1": "",
                    "n_candidates": 0,
                })
            continue

        # Judge each rep
        judges = []
        for rep_i, r in enumerate(rep_results, 1):
            if not r.get("ok"):
                judges.append({"judge_score": 0.0})
                continue
            print(f"     judge rep{rep_i}…", end=" ", flush=True)
            j = judge_one(r.get("report", []))
            judges.append(j)
            print(f"score={j['judge_score']}")

        # Per-rep rankings
        rankings = [_ranks(r.get("report", [])) for r in rep_results]
        for rep_i, (r, j, rk) in enumerate(zip(rep_results, judges, rankings), 1):
            rows.append({
                "consistency_id": case_id,
                "rep": rep_i,
                "ok": bool(r.get("ok")),
                "judge_score": j.get("judge_score", 0.0),
                "ranking": "|".join(rk) if rk else "",
                "top1": rk[0] if rk else "",
                "n_candidates": len(rk),
            })

    df = pd.DataFrame(rows)
    df.to_csv(OUT_PATH, index=False)
    print(f"\n[{time.strftime('%H:%M:%S')}] wrote {OUT_PATH}")

    # ------------------------------------------------------------------
    # Aggregate per test case
    # ------------------------------------------------------------------
    summary_rows = []
    for case_id, grp in df.groupby("consistency_id"):
        ok_reps = grp[grp["ok"]]
        rankings = [r.split("|") for r in ok_reps["ranking"].tolist() if r]
        if len(rankings) < 2:
            summary_rows.append({
                "consistency_id": case_id,
                "ok_reps": len(rankings),
                "judge_mean": float(ok_reps["judge_score"].mean()) if len(ok_reps) else 0.0,
                "judge_std": 0.0,
                "top1_stable": False,
                "jaccard_mean": None,
                "spearman_mean": None,
                "note": "insufficient successful reps for variance",
            })
            continue

        jaccards = [_jaccard(a, b) for a, b in combinations(rankings, 2)]
        spearmans = [s for s in (_spearman_of_rankings(a, b) for a, b in combinations(rankings, 2)) if s is not None]
        top1s = [r[0] for r in rankings if r]
        top1_stable = len(set(top1s)) == 1

        summary_rows.append({
            "consistency_id": case_id,
            "ok_reps": len(rankings),
            "judge_mean": round(float(ok_reps["judge_score"].mean()), 2),
            "judge_std": round(float(ok_reps["judge_score"].std(ddof=0)), 3),
            "top1_stable": top1_stable,
            "jaccard_mean": round(sum(jaccards) / len(jaccards), 3) if jaccards else None,
            "spearman_mean": round(sum(spearmans) / len(spearmans), 3) if spearmans else None,
            "note": "",
        })

    summary_df = pd.DataFrame(summary_rows)
    summary_path = DATA / "consistency_summary.csv"
    summary_df.to_csv(summary_path, index=False)
    print(f"[{time.strftime('%H:%M:%S')}] wrote {summary_path}")

    # Headline
    valid = summary_df[summary_df["jaccard_mean"].notna()]
    print()
    print("=" * 60)
    print("Consistency Score (n =", len(valid), "cases with >=2 successful reps):")
    if len(valid):
        print(f"  Top-N set overlap (Jaccard mean) : {valid['jaccard_mean'].mean():.3f}  (1.0 = identical sets across reps)")
        print(f"  Top-1 stability                  : {valid['top1_stable'].mean()*100:.0f}%  (% of cases where rank-1 stayed the same)")
        sp = valid["spearman_mean"].dropna()
        if len(sp):
            print(f"  Ranking Spearman ρ (mean)        : {sp.mean():.3f}")
        print(f"  Judge score std (mean)           : {valid['judge_std'].mean():.3f}  (0.0 = identical judge across reps)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
