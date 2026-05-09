"""End-to-end smoke test that drives the LangGraph agent from the CLI.

Runs the demo query intentionally under-specified to exercise the
clarify interrupt + resume path. Prints every trace entry as it happens.
"""
from __future__ import annotations

import functools
import json
import sys
import time
from pathlib import Path

# Force flush on every print so this works behind pipes/nohup.
print = functools.partial(print, flush=True)

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

print(f"[{time.strftime('%H:%M:%S')}] importing dotenv…")
from dotenv import load_dotenv

load_dotenv()
print(f"[{time.strftime('%H:%M:%S')}] importing langgraph…")
from langgraph.types import Command  # noqa: E402

print(f"[{time.strftime('%H:%M:%S')}] importing agent (this triggers ChatAnthropic import — can be slow)…")
import agent  # noqa: E402

print(f"[{time.strftime('%H:%M:%S')}] all imports done")


SEPARATOR = "─" * 70


def render_trace(state_delta) -> int:
    if not isinstance(state_delta, dict):
        return 0
    entries = state_delta.get("trace") or []
    for e in entries:
        print(SEPARATOR)
        print(f"  node       : {e['node']}")
        print(f"  observation: {e['observation']}")
        print(f"  decision   : {e['decision']}")
        print(f"  action     : {e['action']}")
    return len(entries)


def drain(stream) -> int:
    n = 0
    for chunk in stream:
        # LangGraph streams: normal chunks are {node_name: state_delta}.
        # Interrupt chunks are {"__interrupt__": (Interrupt(...),)} — value is
        # a tuple, not a dict, so render_trace must accept and skip non-dicts.
        if isinstance(chunk, dict):
            for node_name, delta in chunk.items():
                if node_name == "__interrupt__":
                    print(SEPARATOR)
                    print(f"  [INTERRUPT signal received from upstream]")
                    continue
                n += render_trace(delta)
    return n


def main() -> int:
    print("=" * 70)
    print(f"[{time.strftime('%H:%M:%S')}] Building LangGraph…")
    graph = agent.build_graph()
    print(f"[{time.strftime('%H:%M:%S')}] graph built")
    config = {"configurable": {"thread_id": "smoke-1"}}

    init_state = {
        "query": "Find good Rust contributors in tokio-rs/axum",
        "repo_owner": "tokio-rs",
        "repo_name": "axum",
        "top_n": 3,
        "criteria_text": "Find good Rust contributors",
        "trace": [],
    }

    print(f"[{time.strftime('%H:%M:%S')}] Running first pass (expect interrupt)…")
    print("=" * 70)
    t0 = time.time()
    drain(graph.stream(init_state, config=config, stream_mode="updates"))

    snapshot = graph.get_state(config)
    interrupts = getattr(snapshot, "interrupts", ()) or ()
    if not interrupts:
        print("\nWARN: no interrupt fired — clarify_node may have")
        print("decided the criteria was sufficient.")
    else:
        info = interrupts[0].value
        print()
        print("=" * 70)
        print("INTERRUPT received from clarify_node:")
        print(f"  follow_up  : {info.get('follow_up_question')}")
        print(f"  missing    : {info.get('missing')}")
        print()
        resume_text = (
            "Senior level. Role focus: framework design. "
            "Must-have skills: rust, async."
        )
        print(f"Resuming with: {resume_text!r}")
        print("=" * 70)
        drain(
            graph.stream(
                Command(resume=resume_text),
                config=config,
                stream_mode="updates",
            )
        )

    elapsed = time.time() - t0
    print("\n" + "=" * 70)
    final = graph.get_state(config).values
    payload = final.get("final_report")
    if payload:
        candidates = json.loads(payload)
        print(f"FINAL TALENT REPORT — {len(candidates)} candidates "
              f"(elapsed {elapsed:.1f}s)")
        print("=" * 70)
        for c in candidates:
            print(
                f"\n#{c['rank']} {c['username']}  score={c['score']}  "
                f"predicates={c['predicates_passed']}  "
                f"merged_prs={c['merged_prs']}"
            )
            if c.get("reasoning"):
                print(f"  reasoning: {c['reasoning'][:240]}")
            for p in c.get("passed", []):
                print(f"    PASS {p['predicate']}")
            for f in c.get("failed", []):
                print(f"    FAIL {f['predicate']} — {f['reason']}")
    else:
        print("ERROR: no final_report in state")
        print(f"State keys: {list(final.keys())}")
        return 1

    print("\n" + "=" * 70)
    print("SMOKE TEST PASSED")
    print(f"Total elapsed: {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
