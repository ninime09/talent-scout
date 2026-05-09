## Five features and their measured contribution

Initial weights were chosen a priori based on hiring intuition, then
validated by ablation against hand-labeled ground truth.

| Feature | Initial weight | Δ Spearman when dropped (n=15) | Status |
|---|---|---|---|
| `merged_pr_count` | 0.30 | +0.034 | Slight net penalty in this domain |
| `review_acceptance_rate` | 0.25 | -0.021 | Mildly useful |
| `review_participation` | 0.20 | -0.030 | Useful, weight roughly correct |
| `commit_recency` | 0.15 | **+0.116** | Sample artifact — see ADR-005 |
| `issue_discussion_quality` | 0.10 | 0.000 | No measurable signal |

Baseline Spearman ρ = **0.722** (n=15) — clears the 0.50 significance threshold.

See ADR-005 for the full ablation methodology, per-user calibration table,
and the discussion of why weights were not retuned post-hoc.

## How hiring criteria become measurable

Free-text criteria are parsed by `criteria_parser_node` into structured
predicates:

```json
{
  "seniority": "senior",
  "min_merged_prs": 20,
  "must_have_skills": ["async", "rust"],
  "evidence_required": ["framework_design_pr"],
  "review_acceptance_min": 0.80
}
```

Predicate verification is **rule-based** — `tools.evaluate_predicates`
checks each predicate against measured data and returns
`{passed: bool, evidence: [pr_url, ...]}`. The LLM writes the final
natural-language explanation but only over verified rule outputs;
it cannot invent a "passes seniority requirement" claim that isn't
backed by a Boolean from the rule layer.

The `framework_design_pr` evidence type is detected by inspecting PR file
paths against a substring list of architecturally-significant directories
(`/src/extract`, `/src/routing`, `/src/handler`, `/src/middleware`,
`/src/error`, `/src/response`, `/src/body`, `/src/lib.rs`, plus
`axum-core/src/`). This is auditable and version-controlled in code,
not a subjective LLM judgment about "what counts as framework design".
