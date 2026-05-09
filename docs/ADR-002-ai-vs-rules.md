## ADR-002: AI vs. rule-based per step

### Decision

| Step | Approach | Reason |
|---|---|---|
| GitHub data retrieval | Rule (REST API) | Deterministic, no LLM cost |
| Detecting missing criteria dimensions | AI (Sonnet) | Linguistic nuance |
| Parsing criteria into structured predicates | AI (Haiku) | Free-text → JSON schema |
| Predicate verification (does candidate satisfy?) | **Rule** | Auditable; LLM judgment here is the highest-risk source of false confidence |
| Composite scoring | Rule (pandas weighted) | Reproducible; supports ablation |
| Final report writing | AI (Sonnet) | Citation-grounded narrative |
| Judge | AI for explanation quality only; Spearman vs. ground truth for ranking | Avoid LLM-judges-LLM circularity in the ranking layer |

### Why predicate verification is rules-only

If the LLM decides whether a candidate "matches" criteria, it can produce
polished recruiting language around weak evidence — confident-sounding text
that isn't actually grounded in the data. Keeping predicate evaluation
deterministic means the LLM can only describe rule outputs, not invent
them. Every "passes seniority requirement" claim in the final report
traces back to a specific Boolean returned by `tools.evaluate_predicates`.
