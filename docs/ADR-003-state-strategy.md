## ADR-003: State strategy

### Decision

- `AgentState` is a `TypedDict` with explicit fields:
  `query`, `criteria_text`, `parsed_criteria`, `predicates`, `candidates`,
  `evidence_log`, `iteration_count`, `messages`.
- LangGraph `MemorySaver` checkpointer is enabled to support `interrupt()`
  resume in `clarify_node` (the human-in-the-loop step).
- Streamlit `st.session_state` holds the `thread_id` so a single user
  session maps to one LangGraph thread; this allows interrupt/resume to
  survive Streamlit script reruns triggered by the resume form submission.

### Why TypedDict over Pydantic

LangGraph supports both. TypedDict is lighter and avoids serialization
edge cases when checkpointing — the agent state is checkpointed after
every node, and Pydantic models occasionally produce surprising
round-trip behavior with nested optional fields.

### Why MemorySaver over a persistent backend

For a single-session demo this is sufficient and zero-config. For
production deployment with multi-user resume across sessions, this would
be replaced with `SqliteSaver` or `PostgresSaver`.
