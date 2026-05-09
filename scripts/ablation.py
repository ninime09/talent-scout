"""Feature ablation experiment — direct response to instructor feedback #4.

Procedure:
1. Pull 365-day activity for all 15 ground-truth users (GitHub API only, no LLM).
2. Compute composite scores with the FULL feature set (baseline).
3. For each of the 5 features, compute scores with that feature's weight = 0
   (and remaining weights renormalized).
4. Spearman ρ vs. ground truth for each variant. Larger drop ⇒ feature matters.

Output: data/ablation_results.csv
"""
from __future__ import annotations

import functools
import json
import sys
import time
from pathlib import Path

print = functools.partial(print, flush=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import pandas as pd
from scipy.stats import kendalltau, spearmanr

import tools

REPO_OWNER = "tokio-rs"
REPO_NAME = "axum"
WINDOW_DAYS = 365  # match ground_truth.json _meta.labeling_window
GROUND_TRUTH_PATH = Path(__file__).resolve().parent.parent / "data" / "ground_truth.json"
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "ablation_results.csv"


FEATURES = list(tools.DEFAULT_WEIGHTS.keys())


def _renormalize_dropping(feature: str) -> dict:
    """Return weight dict with `feature` zeroed and the rest summing to 1.0."""
    base = dict(tools.DEFAULT_WEIGHTS)
    base[feature] = 0.0
    total = sum(base.values())
    return {k: (v / total if total else 0.0) for k, v in base.items()}


def main() -> int:
    if not GROUND_TRUTH_PATH.exists():
        print(f"ERROR: {GROUND_TRUTH_PATH} not found")
        return 1

    gt = json.loads(GROUND_TRUTH_PATH.read_text())
    if not gt["_meta"].get("completed"):
        print("ERROR: ground_truth.json _meta.completed is false — fill labels first")
        return 1

    labels = [r for r in gt["labels"] if r.get("score") is not None]
    if len(labels) < 5:
        print(f"ERROR: only {len(labels)} labels — need >=5 for meaningful Spearman")
        return 1

    # On-disk cache so re-runs after rate-limit resets don't re-fetch.
    CACHE_PATH = OUT_PATH.parent / "activity_cache.json"
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}

    print(f"[{time.strftime('%H:%M:%S')}] pulling activity for {len(labels)} users…")
    print(f"  (cache hits: {sum(1 for r in labels if r['username'] in cache)}/{len(labels)})")
    activities = []
    for i, row in enumerate(labels, 1):
        username = row["username"]
        if username in cache:
            activity = cache[username]
            print(
                f"  [{i:2}/{len(labels)}] {username:20} "
                f"merged_prs={activity['merged_prs']:3} "
                f"reviews={activity['review_count']:3} "
                f"prs_with_files={len(activity.get('pr_details', [])):2} "
                f"(cached)"
            )
            activities.append({"label": row["score"], "activity": activity})
            continue
        try:
            t0 = time.time()
            activity = tools.get_user_activity(
                username, REPO_OWNER, REPO_NAME, window_days=WINDOW_DAYS
            )
            print(
                f"  [{i:2}/{len(labels)}] {username:20} "
                f"merged_prs={activity['merged_prs']:3} "
                f"reviews={activity['review_count']:3} "
                f"acceptance={activity['review_acceptance']:.2f} "
                f"prs_with_files={len(activity.get('pr_details', [])):2} "
                f"({time.time()-t0:.1f}s)"
            )
            activities.append({"label": row["score"], "activity": activity})
            cache[username] = activity
            # Persist after every fetch so a rate-limit kill doesn't lose work
            CACHE_PATH.write_text(json.dumps(cache, indent=2))
            # GitHub Search API: 30 req/min authenticated.
            # We make 3 search calls per user; pace at 7s to stay safe.
            time.sleep(7)
        except Exception as e:
            print(f"  [{i:2}/{len(labels)}] {username:20} ERROR {type(e).__name__}: {e}")
            if "rate limited" in str(e).lower():
                print("     waiting 60s before continuing…")
                time.sleep(60)

    if not activities:
        print("ERROR: no activity data collected")
        return 1

    print(f"\n[{time.strftime('%H:%M:%S')}] running ablation…")

    def _scores_for(weights: dict) -> tuple[list[float], list[float]]:
        agent_scores = [
            tools.compute_impact_score(a["activity"], weights=weights)["score"]
            for a in activities
        ]
        gt_scores = [a["label"] for a in activities]
        return agent_scores, gt_scores

    rows = []

    # Baseline (no feature dropped)
    base_w = dict(tools.DEFAULT_WEIGHTS)
    agent_scores, gt_scores = _scores_for(base_w)
    rho_base, _ = spearmanr(agent_scores, gt_scores)
    tau_base, _ = kendalltau(agent_scores, gt_scores)
    print(f"  baseline (full)        spearman={rho_base:+.3f}  kendall={tau_base:+.3f}")
    rows.append(
        {
            "feature_removed": "none_full_model",
            "spearman": round(rho_base, 3),
            "delta_vs_full": 0.000,
            "kendall_tau": round(tau_base, 3),
            "note": "baseline",
        }
    )

    # Drop each feature
    for feat in FEATURES:
        w = _renormalize_dropping(feat)
        agent_scores, gt_scores = _scores_for(w)
        rho, _ = spearmanr(agent_scores, gt_scores)
        tau, _ = kendalltau(agent_scores, gt_scores)
        delta = rho - rho_base
        sign = "drop" if delta < 0 else "improve"
        note = (
            f"feature {sign}s Spearman by {abs(delta):.3f}"
            if abs(delta) > 0.005
            else "near-zero impact"
        )
        print(
            f"  drop {feat:30} spearman={rho:+.3f}  "
            f"delta={delta:+.3f}  kendall={tau:+.3f}"
        )
        rows.append(
            {
                "feature_removed": feat,
                "spearman": round(rho, 3),
                "delta_vs_full": round(delta, 3),
                "kendall_tau": round(tau, 3),
                "note": note,
            }
        )

    df = pd.DataFrame(rows)
    df.to_csv(OUT_PATH, index=False)
    print(f"\n[{time.strftime('%H:%M:%S')}] wrote {OUT_PATH}")

    # Sanity printout: per-user comparison
    print("\nPer-user comparison (baseline weights):")
    print(f"  {'username':20} {'gt':>4} {'agent_score':>12}")
    base_scores, gts = _scores_for(base_w)
    user_compare = sorted(
        zip(
            [a["activity"]["username"] for a in activities],
            gts,
            base_scores,
        ),
        key=lambda t: t[2],
        reverse=True,
    )
    for u, g, s in user_compare:
        print(f"  {u:20} {g:>4} {s:>12.2f}")

    print(
        f"\nBASELINE Spearman ρ = {rho_base:+.3f}  "
        f"(success threshold: ρ >= 0.50)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
