"""GitHub Talent Scout — Streamlit platform UI.

Day 1 PM: real LangGraph agent wired in via `graph.stream(stream_mode="updates")`.
The mock data path remains as a fallback when API keys are not configured,
so the platform layout is always demonstrable.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit_mermaid as stmd
from dotenv import load_dotenv

load_dotenv()

# When running on Streamlit Cloud, secrets live in st.secrets and are NOT
# automatically exported to os.environ. Bridge them so agent.py + tools.py
# (which read os.environ) work both locally and in the cloud.
try:
    for _key, _val in dict(st.secrets).items():
        os.environ.setdefault(_key, str(_val))
except (FileNotFoundError, Exception):
    pass

DATA = Path(__file__).parent / "data"
DOCS = Path(__file__).parent / "docs"

st.set_page_config(
    page_title="GitHub Talent Scout — Track A (LangGraph)",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)


def _load_json(name: str):
    return json.loads((DATA / name).read_text())


def _load_csv(name: str) -> pd.DataFrame:
    return pd.read_csv(DATA / name)


def _read_doc(name: str) -> str:
    p = DOCS / name
    return p.read_text() if p.exists() else f"_{name} not yet written._"


def _have_keys() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and bool(
        os.environ.get("GITHUB_TOKEN")
    )


#]------------------------------------------------------------------------
# Live agent runner
#]------------------------------------------------------------------------


def _flatten_trace(updates: list[dict]) -> list[dict]:
    """A LangGraph 'updates' chunk is {node_name: state_delta}.
    Interrupt chunks have node_name "__interrupt__" with a tuple value
    instead of a dict — skip those (they are surfaced via get_state)."""
    trace = []
    for chunk in updates:
        if not isinstance(chunk, dict):
            continue
        for node_name, delta in chunk.items():
            if node_name == "__interrupt__" or not isinstance(delta, dict):
                continue
            for entry in delta.get("trace", []) or []:
                trace.append(entry)
    return trace


def render_trace_step(step_idx: int, entry: dict, container=None):
    target = container or st
    with target.status(
        f"Step {step_idx} — `{entry['node']}`", expanded=False, state="complete"
    ):
        st.markdown(f"**Observation:** {entry['observation']}")
        st.markdown(f"**Decision:** {entry['decision']}")
        st.markdown(f"**Action:** `{entry['action']}`")


def _drain_into(graph, stream, trace_box, step_counter):
    for chunk in stream:
        for entry in _flatten_trace([chunk]):
            step_counter[0] += 1
            render_trace_step(step_counter[0], entry, trace_box)


def _replay_existing_trace(state_values, trace_box, step_counter):
    """When Streamlit reruns mid-conversation, the in-memory step list is
    lost. Rebuild from the persisted state['trace'] before adding new steps."""
    for entry in state_values.get("trace", []) or []:
        step_counter[0] += 1
        render_trace_step(step_counter[0], entry, trace_box)


def run_live_agent(
    repo_owner: str,
    repo_name: str,
    criteria: str,
    top_n: int,
    output_container,
    *,
    start_new: bool,
):
    """Drive the LangGraph agent. Handles three states:
       - start_new: initial submit → kick off a fresh thread
       - mid-run with no interrupt: just render any existing trace + check final
       - interrupt pending: render trace + show resume form (outside any outer form)
    """
    import agent  # lazy import so UI loads even without API keys
    from langgraph.types import Command

    if "graph" not in st.session_state:
        st.session_state.graph = agent.build_graph()
    graph = st.session_state.graph

    if start_new or "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.run_active = True

    config = {"configurable": {"thread_id": st.session_state.thread_id}}
    trace_box = output_container.container()
    step_counter = [0]

    if start_new:
        init_state = {
            "query": f"Find {top_n} contributors in {repo_owner}/{repo_name}",
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "top_n": top_n,
            "criteria_text": criteria,
            "trace": [],
        }
        _drain_into(
            graph,
            graph.stream(init_state, config=config, stream_mode="updates"),
            trace_box,
            step_counter,
        )
    else:
        # Resumed rerun — replay the persisted trace so the UI shows context
        existing = graph.get_state(config).values
        _replay_existing_trace(existing, trace_box, step_counter)

    snapshot = graph.get_state(config)
    interrupts = getattr(snapshot, "interrupts", ()) or ()
    if interrupts:
        info = interrupts[0].value
        with output_container.form("clarify_form", clear_on_submit=False):
            st.warning(info.get("follow_up_question", "Please add detail."))
            missing = info.get("missing", [])
            user_addition = st.text_area(
                f"Provide: {', '.join(missing)}",
                key="clarify_input",
                value=st.session_state.get("clarify_input", ""),
            )
            resumed = st.form_submit_button("Resume agent")
        if not resumed:
            # Stay paused; on next rerun we'll redraw the form.
            return None
        _drain_into(
            graph,
            graph.stream(
                Command(resume=user_addition),
                config=config,
                stream_mode="updates",
            ),
            trace_box,
            step_counter,
        )

    final_state = graph.get_state(config).values
    payload = final_state.get("final_report")
    if payload:
        # Run complete — clear the active flag so next "Run Agent" starts fresh
        st.session_state.run_active = False
        return json.loads(payload)
    return None


#]------------------------------------------------------------------------
# Sidebar
#]------------------------------------------------------------------------


with st.sidebar:
    st.markdown("### About")
    st.markdown(
        "Turn scattered GitHub activity into **evidence-grounded "
        "hiring reports** — not raw stars and commit counts, but "
        "verified predicates with linked PR evidence."
    )
    st.divider()
    st.markdown("### How to read the trace")
    st.markdown(
        "- 🔵 **AI nodes** — LLM reasoning (Sonnet / Haiku)\n"
        "- 🟢 **Rule nodes** — deterministic Python\n"
        "- 🟡 **HITL** — human-in-the-loop clarification\n"
        "- 🩷 **Decision** — conditional branch in the graph"
    )
    st.divider()
    st.caption("Track A · LangGraph StateGraph")
    st.caption("Observability via LangSmith")

    keys_ok = _have_keys()
    with st.expander("Demo mode", expanded=False):
        mode = st.radio(
            "Mode",
            ["Live agent", "Mock (no keys)"],
            index=0 if keys_ok else 1,
            help="Live calls real GitHub + LLM. Mock uses cached sample data.",
            label_visibility="collapsed",
        )
        if mode == "Live agent" and not keys_ok:
            st.error("Live mode needs ANTHROPIC_API_KEY and GITHUB_TOKEN.")


#]------------------------------------------------------------------------
# Header
#]------------------------------------------------------------------------


st.title("GitHub Talent Scout")
st.caption(
    "Multi-step agent that turns scattered GitHub activity into "
    "evidence-grounded hiring reports — every claim cites a real PR."
)


tab_run, tab_arch, tab_eval, tab_finops, tab_score = st.tabs(
    ["Run Agent", "Architecture", "Evaluation", "FinOps", "Scoring Rationale"]
)

# ============================================================
# Tab 1: Run Agent
# ============================================================
with tab_run:
    col_input, col_output = st.columns([1, 2])

    with col_input:
        st.subheader("Inputs")
        with st.form("agent_inputs"):
            repo_owner = st.text_input("Repo owner", value="tokio-rs")
            repo_name = st.text_input("Repo name", value="axum")
            criteria = st.text_area(
                "Hiring criteria (free text)",
                value="Find good Rust contributors",
                help="Vague criteria triggers a clarification step.",
                height=100,
            )
            top_n = st.slider("Top N candidates", 3, 15, 5)
            submitted = st.form_submit_button("Run Agent", type="primary")

    with col_output:
        st.subheader("Live agent trace")
        st.caption(
            "Each step shows what the agent **observed**, what it **decided**, "
            "and what **action** it took next. Submit the form to start; vague "
            "criteria will trigger a clarification step before the agent proceeds."
        )

        # The "Run Agent" form submit kicks off a fresh thread.
        # If a run is already in progress (waiting on a clarify interrupt),
        # subsequent reruns continue it via session_state.run_active.
        is_running = bool(st.session_state.get("run_active"))
        should_render = submitted or is_running

        if should_render:
            if mode == "Live agent" and keys_ok:
                try:
                    result = run_live_agent(
                        repo_owner,
                        repo_name,
                        criteria,
                        top_n,
                        st.container(),
                        start_new=submitted,
                    )
                except Exception as e:  # surface the failure visibly
                    st.error(f"Live run failed: {type(e).__name__}: {e}")
                    st.session_state.run_active = False
                    result = None
            else:
                result = None
                trace = _load_json("mock_trace.json")
                for i, step in enumerate(trace, 1):
                    render_trace_step(i, step)

            if result:
                st.divider()
                st.subheader("Ranked candidates")
                df = pd.DataFrame(result)
                cols = [
                    c
                    for c in [
                        "rank",
                        "username",
                        "score",
                        "predicates_passed",
                        "merged_prs",
                        "reviews",
                        "last_commit",
                    ]
                    if c in df.columns
                ]
                st.dataframe(df[cols], use_container_width=True, hide_index=True)
                st.subheader("Per-candidate reasoning")
                for c in result:
                    with st.expander(
                        f"#{c['rank']} {c['username']} — score {c['score']} "
                        f"({c['predicates_passed']} predicates)"
                    ):
                        st.write(c.get("reasoning", "(no narrative)"))
                        st.markdown("**Predicate outcomes:**")
                        for p in c.get("passed", []):
                            st.markdown(f"- ✅ `{p['predicate']}`")
                        for f in c.get("failed", []):
                            st.markdown(f"- ❌ `{f['predicate']}` — {f['reason']}")
                        if c.get("evidence_links"):
                            st.markdown("**Evidence:**")
                            for link in c["evidence_links"]:
                                st.markdown(f"- {link}")
            elif mode != "Live agent" or not keys_ok:
                # Mock fallback display (mock mode only — never mid-run in live)
                st.divider()
                st.subheader("Ranked candidates (mock data)")
                candidates = _load_json("mock_candidates.json")
                df = pd.DataFrame(candidates)[
                    [
                        "rank",
                        "username",
                        "impact_score",
                        "merged_prs",
                        "reviews",
                        "recency_days",
                        "review_acceptance",
                        "predicates_passed",
                    ]
                ]
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.subheader("Per-candidate reasoning")
                for c in candidates:
                    with st.expander(
                        f"#{c['rank']} {c['username']} — score {c['impact_score']} "
                        f"({c['predicates_passed']} predicates)"
                    ):
                        st.write(c["reasoning"])
                        st.markdown("**Evidence:**")
                        for link in c["evidence_links"]:
                            st.markdown(f"- {link}")
        else:
            st.info(
                "Submit the form to run the agent. The example query "
                "`Find good Rust contributors` is intentionally underspecified "
                "and will trigger the clarify_node interrupt."
            )

# ============================================================
# Tab 2: Architecture
# ============================================================
with tab_arch:
    st.subheader("Track A — LangGraph StateGraph")
    st.markdown(
        "**Nodes:** `clarify_node` → `criteria_parser_node` → "
        "`search_contributors_node` → `get_user_activity_node` → "
        "`score_node` → `report_node`. **Conditional edge** "
        "`evidence_check` loops back to `expand_window_node` → "
        "`get_user_activity_node` when required evidence is missing "
        "(max 2 iterations). **HITL:** `clarify_node` uses `interrupt()` "
        "for missing dimensions."
    )

    # Pre-rendered SVG (via mermaid CLI) — avoids streamlit-mermaid 0.3.0
    # subgraph + HTML rendering issues. Source: docs/architecture.mmd
    arch_svg_path = Path(__file__).parent / "docs" / "architecture.svg"
    if arch_svg_path.exists():
        st.image(str(arch_svg_path), use_container_width=True)
    else:
        st.warning("docs/architecture.svg missing — re-render with: "
                   "npx @mermaid-js/mermaid-cli@10.2.4 -i docs/architecture.mmd "
                   "-o docs/architecture.svg --width 1600")

    # Color legend
    leg_a, leg_b, leg_c, leg_d, leg_e = st.columns(5)
    with leg_a:
        st.markdown(
            "<div style='background:#dbeafe;border:2px solid #1e40af;"
            "padding:6px;border-radius:4px;text-align:center;color:#1e3a8a;"
            "font-weight:600;font-size:13px'>AI · LLM call</div>",
            unsafe_allow_html=True,
        )
    with leg_b:
        st.markdown(
            "<div style='background:#dcfce7;border:2px solid #166534;"
            "padding:6px;border-radius:4px;text-align:center;color:#14532d;"
            "font-weight:600;font-size:13px'>Rule · deterministic</div>",
            unsafe_allow_html=True,
        )
    with leg_c:
        st.markdown(
            "<div style='background:#fef3c7;border:2px solid #92400e;"
            "padding:6px;border-radius:4px;text-align:center;color:#78350f;"
            "font-weight:600;font-size:13px'>HITL · human input</div>",
            unsafe_allow_html=True,
        )
    with leg_d:
        st.markdown(
            "<div style='background:#fce7f3;border:2px solid #9d174d;"
            "padding:6px;border-radius:4px;text-align:center;color:#831843;"
            "font-weight:600;font-size:13px'>Decision · branch</div>",
            unsafe_allow_html=True,
        )
    with leg_e:
        st.markdown(
            "<div style='background:#ede9fe;border:2px solid #6b21a8;"
            "padding:6px;border-radius:4px;text-align:center;color:#581c87;"
            "font-weight:600;font-size:13px'>I/O boundary</div>",
            unsafe_allow_html=True,
        )

    st.caption("Solid arrows = forward edges. Dashed = resume / loop.")

    st.divider()
    st.subheader("Design decisions")
    for adr, title in [
        ("ADR-001-model-split.md", "ADR-001 · Model split (cost-perf + judge independence)"),
        ("ADR-002-ai-vs-rules.md", "ADR-002 · AI vs. rule-based per step"),
        ("ADR-003-state-strategy.md", "ADR-003 · State strategy"),
        ("ADR-004-graceful-degradation.md", "ADR-004 · Graceful degradation"),
        ("ADR-005-scoring-features.md", "ADR-005 · Scoring features and weights"),
    ]:
        with st.expander(title):
            st.markdown(_read_doc(adr))

# ============================================================
# Tab 3: Evaluation
# ============================================================
with tab_eval:
    df_eval = _load_csv("eval_results.csv")
    df_abl = _load_csv("ablation_results.csv")

    baseline_spearman = df_abl[df_abl["feature_removed"] == "none_full_model"][
        "spearman"
    ].iloc[0]
    df_excl_s05 = df_eval[~df_eval["test_id"].str.startswith("S05_")]

    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        st.metric("Spearman ρ", f"{baseline_spearman:.3f}",
                  help="vs. 15-user hand-labeled ground truth")
    with col_b:
        st.metric(
            "Explanation quality",
            f"{df_excl_s05['judge_score'].mean():.2f} / 5",
            help="LLM judge, 4 dimensions, excludes by-design failures",
        )
    with col_c:
        st.metric(
            "Pass rate",
            f"{df_excl_s05['success_flag'].mean()*100:.0f}%",
            help="Judge ≥ 3.5",
        )
    with col_d:
        st.metric("Tests run", f"{len(df_eval)}")

    st.markdown("### Two evaluation layers")
    st.markdown(
        f"**Hard metric — ranking quality.** Spearman ρ between the agent's "
        f"ranking and a hand-labeled benchmark of 15 Axum contributors "
        f"(scored 1-5 by domain reviewers, no LLM in the loop). "
        f"**ρ = {baseline_spearman:.3f}** clears the 0.50 significance threshold."
    )
    st.markdown(
        f"**Soft metric — explanation quality.** A separate LLM judge scores "
        f"each report on transparency, evidence linkage, clarity, and adherence. "
        f"Mean **{df_excl_s05['judge_score'].mean():.2f}/5** across 50 synthetic "
        f"test variations (excluding the graceful-degradation 404-repo set, "
        f"which fails by design)."
    )

    st.subheader("All test results")
    st.dataframe(df_eval, use_container_width=True, hide_index=True)
    st.caption(
        "Success defined as `judge_score ≥ 3.5`. The `S05_repo_404_*` cases "
        "are intentionally pointed at a non-existent repository to verify "
        "graceful 404 handling."
    )

# ============================================================
# Tab 4: FinOps
# ============================================================
with tab_finops:
    df_fin = _load_csv("finops.csv")
    df_eval_for_fin = _load_csv("eval_results.csv")

    total_spend = df_fin["total_cost_usd"].sum()
    total_tokens = df_fin["total_tokens"].sum() if "total_tokens" in df_fin.columns else (
        df_fin["input_tokens"].sum() + df_fin["output_tokens"].sum()
    )
    n_eval = len(df_eval_for_fin)
    cost_per_eval = total_spend / max(n_eval, 1)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total spend", f"${total_spend:.4f}")
    with c2:
        st.metric("Total tokens", f"{int(total_tokens):,}")
    with c3:
        st.metric("Cost per query", f"${cost_per_eval:.4f}")
    with c4:
        st.metric(
            "Pass rate",
            f"{df_eval_for_fin['success_flag'].mean()*100:.0f}%",
            help="Judge score ≥ 3.5",
        )

    st.markdown("### Per-node model assignment")
    st.markdown(
        "Different nodes get different models based on the cost vs. nuance "
        "trade-off. Heavy reasoning gets Sonnet; structured extraction gets "
        "the cheaper Haiku. Full reasoning in [ADR-001 in Architecture tab]."
    )
    st.markdown(
        "| Node | Model | Why |\n"
        "|---|---|---|\n"
        "| `clarify_node` | Sonnet 4.5 | Linguistic nuance to detect missing dims |\n"
        "| `criteria_parser_node` | Haiku 4.5 | Structured JSON extraction — cheap is fine |\n"
        "| `report_node` | Sonnet 4.5 | Final narrative quality matters |\n"
        "| Judge (eval only) | Haiku 4.5 | Cross-model-size to reduce self-eval bias |"
    )

    st.markdown("### Per-trace breakdown")
    st.dataframe(df_fin, use_container_width=True, hide_index=True)
    st.caption(
        "Per-LLM-call traces from LangSmith. Latency is per-call, "
        "not full agent-query time."
    )

# ============================================================
# Tab 5: Scoring Rationale
# ============================================================
with tab_score:
    st.subheader("Why these features and weights?")
    st.markdown(
        "Each candidate's 0-100 impact score combines five activity signals "
        "with weights chosen a priori, then **validated by ablation against "
        "hand-labeled ground truth**. The methodology and findings — "
        "including a surprising result that contradicted our initial "
        "intuition — are below."
    )

    st.markdown(_read_doc("SCORING_RATIONALE.md"))

    st.subheader("Feature ablation")
    st.markdown(
        "Each row drops one feature, renormalizes the rest, and re-evaluates "
        "against the 15-user ground truth. A larger negative `delta_vs_full` "
        "means the feature contributed more to ranking quality."
    )
    df_abl = _load_csv("ablation_results.csv")
    st.dataframe(df_abl, use_container_width=True, hide_index=True)
