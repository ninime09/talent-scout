# Prompt Version Control Log

This log captures the v1 → v2 → v3 evolution for the two LLM-driven nodes.
Each entry includes the failure mode that motivated the next version.

---

## clarify_node prompt evolution

### clarify_v1 — initial draft (Day 1 PM)

`prompts/clarify_v1.txt`

**Behavior on test query** `"Find good Rust contributors in tokio-rs/axum"`:

```json
{"need_clarification": false}
```

**Failure mode:** model is too charitable. Despite the query missing
seniority, role focus, and explicit skills, it says "no clarification
needed" because it can plausibly *infer* something. This breaks the
ambiguity-resolution gate the instructor flagged in feedback #3.

**Diagnosis:** v1 has no explicit list of required dimensions; the model
defaults to "be helpful" rather than "enforce a checklist".

---

### clarify_v2 — overcorrection (Day 2 AM)

`prompts/clarify_v2.txt`

**Change:** added an explicit checklist of three required dimensions and
the rule "MUST contain ALL ... explicitly".

**Behavior on test query** `"Find senior Rust async experts working on
framework design"`:

```json
{"need_clarification": true, "missing": ["seniority"]}
```

**Failure mode:** now over-clarifies. "senior" is *implicit* in "senior
Rust async experts" but v2 demands the literal label. Triggers an
unnecessary user interruption — bad UX and wastes a turn.

**Diagnosis:** "explicitly stated" is too strict. We need to allow
sensible inferences (e.g., "senior X" → seniority=senior).

---

### clarify_v3 — stable (Day 2 AM, current)

`prompts/clarify_v3.txt`

**Change:** added an "Inference rules" block listing patterns that count
as explicit (e.g., "senior X engineer" → seniority=senior; specific
framework name → role focus). Only ask when a dimension is *still*
missing after applying these rules.

**Behavior on test queries:**

| Query | v1 | v2 | v3 |
|---|---|---|---|
| "Find good Rust contributors" | no_clarify ❌ | clarify(seniority,role,skills) ✅ | clarify(seniority,role) ✅ |
| "Find senior Rust async experts on axum framework" | no_clarify ✅ | clarify(seniority) ❌ | no_clarify ✅ |
| "Hire 3 people" | no_clarify ❌ | clarify(all) ✅ | clarify(all) ✅ |

**Why this is stable:** the "checklist + inference rules" pattern matches
how a human reviewer would handle ambiguity. Future test runs will
quantify false-positive vs false-negative rates on the 50+ test set.

---

## criteria_parser_node prompt evolution

### parser_v1 — minimal schema (Day 1 PM)

`prompts/parser_v1.txt`

**Failure mode:** model freely invents `evidence_required` tags like
`"high_quality_reviews"`, `"open_source_advocacy"`, etc. Downstream
`evaluate_predicates` doesn't know how to verify them, so they all get
flagged as "missing evidence" → infinite re-fetch loop until iteration
cap kicks in.

---

### parser_v2 — enumerated tags (Day 2 AM)

`prompts/parser_v2.txt`

**Change:** added "Allowed values for evidence_required:
['framework_design_pr']".

**Failure mode:** model now produces `"evidence_required": []` for senior
roles too, because the constraint feels prohibitive. Senior queries
should *always* require framework-design evidence — that's the whole
point of distinguishing "active contributor" from "framework architect".

---

### parser_v3 — explicit defaults per seniority (Day 2 AM, current)

`prompts/parser_v3.txt`

**Change:** added a "Defaults by seniority" block that *always* sets
`evidence_required=["framework_design_pr"]` for senior roles, plus
explicit min_merged_prs and review_acceptance_min defaults.

**Validation:** running on the 5 seed cases produces predictable,
verifiable predicates. Day 2 PM will quantify across the full 50+ set.

---

## Stabilization criteria (Day 2)

A prompt version is "stable" when:
1. It produces the expected behavior on the 5 seed cases (manual review).
2. Variance across 3 repeated runs of the 10 core tests is < 0.5 on the
   Judge explanation-quality dimension.
3. Spearman ρ vs. ground truth for the full 50+ test set is ≥ 0.5.

If any criterion fails, log the failure, write v4, and continue.
