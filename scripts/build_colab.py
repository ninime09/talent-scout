"""Generate BAAI_Final.ipynb — the submission Colab notebook.

Cells are structured for instructor / grader experience:
  - Pre-computed eval results render instantly (no keys needed).
  - Live agent runs are gated behind a "have keys?" check.
  - Telemetry scaffolding (LangSmith) is referenced explicitly.

Run from the project root:
    .venv/bin/python scripts/build_colab.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "BAAI_Final.ipynb"

GITHUB_HTTPS = "https://github.com/ninime09/talent-scout.git"
STREAMLIT_URL = "https://share.streamlit.io/  (deploy this repo to get a live URL)"
LANGSMITH_PROJECT = "talent-scout"


def md(*lines: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": [l + "\n" for l in lines],
    }


def code(*lines: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": [l + "\n" for l in lines],
    }


cells: list[dict] = []

# ----------------------------------------------------------------------
# 1. Title + abstract
# ----------------------------------------------------------------------
cells.append(md(
    "# GitHub Talent Scout — BAAI Genai Final",
    "",
    "**Track A: LangGraph StateGraph** with 7 reasoning nodes, a conditional",
    "evidence-check loop, and human-in-the-loop clarification.",
    "",
    "## What this notebook contains",
    "",
    "| Section | Purpose |",
    "|---|---|",
    "| 1 · Architecture | The compiled LangGraph topology (mermaid SVG) |",
    "| 2 · Setup | Clone the repo and configure API keys |",
    "| 3 · Live demo (axum) | End-to-end agent run with HITL clarification |",
    "| 4 · Cross-repo demo (langgraph) | Same agent on a different ecosystem — proves generalization |",
    "| 5 · Pre-computed evaluation | 50-test eval matrix, ablation, consistency, FinOps |",
    "| 6 · Telemetry | Pointer to the LangSmith trace dashboard |",
    "| 7 · Documentation | Links to ADRs, PVC log, red team, failure analysis |",
    "",
    "**Companion deliverables**:",
    f"- GitHub repo: {GITHUB_HTTPS.replace('.git','')}",
    f"- Live Streamlit platform: {STREAMLIT_URL}",
    f"- LangSmith trace project: `{LANGSMITH_PROJECT}` on https://smith.langchain.com",
))

# ----------------------------------------------------------------------
# 2. Architecture
# ----------------------------------------------------------------------
cells.append(md(
    "## 1. Architecture",
    "",
    "Seven nodes, one conditional edge, one human-in-the-loop interrupt.",
    "Color encoding: **blue** = LLM-driven, **green** = rule-based,",
    "**yellow** = HITL, **pink** = decision branch, **purple** = I/O.",
))
cells.append(code(
    "from IPython.display import SVG, display",
    "import os",
    "svg_path = 'talent-scout/docs/architecture.svg'",
    "if os.path.exists(svg_path):",
    "    display(SVG(filename=svg_path))",
    "else:",
    "    print('Architecture SVG not found yet — run the Setup cells first.')",
))

# ----------------------------------------------------------------------
# 3. Setup
# ----------------------------------------------------------------------
cells.append(md(
    "## 2. Setup",
    "",
    "**Clone the repo**, install dependencies, and configure API keys.",
    "",
    "On Colab, paste the keys into **Secrets** (left sidebar key icon)",
    "with these exact names: `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`,",
    "`LANGSMITH_API_KEY`. The cell below will pick them up automatically.",
    "",
    "If you don't have keys, sections 3-4 will be skipped; the pre-computed",
    "evaluation in section 5 still works.",
))

cells.append(code(
    "# Clone the repository (no-op if already present).",
    f"!test -d talent-scout || git clone {GITHUB_HTTPS}",
    "%cd talent-scout",
    "!ls",
))

cells.append(code(
    "# Install dependencies (Colab usually already has streamlit/pandas).",
    "!pip install -q -r requirements.txt",
))

cells.append(code(
    "# Configure secrets. Tries Colab userdata first, then OS env, then .env file.",
    "import os",
    "",
    "def _load_secret(name):",
    "    try:",
    "        from google.colab import userdata",
    "        v = userdata.get(name)",
    "        if v:",
    "            os.environ[name] = v",
    "            return True",
    "    except Exception:",
    "        pass",
    "    return name in os.environ and os.environ[name].strip() != ''",
    "",
    "for k in ['ANTHROPIC_API_KEY', 'GITHUB_TOKEN', 'LANGSMITH_API_KEY']:",
    "    ok = _load_secret(k)",
    "    print(f'{k:25} {\"OK\" if ok else \"MISSING\"}')",
    "",
    "# LangSmith tracing (telemetry scaffolding) — log every LLM call.",
    "os.environ.setdefault('LANGSMITH_TRACING', 'true')",
    "os.environ.setdefault('LANGSMITH_PROJECT', 'talent-scout')",
    "os.environ.setdefault('LANGSMITH_ENDPOINT', 'https://api.smith.langchain.com')",
    "",
    "HAS_KEYS = all(",
    "    os.environ.get(k, '').strip()",
    "    for k in ['ANTHROPIC_API_KEY', 'GITHUB_TOKEN']",
    ")",
    "print()",
    "print(f'HAS_KEYS = {HAS_KEYS} — live cells will run' if HAS_KEYS",
    "      else 'HAS_KEYS = False — live cells will be skipped (pre-computed results still work)')",
))

# ----------------------------------------------------------------------
# 4. Live demo on axum
# ----------------------------------------------------------------------
cells.append(md(
    "## 3. Live demo — axum",
    "",
    "Submit an intentionally **under-specified** query so the",
    "`clarify_node` triggers an `interrupt()`. We then resume",
    "with structured criteria. The full trace is printed step by step;",
    "every LLM call is recorded in LangSmith for telemetry inspection.",
))

cells.append(code(
    "if not HAS_KEYS:",
    "    print('SKIPPED: live demo needs ANTHROPIC_API_KEY + GITHUB_TOKEN.')",
    "else:",
    "    import json, time, agent",
    "    from langgraph.types import Command",
    "    ",
    "    graph = agent.build_graph()",
    "    config = {'configurable': {'thread_id': f'colab-{int(time.time())}'}}",
    "    ",
    "    init_state = {",
    "        'query': 'Find good Rust contributors in tokio-rs/axum',",
    "        'repo_owner': 'tokio-rs',",
    "        'repo_name': 'axum',",
    "        'top_n': 3,",
    "        'criteria_text': 'Find good Rust contributors',",
    "        'trace': [],",
    "    }",
    "    ",
    "    def render(stream):",
    "        for chunk in stream:",
    "            if isinstance(chunk, dict):",
    "                for node, delta in chunk.items():",
    "                    if not isinstance(delta, dict):",
    "                        continue",
    "                    for entry in delta.get('trace', []) or []:",
    "                        print('─' * 70)",
    "                        print(f\"  node       : {entry['node']}\")",
    "                        print(f\"  observation: {entry['observation']}\")",
    "                        print(f\"  decision   : {entry['decision']}\")",
    "                        print(f\"  action     : {entry['action']}\")",
    "    ",
    "    print('Running first pass — expect interrupt at clarify_node…')",
    "    render(graph.stream(init_state, config=config, stream_mode='updates'))",
    "    ",
    "    snap = graph.get_state(config)",
    "    if getattr(snap, 'interrupts', ()):",
    "        info = snap.interrupts[0].value",
    "        print('\\nINTERRUPT — clarify_node asks:')",
    "        print(' ', info.get('follow_up_question', ''))",
    "        resume_text = ('Senior level. Role focus: framework design and async '",
    "                       'runtime. Must-have skills: rust, async, tokio.')",
    "        print(f'\\nResuming with: {resume_text!r}')",
    "        render(graph.stream(Command(resume=resume_text), config=config, stream_mode='updates'))",
    "    ",
    "    final = graph.get_state(config).values",
    "    if final.get('final_report'):",
    "        candidates = json.loads(final['final_report'])",
    "        print(f'\\nFINAL TALENT REPORT — {len(candidates)} candidates')",
    "        for c in candidates:",
    "            print(f\"\\n#{c['rank']} {c['username']}  score={c['score']}  predicates={c['predicates_passed']}\")",
    "            for p in c.get('passed', []):",
    "                ev = p.get('evidence', [])",
    "                first = ev[0] if ev and isinstance(ev[0], str) and ev[0].startswith('http') else ''",
    "                print(f\"    PASS {p['predicate']}\" + (f'  ← {first}' if first else ''))",
    "            for f in c.get('failed', []):",
    "                print(f\"    FAIL {f['predicate']} — {f.get('reason','')[:80]}\")",
))

# ----------------------------------------------------------------------
# 5. Cross-repo demo on langgraph
# ----------------------------------------------------------------------
cells.append(md(
    "## 4. Cross-repo verification — langchain-ai/langgraph",
    "",
    "The same agent, applied to a **Python AI library** (different stack from",
    "axum's Rust). The `criteria_parser_node` should generate stack-appropriate",
    "evidence patterns dynamically — not the axum-specific paths.",
    "",
    "This proves the agent is genuinely cross-repo, not single-repo plus",
    "marketing.",
))

cells.append(code(
    "if not HAS_KEYS:",
    "    print('SKIPPED: cross-repo demo needs API keys.')",
    "else:",
    "    import json, time, agent",
    "    ",
    "    graph = agent.build_graph()",
    "    config = {'configurable': {'thread_id': f'colab-cross-{int(time.time())}'}}",
    "    ",
    "    init_state = {",
    "        'query': 'Find Python framework architects',",
    "        'repo_owner': 'langchain-ai',",
    "        'repo_name': 'langgraph',",
    "        'top_n': 3,",
    "        'criteria_text': ('Senior Python framework architect. Must-have skills: '",
    "                           'async, type hints, agent state management.'),",
    "        'trace': [],",
    "    }",
    "    ",
    "    for chunk in graph.stream(init_state, config=config, stream_mode='updates'):",
    "        if isinstance(chunk, dict):",
    "            for node, delta in chunk.items():",
    "                if not isinstance(delta, dict):",
    "                    continue",
    "                for entry in delta.get('trace', []) or []:",
    "                    print(f\"[{entry['node']}] {entry['action']}\")",
    "    ",
    "    final = graph.get_state(config).values",
    "    parsed = final.get('parsed_criteria', {})",
    "    print('\\nDynamic evidence rules generated by criteria_parser_node:')",
    "    for rule in parsed.get('evidence_required', []):",
    "        if isinstance(rule, dict):",
    "            print(f\"  • {rule.get('name')}\")",
    "            print(f\"    patterns: {rule.get('file_path_patterns')}\")",
    "    ",
    "    if final.get('final_report'):",
    "        candidates = json.loads(final['final_report'])",
    "        print(f'\\nTop {len(candidates)} candidates on langgraph:')",
    "        for c in candidates:",
    "            print(f\"  #{c['rank']} {c['username']}  score={c['score']}  {c['predicates_passed']} predicates\")",
))

# ----------------------------------------------------------------------
# 6. Pre-computed evaluation — works without API keys
# ----------------------------------------------------------------------
cells.append(md(
    "## 5. Evaluation pipeline (pre-computed)",
    "",
    "These cells load the artifacts produced by `eval.py`, `scripts/ablation.py`,",
    "`scripts/consistency.py`, and `scripts/finops.py`. They run instantly and",
    "do not require API keys.",
    "",
    "### 5a · Ground-truth ranking quality (Spearman ρ)",
    "",
    "We hand-labeled 15 axum contributors (1-5 quality scores). The agent's",
    "ranking is compared to ground truth using Spearman rank correlation —",
    "the LLM is **not** in this loop.",
))

cells.append(code(
    "import pandas as pd",
    "df_abl = pd.read_csv('data/ablation_results.csv')",
    "baseline = df_abl[df_abl['feature_removed'] == 'none_full_model'].iloc[0]",
    "print(f\"Baseline Spearman ρ vs ground truth (n=15): {baseline['spearman']:.3f}\")",
    "print(f\"  Kendall τ: {baseline['kendall_tau']:.3f}\")",
    "print(f\"  Success threshold: ρ ≥ 0.50 — {'PASS' if baseline['spearman'] >= 0.5 else 'FAIL'}\")",
    "print()",
    "print('Feature ablation — drop one feature, re-evaluate:')",
    "df_abl",
))

cells.append(md(
    "### 5b · 50 synthetic test variations + LLM judge",
    "",
    "5 seed cases × 10 variations each, varying tone / specificity / edge cases /",
    "out-of-bounds parameters. Judge scores 4 dimensions (transparency,",
    "evidence linkage, clarity, adherence) on a 1-5 scale.",
))

cells.append(code(
    "df_eval = pd.read_csv('data/eval_results.csv')",
    "df_excl_s05 = df_eval[~df_eval['test_id'].str.startswith('S05_')]  # 404 cases fail by design",
    "",
    "print(f'Total tests run        : {len(df_eval)}')",
    "print(f'Mean judge score (all) : {df_eval[\"judge_score\"].mean():.2f} / 5')",
    "print(f'Mean judge (excl. S05) : {df_excl_s05[\"judge_score\"].mean():.2f} / 5')",
    "print(f'Pass rate (excl. S05)  : {df_excl_s05[\"success_flag\"].mean()*100:.0f}%')",
    "print()",
    "print('Per-dimension means (excl. S05):')",
    "for col in ['judge_transparency', 'judge_evidence_linkage', 'judge_clarity', 'judge_adherence']:",
    "    print(f\"  {col:25} {df_excl_s05[col].mean():.2f}\")",
    "print()",
    "df_eval.head(10)",
))

cells.append(md(
    "### 5c · Consistency Score (10 cases × 3 reps)",
    "",
    "Each core test case run 3 times. We measure ranking stability and",
    "judge variance — not just whether the agent returns N candidates.",
))

cells.append(code(
    "df_cons = pd.read_csv('data/consistency_summary.csv')",
    "valid = df_cons[df_cons['jaccard_mean'].notna()]",
    "",
    "print('Consistency (n =', len(valid), 'cases with ≥2 successful reps):')",
    "print(f\"  Top-N set overlap (Jaccard mean) : {valid['jaccard_mean'].mean():.3f}  (1.0 = identical)\")",
    "print(f\"  Top-1 stability                  : {valid['top1_stable'].mean()*100:.0f}%\")",
    "sp = valid['spearman_mean'].dropna()",
    "if len(sp):",
    "    print(f\"  Ranking Spearman ρ (mean)        : {sp.mean():.3f}\")",
    "print(f\"  Judge score std (mean across cases): {valid['judge_std'].mean():.3f}\")",
    "print()",
    "df_cons",
))

cells.append(md(
    "### 5d · FinOps — total spend, per-query cost, model assignment",
))

cells.append(code(
    "df_fin = pd.read_csv('data/finops.csv')",
    "n_eval = len(df_eval)",
    "total = df_fin['total_cost_usd'].sum()",
    "tokens = df_fin['total_tokens'].sum() if 'total_tokens' in df_fin.columns else (",
    "    df_fin['input_tokens'].sum() + df_fin['output_tokens'].sum()",
    ")",
    "print(f'Total spend (LangSmith captured) : ${total:.4f}')",
    "print(f'Total tokens                     : {int(tokens):,}')",
    "print(f'Cost per evaluation test         : ${total / max(n_eval, 1):.4f}')",
    "print()",
    "print('Per-node model assignment (cost-perf split):')",
    "print('  clarify_node      → Claude Sonnet 4.5')",
    "print('  criteria_parser   → Claude Haiku 4.5  (cheap structured extraction)')",
    "print('  report_node       → Claude Sonnet 4.5')",
    "print('  Judge (eval only) → Claude Haiku 4.5  (cross-model-size)')",
    "print()",
    "df_fin.head(10)",
))

# ----------------------------------------------------------------------
# 7. Telemetry
# ----------------------------------------------------------------------
cells.append(md(
    "## 6. Telemetry scaffolding (LangSmith)",
    "",
    "Every LLM invocation in every node is logged to LangSmith via the",
    "`LANGSMITH_TRACING=true` environment variable. The trace dashboard shows:",
    "",
    "- Per-node input / output / token counts / latency",
    "- Cost per call (auto-computed by LangSmith)",
    "- Full conversation chain for any individual run",
    "",
    "**Open the dashboard**: https://smith.langchain.com/o/(your-org)/projects/p/talent-scout",
    "",
    "The `scripts/finops.py` script is the bridge that pulls these traces and",
    "writes `data/finops.csv` (loaded above in section 5d). Re-run it after any",
    "agent execution to refresh the FinOps numbers.",
))

cells.append(code(
    "# Quick check: confirm LangSmith tracing is configured.",
    "import os",
    "for k in ['LANGSMITH_TRACING', 'LANGSMITH_PROJECT', 'LANGSMITH_API_KEY']:",
    "    v = os.environ.get(k, '')",
    "    print(f'{k:25} {\"set\" if v else \"MISSING\"}')",
))

# ----------------------------------------------------------------------
# 8. Documentation
# ----------------------------------------------------------------------
cells.append(md(
    "## 7. Documentation",
    "",
    "All written deliverables live in [docs/](docs/) of the repo:",
    "",
    "| File | Purpose |",
    "|---|---|",
    "| `ADR-001-model-split.md` | Why each node uses a different model |",
    "| `ADR-002-ai-vs-rules.md` | Where AI ends and rules begin |",
    "| `ADR-003-state-strategy.md` | LangGraph state schema + checkpointing |",
    "| `ADR-004-graceful-degradation.md` | Failure modes and responses |",
    "| `ADR-005-scoring-features.md` | 5 features, weights, ablation findings |",
    "| `SCORING_RATIONALE.md` | How free-text criteria become measurable predicates |",
    "| `PVC_LOG.md` | Prompt version control: v1 → v2 → v3 evolution |",
    "| `RED_TEAM.md` | 5 attack categories with defenses + residual risks |",
    "| `FAILURE_ANALYSIS.md` | 4 real bugs found via the eval pipeline + how we fixed them |",
    "| `INSTRUCTOR_FEEDBACK_RESPONSE.md` | Phase-1 reviewer critiques addressed point by point |",
    "| `DEPLOYMENT.md` | Streamlit Cloud deployment walkthrough |",
    "",
    "### Reproducing everything from scratch",
    "",
    "```bash",
    "# 1. Smoke test — single end-to-end query",
    "python scripts/smoke_test.py",
    "",
    "# 2. Cross-repo verification",
    "python scripts/cross_repo_test.py",
    "",
    "# 3. Feature ablation against ground truth (no LLM cost)",
    "python scripts/ablation.py",
    "",
    "# 4. Full eval pipeline (50 variations + judge)",
    "python eval.py",
    "",
    "# 5. Consistency score (10 cases × 3 reps)",
    "python scripts/consistency.py",
    "",
    "# 6. Pull LangSmith trace data into FinOps CSV",
    "python scripts/finops.py",
    "```",
))

# ----------------------------------------------------------------------
# Build notebook
# ----------------------------------------------------------------------
notebook = {
    "cells": cells,
    "metadata": {
        "colab": {
            "provenance": [],
            "toc_visible": True,
        },
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        },
        "language_info": {
            "name": "python",
        },
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

OUT.write_text(json.dumps(notebook, indent=1))
print(f"Wrote {OUT} ({len(cells)} cells, {OUT.stat().st_size} bytes)")
