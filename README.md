# GitHub Talent Scout — BAAI Genai Final

**Track A: LangGraph StateGraph** — multi-step agent that turns scattered
GitHub activity into explainable, evidence-grounded talent reports.

## Status (end of Day 2 PM)

| Component | Status | Evidence |
|---|---|---|
| Streamlit 5-tab platform | ✅ live | http://localhost:8501 (`app.py`) |
| `tools.py` — 4 structured tools + 1h activity cache | ✅ tested | offline + live API |
| `agent.py` — 7-node LangGraph + interrupt + conditional loop + activity cap | ✅ smoke-tested | end-to-end 42s |
| `prompts/` — clarify_v1/v2/v3 + parser_v1/v2/v3 | ✅ done | failure narrative in `PVC_LOG.md` |
| `data/ground_truth.json` — 15 hand-labeled axum contributors | ✅ done | by Jennifer |
| Feature ablation experiment | ✅ done | **Spearman ρ = 0.722** |
| `data/eval_results.csv` — 50 variations + Haiku judge | ✅ done | mean 4.07 (excl. S05) |
| `data/consistency_results.csv` — 10 core × 3 reps | ✅ done | variance < 0.5 |
| `data/finops.csv` — from LangSmith | ✅ done | total spend ~$1-2 |
| `docs/ADR-001..005.md` | ✅ done | 5 ADRs incl. ablation findings |
| `docs/RED_TEAM.md` | ✅ done | 5 attack categories |
| `docs/FAILURE_ANALYSIS.md` | ✅ done | 3 real failures + fixes |
| `docs/INSTRUCTOR_FEEDBACK_RESPONSE.md` | ✅ done | 8 critiques addressed |
| `docs/DEPLOYMENT.md` | ✅ done | Streamlit Cloud walkthrough |
| Streamlit Cloud deploy + 5-min video | ⏳ Day 3 | git init + push needed |

## Quick start (local)

```bash
cd talent-scout
source .venv/bin/activate

# 1. Configure secrets (one-time)
cp .env.example .env
# Edit .env: ANTHROPIC_API_KEY, GITHUB_TOKEN, LANGSMITH_API_KEY

# 2. Run the platform
NSAppSleepDisabled=YES caffeinate -is .venv/bin/streamlit run app.py
```

> Why the `caffeinate` wrapper: macOS App Nap can throttle background
> Python processes to nearly zero CPU. See `docs/FAILURE_ANALYSIS.md#3`.

Open http://localhost:8501. The sidebar lets you toggle between
**Live agent** mode (requires API keys) and **Mock** mode (works
without keys, useful for layout previews and demos).

## Demo query (designed to trigger every part of the graph)

```
Repo:     tokio-rs/axum
Criteria: Find good Rust contributors
Top N:    5
```

This deliberately under-specifies seniority and role focus, so:

1. `clarify_node` detects missing dimensions → `interrupt()` pauses
2. UI shows a follow-up form
3. User supplies "senior, framework-design, async + rust"
4. Agent resumes; `criteria_parser_node` produces structured predicates
5. `search_contributors` → `get_user_activity` → `score_node`
6. `evidence_check` may loop back via `expand_window_node` if needed
7. After ≤ 2 iterations, `report_node` writes evidence-grounded narratives

Verified end-to-end in `scripts/smoke_test.py`. Final Spearman vs Jennifer's
ground truth = 0.722 on n=15 contributors of axum.

## File map

```
talent-scout/
├── app.py                    # Streamlit platform (5 tabs)
├── agent.py                  # LangGraph StateGraph + 7 nodes
├── tools.py                  # 4 structured tools (no LLM)
├── eval.py                   # 50+ test harness (Sonnet generates → agent runs → Haiku judges)
├── scripts/
│   ├── smoke_test.py         # End-to-end CLI verification
│   ├── ablation.py           # Feature ablation against ground truth
│   └── finops.py             # Pull token/cost data from LangSmith
├── prompts/                  # PVC v1 → v2 → v3 (clarify + parser)
├── data/                     # seed cases, ground truth, eval/finops/ablation CSVs
├── docs/                     # 5 ADRs + PVC log + scoring rationale
│                             # + red team + failure analysis
│                             # + instructor feedback response + deployment
├── references/               # cloned cookbooks (gitignored)
├── .streamlit/config.toml    # theme + headless server
├── requirements.txt
└── .env.example
```

## Headline numbers

| Metric | Value | Threshold | Source |
|---|---|---|---|
| Spearman ρ vs ground truth | **0.722** | ≥ 0.50 ✅ | 15-user ablation |
| Mean Judge score (full 50) | 3.25 / 5 | — | eval pipeline |
| Mean Judge score (excl. S05 by-design 404 fails) | **4.07 / 5** | ≥ 3.0 ✅ | eval pipeline |
| Pass rate (judge ≥ 3.5, full 50) | 78% | — | eval pipeline |
| Pass rate (judge ≥ 3.5, excl. S05) | **98%** | — | eval pipeline |
| Latency p50 (cached) | ~25 s | — | 50-run mean |
| Total spend (Day 1 + Day 2) | ~$1-2 | budget $3-8 ✅ | LangSmith |

## Feedback compliance

See `docs/INSTRUCTOR_FEEDBACK_RESPONSE.md` for the 8-row critique → fix
mapping. Headlines:

- ✅ Track A explicitly declared (3 places)
- ✅ Concrete graph in `agent.py`, auto-exported to mermaid
- ✅ Ambiguity resolution via `clarify_node` + `interrupt()`
- ✅ Scoring weights validated by ablation against 15-user ground truth
- ✅ Hiring criteria operationalized into rule-based predicates
- ✅ Spearman ρ on hand-labeled benchmark (not LLM-only judging)
- ✅ FinOps with model names, tokens, burn rate, success/fail split
- ✅ Reasoning chain shown as observation/decision/action triplets
