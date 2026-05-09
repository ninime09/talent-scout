## ADR-001: Model split (cost-performance + judge independence)

### Decision

| Node | Model | Reason |
|---|---|---|
| `clarify_node` | Claude Sonnet 4.5 | Detecting whether criteria are sufficiently specified requires linguistic nuance |
| `criteria_parser_node` | Claude Haiku 4.5 | Structured free-text → JSON extraction; the cheaper model is sufficient |
| `report_node` | Claude Sonnet 4.5 | Final natural-language quality matters; this is what the user reads |
| Judge (eval only) | Claude Haiku 4.5 (cross-model-size) | Independent scoring of explanation quality; ideally GPT-4o-mini for cross-vendor independence |

### Why not all Sonnet?

- Cost: Haiku is roughly 3× cheaper for `criteria_parser_node`, which is the highest-frequency LLM call.
- Judge independence: a Sonnet judge scoring Sonnet-generated reports is the well-known LLM-judges-LLM circularity. Cross-model-size (Haiku judging Sonnet) reduces that bias; cross-vendor (GPT-4o-mini judging Sonnet) eliminates it.

### Why GPT-4o-mini for the judge (when configured)

- Different model family → uncorrelated bias.
- Cheap.
- Strong on structured rubric scoring per public eval benchmarks.

### Trade-offs

- Two API providers means two key-management surfaces (mitigated by `.env` + Streamlit secrets).
- Without `OPENAI_API_KEY`, the judge runs on Haiku (same vendor, different size). The cross-vendor independence claim is weaker but the methodology still avoids same-model self-evaluation.
