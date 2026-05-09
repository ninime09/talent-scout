# Failure Analysis Post-Mortem

Three concrete failure modes encountered during MVP development, with
root cause + fix + lesson.

---

## Failure 1: `merged_pr_count` was the wrong dominant signal

**Discovered:** Day 2 AM during ablation experiment.

**Symptom.** When we computed Spearman ρ between agent rankings and
Jennifer's hand-labeled ground truth (n=10 partial run), dropping
`merged_pr_count` *improved* the correlation by +0.113. Initial weight
choices (0.30 for merged_pr_count, the highest) reflected a
quantity-over-quality intuition that the data did not support.

**Root cause.** The labeler scored on *contribution quality and design
influence*, not raw PR volume. Specifically:
- `tottoto`: GT=3, agent=67.4, 46 PRs — over-rated because high PR
  count was mostly maintenance, not architectural ownership.
- `davidpdrsn`: GT=5, agent=47.8, 5 PRs — severely under-rated
  because foundational maintainers can be currently low-volume.

**Fix.** None applied to weights (avoiding overfit on small sample).
Documented honestly in ADR-005 with full ablation table. Future work:
add `contribution_diversity` feature (touches multiple modules vs one
narrow module) to capture what `merged_pr_count` was trying to proxy.

**Lesson.** Validate weight intuitions against ground truth before
locking them in. The full n=15 run later showed the n=10 finding
exaggerated the effect (delta +0.034 not +0.113), reinforcing the
"don't retune on tiny samples" lesson.

---

## Failure 2: `framework_design_pr` detection silently always returned False

**Discovered:** First successful smoke test, Day 2 (12:54).

**Symptom.** Every candidate failed the `has_framework_design_pr`
predicate, triggering the `evidence_check` conditional loop on every
single run. `evaluate_predicates.missing_evidence` always contained
`framework_design_pr` regardless of who the candidate was.

**Root cause.** `tools.py:FRAMEWORK_DESIGN_PATH_HINTS` used path
prefixes like `src/extract`, `src/routing`. But axum is multi-crate:
its actual file paths are `axum/src/extract/...`,
`axum-core/src/...`, etc. The `startswith` check never matched.

**Fix.**
1. Changed prefix matching to substring matching with `/src/extract`
   etc.
2. Added `axum-core/src/` as a separate hint for that crate.

After fix: jplatte found 12 framework-design PRs, davidpdrsn found 2.

**Lesson.** Heuristics that depend on filesystem layout MUST be
validated against the live data they operate on. A unit test against
real GitHub PR file lists would have caught this immediately. Adding
this to Day 3 hardening backlog.

---

## Failure 3: macOS App Nap throttled background imports to ~15 minutes

**Discovered:** First few smoke test attempts (Day 2 mid-morning).

**Symptom.** When the smoke test was launched as a background process
(via `nohup ... &`), Python prints showed "[12:27:25] importing
langgraph…" but the next print (`importing agent`) didn't appear for
6+ minutes. Process state was `SN` (sleeping interruptible, low
priority) with only 1.5 seconds of CPU time after 10 minutes elapsed.

**Root cause.** macOS App Nap aggressively throttles background
processes that aren't visibly active. Python imports — which load many
shared libraries — got throttled to nearly zero scheduling slots.

**Fix.** Wrap the Python invocation:
```bash
NSAppSleepDisabled=YES caffeinate -is .venv/bin/python -u eval.py
```
- `NSAppSleepDisabled=YES` opts out of App Nap at the env-var level.
- `caffeinate -is` keeps the system "active" so background processes
  don't get throttled.
- `python -u` ensures unbuffered stdout (separate issue from App Nap
  but observed at the same time — buffered stdout hid the throttling
  symptom).

After fix: smoke test completed in 54 seconds.

**Lesson.** When a Python script appears "hung" with no progress and
low CPU on macOS, suspect App Nap before suspecting the script logic.
Documented this pattern in `README.md` so future MVPs avoid the same
debugging loop.

---

---

## Failure 4: `report_node` fallback narrative was a placeholder, not synthesis

**Discovered:** Day 2 PM, when the eval Judge consistently flagged S03
variations with explanation-quality score 2.25 ("reasoning field
explicitly states fallback to raw evidence rather than synthesized
analysis").

**Symptom.** When `report_node`'s LLM JSON output couldn't be parsed by
the brittle `{"items": [...]}` wrapping hack, every candidate's
`reasoning` field became the literal string
`"(report generation fell back to raw evidence)"`. Judge correctly
identified this as low-quality output (because it WAS) and dragged the
mean from 4.07 down to 3.25 across the 50-test set.

**Root cause.** Two issues in the same code path:
1. The original parser wrapped the LLM's JSON list in `{"items": [...]}`
   then parsed as object — fragile to trailing characters or any LLM
   prose around the list.
2. The fallback handler wrote a hardcoded placeholder rather than
   synthesizing from the rule data we already had.

**Fix.**
1. Multi-strategy parser (`_try_parse_narratives`): tries direct list
   parse, then markdown-fence stripping, then brace-matched object
   extraction. Returns `None` only when all strategies fail.
2. New `_synthesize_narrative()`: when LLM parsing fails, builds a real
   evidence-grounded paragraph from the candidate's predicate
   pass/fail data + framework-design PR list. The fallback is now
   *better* than the original placeholder because it's anchored in
   verified rule outputs rather than empty filler.

After fix: re-ran the 13 affected variations. S03 jumped from 2.25 to
4.0-4.5 across all 10 cases. Mean improved 2.73 → 3.25 (or 3.37 → 4.07
excluding S05).

**Lesson.** A fallback path is part of the product, not "what happens
when things break". If the fallback writes lower-quality output than
the happy path, the eval pipeline will surface that — but only if you
have an eval pipeline that scores on quality, not just success. Which
loops back to the meta-lesson below.

---

## Recurring meta-lesson

Two of three failures (#1 and #2) were *silent* failures —
the system kept running and produced output that looked plausible but
was wrong. Both were caught only because we built the ablation /
ground-truth evaluation harness. **The evaluation pipeline didn't just
measure quality — it surfaced bugs the agent would otherwise have
hidden.**

This is a defense of why the project allocates 50% of its compute
budget to evaluation rather than to the agent itself.
