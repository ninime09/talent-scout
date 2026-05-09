# GitHub Talent Scout

A multi-step LangGraph agent that turns scattered GitHub activity into
**evidence-grounded hiring reports** — every claim cites a real PR.

Built on **Track A · LangGraph StateGraph** with 7 reasoning nodes,
a conditional evidence-check loop, and human-in-the-loop clarification.

## What it does

Given a GitHub repository and free-text hiring criteria, the agent:

1. Detects whether the criteria are specific enough to evaluate fairly
   (and pauses to ask the user when they aren't)
2. Parses the criteria into structured, machine-verifiable predicates
3. Pulls contributor activity (PRs, reviews, commits) over a 365-day window
4. Computes a 0-100 impact score using a weighted feature set validated
   against hand-labeled ground truth
5. Verifies each predicate against the data with rule-based code
   (not LLM judgment), attaching real PR URLs as evidence
6. Loops back to gather more data when evidence is missing
7. Generates a per-candidate narrative that cites only verified outputs

The output is a ranked shortlist where every recommendation can be
traced back to specific commits and reviews — not just star counts.

## Architecture

| Layer | Implementation |
|---|---|
| Orchestration | LangGraph `StateGraph`, 7 nodes, conditional edge with iteration cap |
| LLMs | Sonnet 4.5 for nuance, Haiku 4.5 for structured extraction |
| Data | GitHub REST API + 1-hour file cache |
| Scoring | pandas weighted composite + rule-based predicate verification |
| HITL | LangGraph `interrupt()` surfaced via Streamlit form |
| Observability | LangSmith trace API |

See [docs/ADR-001..005](docs/) for the design decisions.

## Evaluation

| Metric | Value | Source |
|---|---|---|
| Spearman ρ vs hand-labeled ground truth | **0.722** | 15 axum contributors, scored 1-5 by domain reviewers |
| Explanation quality (LLM judge, 4 dimensions) | **4.07 / 5** | mean over 40 synthetic test variations |
| Pass rate (judge ≥ 3.5) | **98%** | excluding by-design 404-handling cases |
| Latency p50 (with cache) | ~25 s | per query |
| Cost per query | ~$0.04 | from LangSmith trace |

## Quick start

```bash
cd talent-scout

# 1. Configure secrets
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY, GITHUB_TOKEN, LANGSMITH_API_KEY

# 2. Run the platform
NSAppSleepDisabled=YES caffeinate -is .venv/bin/streamlit run app.py
```

> The `caffeinate` wrapper prevents macOS App Nap from throttling the
> background Python process.

Open http://localhost:8501. The sidebar's **Demo mode** toggle lets you
switch between live API calls and mock data (useful for layout previews).

### Try it

```
Repo:     tokio-rs/axum
Criteria: Find good Rust contributors
Top N:    5
```

The criteria are deliberately under-specified — `clarify_node` will
detect this and pause for follow-up. Reply with something like
`"Senior level. Role focus: framework design. Must-have skills: rust, async."`
and watch the rest of the graph execute in real time.

## File map

```
talent-scout/
├── app.py               Streamlit platform (5 tabs)
├── agent.py             LangGraph StateGraph + 7 nodes
├── tools.py             4 structured tools (no LLM)
├── eval.py              50-variation test harness + judge
├── scripts/
│   ├── smoke_test.py    End-to-end CLI verification
│   ├── ablation.py      Feature ablation against ground truth
│   └── finops.py        Pull token/cost data from LangSmith
├── prompts/             Versioned prompts (clarify_v1..v3, parser_v1..v3)
├── data/                Seed cases, ground truth, eval/ablation/finops CSVs
├── docs/                ADRs, scoring rationale, deployment guide,
│                        red-team analysis, failure post-mortem
└── requirements.txt
```

## License

Educational project for BAAI Genai course. Not licensed for redistribution.
