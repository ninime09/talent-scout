"""Pull cost / latency / token data from LangSmith and write data/finops.csv.

Direct response to instructor feedback #7: "FinOps placeholder — needs model
names, token estimates, burn-rate, success/fail distinction."

Definition of success used here:
    success_flag = 1 if judge_score >= 3.5 else 0
    (judge_score is from data/eval_results.csv, joined by trace tag.)
"""
from __future__ import annotations

import functools
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

print = functools.partial(print, flush=True)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv()

import pandas as pd
from langsmith import Client

DATA = ROOT / "data"
PROJECT = os.environ.get("LANGSMITH_PROJECT", "talent-scout")
LOOKBACK_HOURS = 24

# Per-million-token prices (USD), 2026 list pricing.
PRICES = {
    "claude-sonnet-4-5-20250929": {"in": 3.0, "out": 15.0},
    "claude-sonnet-4-5":          {"in": 3.0, "out": 15.0},
    "claude-haiku-4-5":           {"in": 0.80, "out": 4.0},
    "claude-haiku-4-5-20251001":  {"in": 0.80, "out": 4.0},
    "gpt-4o-mini":                {"in": 0.15, "out": 0.60},
}


def _model_name_from_run(run) -> str:
    extra = (run.extra or {}).get("invocation_params", {}) or {}
    name = extra.get("model") or extra.get("model_name") or ""
    return name.split("/")[-1].lower() if name else "unknown"


def _price(model: str, in_tok: int, out_tok: int) -> float:
    p = PRICES.get(model)
    if not p:
        # Default to Sonnet pricing if unknown
        p = PRICES["claude-sonnet-4-5"]
    return (in_tok / 1e6) * p["in"] + (out_tok / 1e6) * p["out"]


def main() -> int:
    client = Client()
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    print(f"querying LangSmith project={PROJECT!r} since {since.isoformat()}")

    # Pull all top-level "thread" runs first (each maps to one user query)
    # then explode child LLM runs by thread_id for per-node cost.
    # langsmith caps per-page limit at 100 — iterator handles pagination.
    runs = []
    for r in client.list_runs(project_name=PROJECT, start_time=since, limit=100):
        runs.append(r)
        if len(runs) >= 5000:
            break
    print(f"  fetched {len(runs)} runs")

    # Group by top-level chain (parent_run_id == None means it's a root).
    # Each LLM call's child runs hang off either a LangGraph chain or are
    # orphan (eval.py's direct LLM calls). Root key for orphans = run.id.
    by_root: dict[str, list] = defaultdict(list)
    runs_by_id = {str(r.id): r for r in runs}
    for r in runs:
        # Walk up parent_run_id chain to find the root
        cur = r
        seen = set()
        while getattr(cur, "parent_run_id", None) and str(cur.parent_run_id) in runs_by_id and str(cur.id) not in seen:
            seen.add(str(cur.id))
            cur = runs_by_id[str(cur.parent_run_id)]
        by_root[str(cur.id)].append(r)
    by_trace = by_root
    print(f"  {len(by_trace)} unique top-level traces")

    # Build one row per trace
    rows = []
    for trace_id, trace_runs in by_trace.items():
        trace_runs.sort(key=lambda r: r.start_time or datetime.min.replace(tzinfo=timezone.utc))
        root = trace_runs[0]
        in_tok = 0
        out_tok = 0
        cost = 0.0
        per_node_models = {}
        for r in trace_runs:
            if r.run_type != "llm":
                continue
            model = _model_name_from_run(r)
            in_t = (r.prompt_tokens or 0) or (r.input_tokens or 0)
            out_t = (r.completion_tokens or 0) or (r.output_tokens or 0)
            in_tok += in_t
            out_tok += out_t
            # Prefer LangSmith's own cost calc when available; fall back to ours.
            r_cost = (r.total_cost or 0) or (r.input_cost or 0) + (r.completion_cost or 0)
            cost += float(r_cost) if r_cost else _price(model, in_t, out_t)
            per_node_models[r.name] = model

        end = root.end_time or datetime.now(timezone.utc)
        latency_ms = int((end - root.start_time).total_seconds() * 1000)

        rows.append(
            {
                "trace_id": trace_id[:12],
                "name": root.name,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "total_tokens": in_tok + out_tok,
                "total_cost_usd": round(cost, 6),
                "latency_ms": latency_ms,
                "started": root.start_time.isoformat() if root.start_time else "",
                "models_seen": ";".join(sorted(set(per_node_models.values()))),
            }
        )

    df = pd.DataFrame(rows).sort_values("started")
    if df.empty:
        print("WARN: no runs found — has agent been executed yet?")
        return 1

    # success_flag: trace produced LLM output (i.e. agent didn't crash before
    # the first LLM call). For per-eval-run success/fail (judge >= 3.5), see
    # eval_results.csv directly — that join is not 1:1 with traces because
    # variation generation + judge sub-calls also produce traces.
    df["success_flag"] = (df["total_tokens"] > 0).astype(int)

    # Pull headline judge metric from eval_results.csv if available.
    eval_path = DATA / "eval_results.csv"
    eval_summary = ""
    if eval_path.exists():
        eval_df = pd.read_csv(eval_path)
        if "judge_score" in eval_df.columns:
            non_zero = eval_df[eval_df["judge_score"] > 0]
            non_s05 = eval_df[~eval_df["test_id"].str.startswith("S05_")]
            non_s05_nz = non_s05[non_s05["judge_score"] > 0]
            eval_summary = (
                f"\nJudge headline (from eval_results.csv):\n"
                f"  All tests          : mean={eval_df['judge_score'].mean():.2f}, "
                f"pass={eval_df['success_flag'].mean()*100:.0f}%\n"
                f"  Excluding S05 (404): mean={non_s05['judge_score'].mean():.2f}, "
                f"pass={non_s05['success_flag'].mean()*100:.0f}%\n"
                f"  Non-zero judged    : mean={non_zero['judge_score'].mean():.2f}\n"
            )
    out = DATA / "finops.csv"
    df.to_csv(out, index=False)
    print(f"  wrote {out} ({len(df)} rows)")

    # Headline numbers
    success = df[df["success_flag"] == 1]
    fail = df[df["success_flag"] == 0]
    print()
    print("=" * 60)
    print("FinOps headline (last 24h):")
    print(f"  Total runs           : {len(df)}")
    print(f"  Success / fail       : {len(success)} / {len(fail)}")
    print(f"  Cost-per-success     : ${success['total_cost_usd'].mean():.4f}")
    if len(fail):
        print(f"  Cost-per-fail        : ${fail['total_cost_usd'].mean():.4f}")
    print(f"  Total spend          : ${df['total_cost_usd'].sum():.4f}")
    print(f"  Latency p50 / p95    : "
          f"{df['latency_ms'].median()/1000:.1f}s / "
          f"{df['latency_ms'].quantile(0.95)/1000:.1f}s")
    if len(df) > 1 and df["started"].nunique() > 1:
        first = pd.to_datetime(df["started"].iloc[0], utc=True)
        last = pd.to_datetime(df["started"].iloc[-1], utc=True)
        mins = max((last - first).total_seconds() / 60.0, 1)
        burn = df["total_cost_usd"].sum() / mins
        print(f"  Burn rate            : ${burn:.4f} / min")
    print(f"  Models seen          : "
          f"{', '.join(sorted({m for s in df['models_seen'] for m in s.split(';') if m}))}")
    print("=" * 60)
    if eval_summary:
        print(eval_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
