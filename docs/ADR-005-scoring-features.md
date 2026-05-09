## ADR-005: Scoring features and weights

### Five features

| Feature | Weight | What it measures |
|---|---|---|
| `merged_pr_count` | 0.30 | Volume of accepted contributions |
| `review_acceptance_rate` | 0.25 | Maintainer-accepted vs. submitted (signal of trust) |
| `review_participation` | 0.20 | Reviewing others' PRs (senior-level signal) |
| `commit_recency` | 0.15 | Currency filter — distinguishes active from dormant |
| `issue_discussion_quality` | 0.10 | Design participation outside PRs |

### Methodology

Initial weights were chosen a priori based on hiring intuition. They
were then **validated by ablation against hand-labeled ground truth**:
15 real Axum contributors, scored 1-5 by domain reviewers, with no LLM
in the loop. For each feature we set its weight to zero, renormalized
the remaining four, and measured the Spearman ρ change on the agent's
ranking.

### Results

| Feature dropped | Spearman ρ | Δ vs. full | Note |
|---|---|---|---|
| (none, baseline) | **0.722** | — | Above the 0.50 significance threshold for n=15 |
| `merged_pr_count` | 0.756 | +0.034 | Slight net penalty in this domain |
| `review_acceptance_rate` | 0.702 | -0.021 | Mildly useful |
| `review_participation` | 0.692 | -0.030 | Useful, modest contribution |
| `commit_recency` | 0.838 | +0.116 | Sample artifact (see below) |
| `issue_discussion_quality` | 0.722 | 0.000 | No measurable signal — drop candidate |

### Discussion

**The `commit_recency` finding is a sample artifact.** Six of the 15
ground-truth users have zero merged PRs in the activity window
(`last_commit_iso = None` → recency_score = 0). Keeping recency in the
formula effectively penalizes them twice — once via the zero score, once
via the renormalization. Removing recency lets the other features
differentiate the active contributors more sharply. This is *not* a
recommendation to drop recency in production; it's a recommendation to
treat zero-data candidates as a separate cohort.

**`issue_discussion_quality` consistently shows zero signal** across
runs. It is the strongest candidate for removal in a future revision.

**Why we did not retune weights post-hoc.** The baseline ρ = 0.722
already clears the success threshold. Retuning on n=15 to reach 0.83
would risk overfitting to this single repo; the responsible move is to
expand the ground truth set and re-validate before changing weights.

### Per-user calibration (baseline weights, full run)

| Rank | Username | Ground truth | Agent score |
|---|---|---|---|
| 1 | jplatte | 5 | 73.3 |
| 2 | tottoto | 3 | 67.4 |
| 3 | yanns | 4 | 63.6 |
| 4 | davidpdrsn | 5 | 47.8 |
| 5 | mladedav | 4 | 44.1 |
| 6 | SabrinaJewson | 4 | 28.5 |
| 7 | Turbo87 | 3 | 8.9 |
| 8-12 | (5 users) | 1-2 | 0.0-1.5 |

### Where the rankings disagree

The largest gap between agent and ground truth is `davidpdrsn` (GT=5,
agent=48). davidpdrsn is the original author of axum but currently has
only 5 merged PRs in the 365-day activity window. The agent measures
*current* hiring signal; the labelers scored *cumulative* contribution
quality. Both framings are defensible — they answer different questions.

### Limitations

- Ground truth is 15 contributors of one repo, labeled by one team.
  Generalization to other ecosystems is untested.
- Hand labels reflect community insider judgment, not industry recruiter
  scoring; a real recruiter might weight differently (e.g., caring more
  about merge volume for headcount planning vs. architectural depth for
  staff hires).
- The 365-day activity window matches the labeling window, but
  systematically under-rates "less active but foundational" contributors.

### Evidence rule design — dynamic patterns, not hardcoded paths

The `evidence_required` field is generated dynamically by
`criteria_parser_node`, not hardcoded. Each rule is a structured object:

```json
{
  "name": "framework_architecture_pr",
  "description": "PRs that modify core framework code or internal APIs",
  "file_path_patterns": ["/core/", "/lib/", "/internal/", "src/framework"],
  "min_count": 1
}
```

The parser chooses patterns based on the user's hiring criteria (e.g.,
"frontend engineer" generates patterns like `src/components/`, `.tsx`;
"infra engineer" generates `/.github/workflows/`, `Dockerfile`).
`tools.evaluate_predicates` scans each candidate's PR file lists against
these patterns at verification time and returns matched PR URLs as
evidence.

**Why dynamic.** An earlier draft hardcoded axum-specific paths (e.g.,
`src/extract`, `src/routing`) inside `tools.py`. That worked for axum
but was a design smell — the agent should generalize across repos.
Cross-repo verification on `langchain-ai/langgraph` confirmed the
parser produces sensible Python-stack patterns (`async`, `asyncio`,
`/state/`, `/agents/`) without code changes.

**Backward compatibility.** Legacy string-form `evidence_required`
entries (e.g., `["framework_design_pr"]`) still work; they fall back to
a curated default pattern list in `tools.DEFAULT_EVIDENCE_PATTERNS`.
