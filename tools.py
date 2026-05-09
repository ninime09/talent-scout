"""Pure-function tools used by the LangGraph agent.

All tools return structured dicts/lists so the agent can reason over them.
No tool calls an LLM — the LLM-vs-rules split is documented in ADR-002.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

# 1-hour file cache for get_user_activity to amortize API calls across
# eval batches. Live UI demos still see ~fresh data within an hour;
# longer-window analytics shouldn't rely on it.
_CACHE_PATH = Path(__file__).parent / "data" / "activity_cache.json"
_CACHE_TTL_SECONDS = 3600
# Bump when the activity dict schema changes so older entries are ignored.
_CACHE_SCHEMA_VERSION = 2  # v2: pr_details (per-PR file lists) replaces framework_design_prs


def _cache_load() -> dict:
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text())
    except Exception:
        return {}


def _cache_save(cache: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass

GITHUB_API = "https://api.github.com"
DEFAULT_TIMEOUT = 30
USER_AGENT = "talent-scout-mvp/0.1"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


class GitHubError(Exception):
    """Raised when GitHub responses are unrecoverable."""


def _gh_get(path: str, params: dict | None = None) -> Any:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GitHubError(
            "GITHUB_TOKEN missing from environment. Add a PAT to .env."
        )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    url = path if path.startswith("http") else f"{GITHUB_API}{path}"
    resp = requests.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT)

    if resp.status_code == 404:
        raise GitHubError(f"404 not found: {url}")
    if resp.status_code in (403, 429):
        remaining = resp.headers.get("X-RateLimit-Remaining", "?")
        raise GitHubError(f"rate limited ({resp.status_code}); remaining={remaining}")
    if resp.status_code >= 400:
        raise GitHubError(f"{resp.status_code}: {resp.text[:200]}")
    return resp.json()


# ---------------------------------------------------------------------------
# Tool 1: search_contributors
# ---------------------------------------------------------------------------


def search_contributors(repo_owner: str, repo_name: str, top_n: int = 10) -> list[dict]:
    """Return the top-N contributors of a repo, ranked by commit count.

    Output shape:
        [{"username": str, "commits": int, "avatar_url": str, "profile_url": str}]
    """
    top_n = max(1, min(top_n, 30))  # guardrail clamp
    raw = _gh_get(
        f"/repos/{repo_owner}/{repo_name}/contributors",
        params={"per_page": top_n, "anon": "false"},
    )
    return [
        {
            "username": c["login"],
            "commits": c.get("contributions", 0),
            "avatar_url": c.get("avatar_url", ""),
            "profile_url": c.get("html_url", ""),
        }
        for c in raw
    ]


# ---------------------------------------------------------------------------
# Tool 2: get_user_activity
# ---------------------------------------------------------------------------


@dataclass
class ActivityStats:
    """Per-user activity in a repo. Stores raw PR file lists so evidence
    rules can be applied dynamically at predicate-verification time
    (rather than baking a single repo-specific heuristic into the fetcher).
    """
    username: str
    repo: str
    window_days: int
    merged_prs: int = 0
    open_prs: int = 0
    review_count: int = 0
    issue_comments: int = 0
    last_commit_iso: str | None = None
    review_acceptance: float = 0.0
    raw_pr_urls: list[str] = field(default_factory=list)
    pr_details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "username": self.username,
            "repo": self.repo,
            "window_days": self.window_days,
            "merged_prs": self.merged_prs,
            "open_prs": self.open_prs,
            "review_count": self.review_count,
            "issue_comments": self.issue_comments,
            "last_commit_iso": self.last_commit_iso,
            "review_acceptance": round(self.review_acceptance, 3),
            "raw_pr_urls": self.raw_pr_urls,
            "pr_details": self.pr_details,
        }


# Default evidence patterns used when criteria_parser_node falls back to
# a string-style evidence tag. These are repo-agnostic architectural-layer
# substrings that work for ~80% of mainstream code-organization conventions.
DEFAULT_EVIDENCE_PATTERNS = {
    "framework_design_pr": [
        "/core/", "/lib/", "/internal/",
        "/main/", "/server/",
        "/api/", "/schemas/", "/types/",
        "/router", "/middleware",
        "/services/", "/handlers/",
        "packages/",
        "/src/extract", "/src/routing",
    ],
    "doc_pr": ["/docs/", "/doc/", "README", ".md"],
    "test_pr": ["/tests/", "/__tests__/", "_test.go", ".test.ts", ".spec.ts", "test_"],
}


def _files_match_patterns(files: list[dict], patterns: list[str]) -> bool:
    """Return True if any file's path contains any of the patterns."""
    return any(
        any(p in f.get("filename", "") for p in patterns)
        for f in files
    )


def get_user_activity(
    username: str,
    repo_owner: str,
    repo_name: str,
    window_days: int = 90,
) -> dict:
    """Aggregate per-user activity in a target repo over a time window.

    Output shape: ActivityStats.to_dict() — structured for the scorer.
    """
    repo = f"{repo_owner}/{repo_name}"
    cache_key = f"{username}|{repo}|{window_days}"
    cache = _cache_load()
    cached = cache.get(cache_key)
    if (
        cached
        and "_cached_at" in cached
        and cached.get("_schema_version") == _CACHE_SCHEMA_VERSION
        and time.time() - cached["_cached_at"] < _CACHE_TTL_SECONDS
    ):
        payload = {
            k: v for k, v in cached.items()
            if k not in ("_cached_at", "_schema_version")
        }
        return payload

    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    stats = ActivityStats(username=username, repo=repo, window_days=window_days)

    # PRs by author in the repo, within window
    pr_search = _gh_get(
        "/search/issues",
        params={
            "q": f"repo:{repo} type:pr author:{username} created:>={since[:10]}",
            "per_page": 50,
        },
    )
    pr_files_fetched = 0
    accepted = 0
    for pr in pr_search.get("items", []):
        stats.raw_pr_urls.append(pr["html_url"])
        pr_number = pr["number"]
        if pr.get("pull_request", {}).get("merged_at"):
            stats.merged_prs += 1
            accepted += 1
        elif pr.get("state") == "open":
            stats.open_prs += 1
        # Sample first 25 PRs for files inspection (cap API cost).
        # Files are stored raw so evidence rules can be applied later.
        if pr_files_fetched < 25:
            try:
                files = _gh_get(f"/repos/{repo}/pulls/{pr_number}/files")
                stats.pr_details.append({
                    "url": pr["html_url"],
                    "title": pr["title"],
                    "files": [f.get("filename", "") for f in files],
                })
                pr_files_fetched += 1
            except GitHubError:
                pass

    # Reviews authored
    review_search = _gh_get(
        "/search/issues",
        params={
            "q": f"repo:{repo} type:pr reviewed-by:{username} created:>={since[:10]}",
            "per_page": 50,
        },
    )
    stats.review_count = review_search.get("total_count", 0)

    # Issue/PR comments authored (proxy for discussion participation)
    comment_search = _gh_get(
        "/search/issues",
        params={
            "q": f"repo:{repo} commenter:{username} created:>={since[:10]}",
            "per_page": 50,
        },
    )
    stats.issue_comments = comment_search.get("total_count", 0)

    # Last commit (recency)
    commits = _gh_get(
        f"/repos/{repo}/commits",
        params={"author": username, "per_page": 1},
    )
    if commits:
        stats.last_commit_iso = commits[0]["commit"]["author"]["date"]

    # Review acceptance proxy: merged authored PRs / total authored PRs
    total_authored = stats.merged_prs + stats.open_prs
    stats.review_acceptance = (
        stats.merged_prs / total_authored if total_authored else 0.0
    )

    payload = stats.to_dict()
    cache[cache_key] = {
        **payload,
        "_cached_at": time.time(),
        "_schema_version": _CACHE_SCHEMA_VERSION,
    }
    _cache_save(cache)
    return payload


# ---------------------------------------------------------------------------
# Tool 3: compute_impact_score
# ---------------------------------------------------------------------------


# Default weights — justified in ADR-005 / SCORING_RATIONALE.md / ablation.
DEFAULT_WEIGHTS = {
    "merged_pr_count": 0.30,
    "review_acceptance_rate": 0.25,
    "review_participation": 0.20,
    "commit_recency": 0.15,
    "issue_discussion_quality": 0.10,
}


def _normalize(value: float, ceiling: float) -> float:
    return min(value / ceiling, 1.0) if ceiling > 0 else 0.0


def _recency_score(last_commit_iso: str | None) -> float:
    if not last_commit_iso:
        return 0.0
    last = datetime.fromisoformat(last_commit_iso.replace("Z", "+00:00"))
    days = (datetime.now(timezone.utc) - last).days
    if days <= 7:
        return 1.0
    if days <= 30:
        return 0.7
    if days <= 90:
        return 0.4
    return 0.1


def compute_impact_score(
    activity: dict,
    weights: dict | None = None,
) -> dict:
    """Compute a 0-100 impact score from activity stats.

    Output shape:
        {
          "username": str,
          "score": float (0-100),
          "feature_values": {feature: raw_value},
          "feature_normalized": {feature: 0-1},
          "weights": {feature: weight},
        }
    """
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    raw = {
        "merged_pr_count": activity["merged_prs"],
        "review_acceptance_rate": activity["review_acceptance"],
        "review_participation": activity["review_count"],
        "commit_recency": activity["last_commit_iso"],
        "issue_discussion_quality": activity["issue_comments"],
    }

    norm = {
        "merged_pr_count": _normalize(activity["merged_prs"], 50),
        "review_acceptance_rate": activity["review_acceptance"],
        "review_participation": _normalize(activity["review_count"], 100),
        "commit_recency": _recency_score(activity["last_commit_iso"]),
        "issue_discussion_quality": _normalize(activity["issue_comments"], 50),
    }

    score = 100.0 * sum(norm[k] * w[k] for k in w)

    return {
        "username": activity["username"],
        "score": round(score, 2),
        "feature_values": raw,
        "feature_normalized": {k: round(v, 3) for k, v in norm.items()},
        "weights": w,
    }


# ---------------------------------------------------------------------------
# Tool 4: evaluate_predicates
# ---------------------------------------------------------------------------


def _resolve_evidence_rule(req) -> dict:
    """Normalize an evidence_required entry into a rule dict.

    Accepts two forms (string for backward compat, dict for new schema):
      "framework_design_pr"  → uses DEFAULT_EVIDENCE_PATTERNS lookup
      {"name": "...", "file_path_patterns": [...], "min_count": 1, ...}
    """
    if isinstance(req, str):
        return {
            "name": req,
            "description": f"PRs matching '{req}' default patterns",
            "file_path_patterns": DEFAULT_EVIDENCE_PATTERNS.get(req, []),
            "min_count": 1,
        }
    if isinstance(req, dict):
        return {
            "name": req.get("name", "evidence"),
            "description": req.get("description", ""),
            "file_path_patterns": list(req.get("file_path_patterns", [])),
            "min_count": int(req.get("min_count", 1)),
        }
    return {"name": "invalid", "file_path_patterns": [], "min_count": 1}


def evaluate_predicates(
    activity: dict,
    score: dict,
    predicates: dict,
) -> dict:
    """Verify a candidate against structured hiring predicates.

    `predicates` shape (from criteria_parser_node):
        {
          "seniority": "senior" | "mid" | "junior" | "any",
          "min_merged_prs": int,
          "must_have_skills": [str],
          "evidence_required": [
              # New schema (preferred):
              {"name": "framework_design_pr",
               "description": "PRs that touch architectural code",
               "file_path_patterns": ["/core/", "src/extract", ...],
               "min_count": 1},
              # Legacy schema (still supported):
              "framework_design_pr",
          ],
          "review_acceptance_min": float (0-1),
        }

    Output shape:
        {
          "username": str,
          "passed": [{"predicate": str, "evidence": [...]}],
          "failed": [{"predicate": str, "reason": str}],
          "all_passed": bool,
          "missing_evidence": [str],
        }
    """
    passed: list[dict] = []
    failed: list[dict] = []
    missing_evidence: list[str] = []

    # Seniority via merged PR threshold (proxy)
    seniority = predicates.get("seniority", "any")
    seniority_thresholds = {"senior": 20, "mid": 5, "junior": 1, "any": 0}
    threshold = seniority_thresholds.get(seniority, 0)
    if activity["merged_prs"] >= threshold:
        passed.append(
            {
                "predicate": f"seniority>={seniority}",
                "evidence": [f"{activity['merged_prs']} merged PRs"],
            }
        )
    else:
        failed.append(
            {
                "predicate": f"seniority>={seniority}",
                "reason": f"only {activity['merged_prs']} merged PRs (need {threshold})",
            }
        )

    # Min merged PRs (explicit)
    min_prs = predicates.get("min_merged_prs", 0)
    if activity["merged_prs"] >= min_prs:
        passed.append(
            {
                "predicate": f"min_merged_prs>={min_prs}",
                "evidence": activity["raw_pr_urls"][:3],
            }
        )
    else:
        failed.append(
            {
                "predicate": f"min_merged_prs>={min_prs}",
                "reason": f"only {activity['merged_prs']} merged PRs",
            }
        )

    # Review acceptance min
    min_acceptance = predicates.get("review_acceptance_min", 0.0)
    if activity["review_acceptance"] >= min_acceptance:
        passed.append(
            {
                "predicate": f"review_acceptance>={min_acceptance}",
                "evidence": [f"acceptance={activity['review_acceptance']}"],
            }
        )
    else:
        failed.append(
            {
                "predicate": f"review_acceptance>={min_acceptance}",
                "reason": f"only {activity['review_acceptance']}",
            }
        )

    # Evidence-required predicates: scan PR file lists against the rule's
    # patterns. Patterns are dynamic — generated by criteria_parser_node
    # based on the user's hiring text and the target repo's conventions.
    for req in predicates.get("evidence_required", []):
        rule = _resolve_evidence_rule(req)
        name = rule["name"]
        patterns = rule["file_path_patterns"]
        min_count = rule["min_count"]
        pred_label = f"has_{name} (>={min_count})"

        if not patterns:
            failed.append({
                "predicate": pred_label,
                "reason": f"evidence rule '{name}' has no file_path_patterns",
            })
            missing_evidence.append(name)
            continue

        # Scan stored PR details. Backward-compat: if older cached data
        # only has framework_design_prs, fall back to it for that name.
        matched = []
        for pr in activity.get("pr_details", []):
            files = [{"filename": fn} for fn in pr.get("files", [])]
            if _files_match_patterns(files, patterns):
                matched.append({"url": pr.get("url"), "title": pr.get("title")})
        if not matched and "framework_design_prs" in activity and name == "framework_design_pr":
            matched = activity["framework_design_prs"]

        if len(matched) >= min_count:
            passed.append({
                "predicate": pred_label,
                "evidence": [m["url"] for m in matched[:3]],
            })
        else:
            failed.append({
                "predicate": pred_label,
                "reason": (
                    f"only {len(matched)} matching PR(s) found in current window "
                    f"(patterns: {', '.join(patterns[:4])}{'...' if len(patterns) > 4 else ''})"
                ),
            })
            missing_evidence.append(name)

    all_passed = not failed

    return {
        "username": activity["username"],
        "score": score["score"],
        "passed": passed,
        "failed": failed,
        "all_passed": all_passed,
        "missing_evidence": missing_evidence,
        "predicates_passed": f"{len(passed)}/{len(passed) + len(failed)}",
    }


# ---------------------------------------------------------------------------
# Smoke test (run only when executed directly)
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    if not os.environ.get("GITHUB_TOKEN"):
        print("Set GITHUB_TOKEN to smoke-test against the live API.")
        raise SystemExit(0)

    print("[1/4] search_contributors…")
    contribs = search_contributors("tokio-rs", "axum", top_n=3)
    for c in contribs:
        print(f"  {c['username']:20} commits={c['commits']}")

    target = contribs[0]["username"]
    print(f"\n[2/4] get_user_activity for {target}…")
    activity = get_user_activity(target, "tokio-rs", "axum", window_days=90)
    print(
        f"  merged_prs={activity['merged_prs']}  "
        f"reviews={activity['review_count']}  "
        f"recency={activity['last_commit_iso']}"
    )

    print(f"\n[3/4] compute_impact_score for {target}…")
    score = compute_impact_score(activity)
    print(f"  score={score['score']}")
    for k, v in score["feature_normalized"].items():
        print(f"    {k:30} {v}")

    print(f"\n[4/4] evaluate_predicates for {target}…")
    predicates = {
        "seniority": "senior",
        "min_merged_prs": 20,
        "must_have_skills": ["async", "rust"],
        "evidence_required": ["framework_design_pr"],
        "review_acceptance_min": 0.80,
    }
    report = evaluate_predicates(activity, score, predicates)
    print(f"  predicates_passed={report['predicates_passed']}")
    for p in report["passed"]:
        print(f"  PASS {p['predicate']}")
    for f in report["failed"]:
        print(f"  FAIL {f['predicate']} ({f['reason']})")
