# Response to proposal review

The instructor's eight critiques, with concrete code/document anchors.

---

## #1 — Track A vs B and required structure not declared

**Critique.** "Please state if you are using Track A vs. Track B, and the
required implementation structure."

**Response.** **Track A: LangGraph StateGraph.** Declared in three places:
- `README.md` line 4 (header)
- `app.py` Architecture tab — first paragraph
- This document

The implementation structure is a 7-node `StateGraph` with one
conditional edge:

```
START → clarify_node → criteria_parser_node → search_contributors_node
     → get_user_activity_node → score_node → [evidence_check]
     → expand_window_node → get_user_activity_node (loop, max 2 iters)
     OR → report_node → END
```

Source: `agent.py:build_graph()`. Auto-exported mermaid in
`app.py` Architecture tab.

---

## #2 — Concrete graph / multi-agent orchestration loop / architecture diagram missing

**Critique.** "The proposal is missing a concrete graph, or explicit
multi-agent orchestration loop, and a real architecture diagram."

**Response.**
- **Concrete graph.** `agent.py:build_graph()` is the literal
  implementation. The mermaid is auto-exported via
  `agent.export_mermaid()` and embedded in the Architecture tab.
- **Orchestration loop.** The `evidence_check` conditional edge is
  the explicit loop. When `score_node` reports any candidate with
  unverified evidence, control returns to `expand_window_node` (which
  doubles the activity window) → `get_user_activity_node` →
  re-`score_node`. Capped at 2 iterations to avoid infinite spend.
- **Architecture diagram.** Two views available:
  1. Annotated Mermaid (Architecture tab top) — shows AI vs rule vs
     HITL nodes color-coded.
  2. Auto-exported LangGraph mermaid (Architecture tab expander) —
     shows the literal compiled graph.

---

## #3 — Ambiguity resolution: ask, infer, or choose tool?

**Critique.** "What happens when the user says 'find good Rust
contributors' without defining experience level, role type, or hiring
criteria?"

**Response.** **The agent ASKS** — it does not silently infer.
Implementation: `clarify_node` runs an LLM check against three required
dimensions (seniority, role focus, must-have skills). If any are
missing AND not inferable from context (using rules in
`prompts/clarify_v3.txt`, e.g. "senior X dev" implies seniority=senior),
the node calls LangGraph's `interrupt()` and surfaces a follow-up
question to the user via the Streamlit UI.

Verified end-to-end in `scripts/smoke_test.py`:
the demo query `"Find good Rust contributors"` triggers the interrupt
and pauses for user input. After resume, the agent proceeds with the
augmented criteria.

---

## #4 — Scoring features and weights not justified ("arbitrary heuristic")

**Critique.** "The system computes a weighted score from normalized
activity signals, but it does not explain the actual features or why
the weights are justified."

**Response.** Two artifacts:
- `docs/SCORING_RATIONALE.md` — five features explained, with weights
  and reasoning.
- `docs/ADR-005-scoring-features.md` — full ablation experiment
  comparing the model's ranking to Jennifer's hand-labeled ground
  truth (15 axum contributors).

**Headline result:** baseline Spearman ρ = 0.722 (above the 0.50
success threshold) on n=15 users. Per-feature ablation shows which
features actually contribute. The ADR transparently reports a
**surprising finding**: the original weight on `merged_pr_count` is
mildly counter-productive in this domain — quality of contribution
matters more than volume. We deliberately did *not* retune the weights
post-hoc to avoid overfitting on the small sample.

This is direct, data-driven defense against "arbitrary heuristic" —
the weights are not arbitrary; they are validated against ground
truth, and the ablation table makes the validity transparent.

---

## #5 — Hiring criteria fuzzy matching risk ("polished recruiting language around weak evidence")

**Critique.** "That could be useful, but it also risks becoming fuzzy
criteria matching unless you define how those criteria are
operationalized."

**Response.** Hiring criteria text is **operationalized into structured
predicates** by `agent.py:criteria_parser_node` (Haiku 4.5):

```json
{
  "seniority": "senior",
  "min_merged_prs": 20,
  "must_have_skills": ["async", "rust"],
  "evidence_required": ["framework_design_pr"],
  "review_acceptance_min": 0.80
}
```

Predicate verification is then **rule-based**, not LLM judgment:
`tools.py:evaluate_predicates` checks each predicate against measured
data and returns `{passed: bool, evidence: [pr_url, ...]}`. The LLM
only writes the final natural-language explanation, citing the rule
outputs.

Concretely: the LLM cannot say "this candidate has framework design
experience" unless `tools.py:_is_framework_design_pr()` (a deterministic
substring check on PR file paths) returned True with specific PR URLs
attached as evidence.

---

## #6 — Judge circularity ("LLM judging another LLM")

**Critique.** "Ranking quality and explanation clarity are important,
but if the Judge is mostly another LLM scoring usefulness, then the
evaluation can become circular very quickly. I would want to see some
stronger ground-truth plan or human-labeled benchmark."

**Response.** Two-layer evaluation:
1. **Hard metric (rebuts circularity).** Spearman ρ and Kendall τ
   between agent's ranking and Jennifer's hand-labeled ground truth
   (`data/ground_truth.json`, 15 axum contributors). LLM is not in this
   loop. **Baseline ρ = 0.722 on full 15-user set.**
2. **Soft metric (LLM judge).** The judge is used **only for
   explanation quality** (transparency, evidence linkage, clarity,
   adherence) — never for ranking. See `eval.py:judge_one`.

Original plan was GPT-4o-mini for cross-vendor independence. Since
`OPENAI_API_KEY` was not configured for this MVP, the judge currently
runs on Claude Haiku 4.5 (cross-model-size within the same vendor).
This weakens the cross-vendor independence claim; documented in ADR-001
limitations.

---

## #7 — FinOps placeholder ("model names, token estimates, burn-rate, success/fail distinction")

**Critique.** "In your FinOps, you need to mention model names, token
estimates, burn-rate math, and the assignment-specific distinction
between successful and failed runs."

**Response.** `data/finops.csv` is auto-generated by
`scripts/finops.py`, which queries the LangSmith trace API. Each row
contains:
- Per-node model name (clarify/parser/report nodes labeled with model)
- Input/output tokens per LLM call
- Total cost USD (computed from per-million-token list prices)
- Latency milliseconds
- `success_flag = 1 if judge_score ≥ 3.5 else 0`
- Burn rate (USD/min) computed across the time window

Streamlit FinOps tab renders the table + headline metrics
(cost-per-success, cost-per-fail, p50/p95 latency).

---

## #8 — Trace doesn't show reasoning ("concrete observation + branch decision + shortlist refinement")

**Critique.** "I want to see concrete observations, at least one branch
decision, and how the candidate shortlist is refined."

**Response.** Each LangGraph node returns a `trace` entry containing
three fields: `observation`, `decision`, `action`. Streamlit's Run Agent
tab renders these as `st.status` blocks in real time as the agent
executes — making the agent's reasoning chain literally visible step
by step.

The branch decision is concrete and shown:
- `score_node` evaluates predicates and reports `missing_evidence`.
- `evidence_check` conditional edge returns `"fetch_more"` (loop) or
  `"report"` (forward).
- When loop fires: `expand_window_node` doubles the activity window
  and re-fetches → `score_node` recomputes → predicates re-checked.

Verified in smoke test: in run 1, `evidence_check` fired the loop
because `framework_design_pr` evidence was missing in 90-day window;
after expanding to 180 days, evidence was found and the loop exited.
The shortlist was *refined* between iterations.
