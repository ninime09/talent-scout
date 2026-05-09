## ADR-004: Graceful degradation

### Failure modes and responses

| Failure | Detection | Response |
|---|---|---|
| GitHub rate limit (403/429) | Header `X-RateLimit-Remaining=0` | Backoff and use cached partial data; surface notice in UI |
| GitHub 404 (private/missing repo) | Status 404 | Halt with a clear error in the trace; no candidates returned |
| LLM API timeout | 30s per-call cap | Skip `report_node`'s natural-language generation; output raw scores + predicate table |
| Report generation parse error | JSON parse fails | Synthesize narrative from rule data (predicate pass/fail + evidence URLs) instead of producing placeholder text |
| `evidence_check` exhausts iterations | `iteration_count == 2` | Output the current shortlist with an explicit "low-confidence" flag |
| User abandons clarify interrupt | Streamlit session ends | LangGraph checkpoint persists; resumable later via `thread_id` |

### Guardrails

- `max_iterations = 2` on the `evidence_check` loop
- Per-LLM-call timeout: 30s
- Activity expansion capped at 10 candidates regardless of `top_n`
  (protects the GitHub Search API budget at 30 req/min)

### Design principle

A fallback path is part of the product, not an afterthought. If the
fallback writes lower-quality output than the happy path, the evaluation
pipeline scores it lower — and that's caught before users see it.
