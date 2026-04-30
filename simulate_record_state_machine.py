#!/usr/bin/env python3
# ruff: noqa: T201  # CLI demo: all output via print
"""Interactive CLI simulation of the Record State Machine.

Walks through the qanalabs_quiz_gen workflow showing how 5 records
flow through actions, with state transitions at each step.

Uses the same :class:`agent_actions.record.state.RecordState` values and the
same reset/cascade sets as :mod:`agent_actions.processing.task_preparer`, so
the walkthrough stays aligned with production semantics.

Demonstrates every state in the machine:
  active, processed, committed, guard_skipped, guard_deferred,
  guard_filtered, exhausted, cascade_skipped, failed

Usage:
    python simulate_record_state_machine.py              # interactive
    python simulate_record_state_machine.py --validate    # non-interactive checks (CI)

Press ENTER to advance each step. Press 'q' to quit.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
from datetime import datetime, timedelta

from agent_actions.record.state import (
    CASCADE_BLOCKING_STATES,
    RESETTABLE_DOWNSTREAM_STATES,
    RecordState,
)
from agent_actions.storage.backend import (
    DISPOSITION_CASCADE_SKIPPED,
    DISPOSITION_EXHAUSTED,
    DISPOSITION_FAILED,
    DISPOSITION_GUARD_DEFERRED,
    DISPOSITION_GUARD_FILTERED,
    DISPOSITION_GUARD_SKIPPED,
    DISPOSITION_SUCCESS,
)

# ─── Aligned with TaskPreparer (must match framework) ───────────────────────

FLOWS_AS_ACTIVE: frozenset[RecordState] = RESETTABLE_DOWNSTREAM_STATES
PROPAGATES_AS_CASCADE: frozenset[RecordState] = CASCADE_BLOCKING_STATES

PROCESSABLE = frozenset(s for s in RecordState if s.is_processable())
SETTLED_RETRIABLE = frozenset(s for s in RecordState if s.is_retriable())
SETTLED_BY_DESIGN = frozenset(s for s in RecordState if s.is_settled() and not s.is_retriable())

DISPOSITION_MAP: dict[RecordState, str] = {
    RecordState.COMMITTED: DISPOSITION_SUCCESS,
    RecordState.GUARD_SKIPPED: DISPOSITION_GUARD_SKIPPED,
    RecordState.GUARD_DEFERRED: DISPOSITION_GUARD_DEFERRED,
    RecordState.GUARD_FILTERED: DISPOSITION_GUARD_FILTERED,
    RecordState.EXHAUSTED: DISPOSITION_EXHAUSTED,
    RecordState.FAILED: DISPOSITION_FAILED,
    RecordState.CASCADE_SKIPPED: DISPOSITION_CASCADE_SKIPPED,
}


def validate_framework_alignment() -> None:
    """Fail fast if this script drifts from framework definitions."""

    assert FLOWS_AS_ACTIVE == RESETTABLE_DOWNSTREAM_STATES, (
        "Simulation FLOWS_AS_ACTIVE must match RESETTABLE_DOWNSTREAM_STATES"
    )
    assert PROPAGATES_AS_CASCADE == CASCADE_BLOCKING_STATES, (
        "Simulation PROPAGATES_AS_CASCADE must match CASCADE_BLOCKING_STATES"
    )
    expected_dispositions = {
        RecordState.COMMITTED: DISPOSITION_SUCCESS,
        RecordState.GUARD_SKIPPED: DISPOSITION_GUARD_SKIPPED,
        RecordState.GUARD_DEFERRED: DISPOSITION_GUARD_DEFERRED,
        RecordState.GUARD_FILTERED: DISPOSITION_GUARD_FILTERED,
        RecordState.EXHAUSTED: DISPOSITION_EXHAUSTED,
        RecordState.FAILED: DISPOSITION_FAILED,
        RecordState.CASCADE_SKIPPED: DISPOSITION_CASCADE_SKIPPED,
    }
    assert DISPOSITION_MAP == expected_dispositions, "DISPOSITION_MAP drifted from storage/backend.py"

_interactive = True

STATE_COLORS = {
    RecordState.ACTIVE: "\033[97m",  # white
    RecordState.PROCESSED: "\033[96m",  # cyan
    RecordState.COMMITTED: "\033[92m",  # green
    RecordState.GUARD_SKIPPED: "\033[93m",  # yellow
    RecordState.GUARD_DEFERRED: "\033[95m",  # magenta
    RecordState.GUARD_FILTERED: "\033[90m",  # gray
    RecordState.EXHAUSTED: "\033[91m",  # red
    RecordState.CASCADE_SKIPPED: "\033[33m",  # dark yellow
    RecordState.FAILED: "\033[91m",  # red
}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
UNDERLINE = "\033[4m"

# Simulated clock
_sim_time = datetime(2026, 4, 29, 14, 0, 0)


def sim_now():
    global _sim_time
    _sim_time += timedelta(seconds=2)
    return _sim_time.strftime("%H:%M:%S")


def colored(text: str, state: RecordState) -> str:
    return f"{STATE_COLORS.get(state, '')}{text}{RESET}"


def bold(text):
    return f"{BOLD}{text}{RESET}"


def dim(text):
    return f"{DIM}{text}{RESET}"


# ─── Record ───────────────────────────────────────────────────────────────────


class Record:
    def __init__(self, id, label, source_url):
        self.id = id
        self.label = label
        self.source_url = source_url
        self.state = RecordState.ACTIVE
        self.history = []
        self.data = {}

    def transition(self, new_state, action, reason="", detail=""):
        old = self.state
        self.state = new_state
        self.history.append(
            {
                "from": old,
                "to": new_state,
                "action": action,
                "reason": reason,
                "detail": detail,
                "timestamp": sim_now(),
            }
        )

    def is_processable(self):
        return self.state in PROCESSABLE

    def is_settled(self):
        return self.state.is_settled()

    def state_display(self) -> str:
        return colored(self.state.value, self.state)


# ─── Display ──────────────────────────────────────────────────────────────────


def clear() -> None:
    if not _interactive:
        return
    os.system("clear" if os.name != "nt" else "cls")


def wait(msg: str = "") -> None:
    if not _interactive:
        return
    prompt = f"\n{dim('Press ENTER to continue' + (f' ({msg})' if msg else '') + '  [q to quit]')}"
    try:
        result = input(prompt)
        if result.strip().lower() == "q":
            print("\nExiting.")
            sys.exit(0)
    except (EOFError, KeyboardInterrupt):
        print("\nExiting.")
        sys.exit(0)


def print_header(phase, action_name, action_kind="llm", intent=""):
    width = 80
    print(f"\n{'═' * width}")
    print(f"  {bold(phase)}")
    print(f"  Action: {bold(action_name)}  ({action_kind})")
    if intent:
        print(f"  {dim(intent)}")
    print(f"{'═' * width}")


def print_records(records, label="Records"):
    """Print only visible records (GUARD_FILTERED are gone from the pipeline)."""
    visible = [r for r in records if r.state != RecordState.GUARD_FILTERED]
    print(f"\n  {UNDERLINE}{label}{RESET}")
    if not visible:
        print(f"    {dim('(no visible records)')}")
        return
    for r in visible:
        state_str = r.state_display()
        marker = ""
        if r.state in SETTLED_BY_DESIGN:
            marker = dim(" (settled: by design)")
        elif r.state in SETTLED_RETRIABLE:
            marker = dim(" (settled: retriable)")
        elif r.state == RecordState.ACTIVE:
            marker = dim(" (processable)")
        print(f"    {r.label:25s} {state_str:>35s}{marker}")


def print_transition(record, old_state: RecordState, new_state: RecordState, reason):
    arrow = colored("→", new_state)
    old_display = colored(old_state.value, old_state)
    new_display = colored(new_state.value, new_state)
    print(f"    {record.label:25s} {old_display} {arrow} {new_display}")
    if reason:
        print(f"    {'':25s} {dim(reason)}")


def print_legend():
    print(f"\n{'─' * 80}")
    print(f"  {bold('STATE LEGEND')}")
    print(
        f"    {colored(RecordState.ACTIVE.value, RecordState.ACTIVE):>45s}  Processable — ready for this action"
    )
    print(
        f"    {colored(RecordState.PROCESSED.value, RecordState.PROCESSED):>45s}  Processable — output pending enrichment"
    )
    print(
        f"    {colored(RecordState.COMMITTED.value, RecordState.COMMITTED):>45s}  Settled (by design) — succeeded"
    )
    print(
        f"    {colored(RecordState.GUARD_SKIPPED.value, RecordState.GUARD_SKIPPED):>45s}  Settled (by design) — record is fine, skip"
    )
    print(
        f"    {colored(RecordState.GUARD_DEFERRED.value, RecordState.GUARD_DEFERRED):>45s}  Settled (retriable) — not ready yet"
    )
    print(
        f"    {colored(RecordState.GUARD_FILTERED.value, RecordState.GUARD_FILTERED):>45s}  Settled (by design) — dropped from pipeline"
    )
    print(
        f"    {colored(RecordState.EXHAUSTED.value, RecordState.EXHAUSTED):>45s}  Settled (retriable) — retries depleted"
    )
    print(
        f"    {colored(RecordState.CASCADE_SKIPPED.value, RecordState.CASCADE_SKIPPED):>45s}  Settled (retriable) — upstream blocked"
    )
    print(
        f"    {colored(RecordState.FAILED.value, RecordState.FAILED):>45s}  Settled (retriable) — processing error"
    )
    print(f"{'─' * 80}")


def print_state_machine_diagram():
    print(f"""
  {bold("RECORD STATE MACHINE")}

  {colored(RecordState.ACTIVE.value, RecordState.ACTIVE)} ──→ {colored(RecordState.PROCESSED.value, RecordState.PROCESSED)} ──→ {colored(RecordState.COMMITTED.value, RecordState.COMMITTED)}
    │              │
    │              └──→ {colored(RecordState.FAILED.value, RecordState.FAILED)} ──→ {colored(RecordState.EXHAUSTED.value, RecordState.EXHAUSTED)}
    │
    ├──→ {colored(RecordState.GUARD_SKIPPED.value, RecordState.GUARD_SKIPPED)}    (on_false: skip — record is fine)
    │
    ├──→ {colored(RecordState.GUARD_DEFERRED.value, RecordState.GUARD_DEFERRED)}   (on_false: defer — not ready yet)
    │
    ├──→ {colored(RecordState.GUARD_FILTERED.value, RecordState.GUARD_FILTERED)}   (on_false: filter — doesn't belong)
    │
    └──→ {colored(RecordState.CASCADE_SKIPPED.value, RecordState.CASCADE_SKIPPED)}  (upstream failed/exhausted)

  {dim("Settled by design:  committed, guard_skipped, guard_filtered")}
  {dim("Settled retriable:  failed, exhausted, cascade_skipped, guard_deferred")}
  {dim("Flows as ACTIVE:    RESETTABLE_DOWNSTREAM_STATES → active downstream")}
  {dim("Auto-cascades:      CASCADE_BLOCKING_STATES → cascade_skipped downstream")}
""")


def print_record_timeline(record):
    print(f"\n  {bold(record.label)} — Full lifecycle:")
    for h in record.history:
        to_state = h["to"]
        to_display = colored(to_state.value, to_state)
        ts = dim(h["timestamp"])
        action = dim(f"at {h['action']}")
        reason = ""
        if h["reason"]:
            reason = f"\n         {dim(h['reason'])}"
        if h["detail"]:
            reason += f"\n         {dim('detail: ' + h['detail'])}"
        print(f"    {ts}  {to_display:>35s} {action}{reason}")


# ─── Simulation Engine ───────────────────────────────────────────────────────


def action_step(
    records, action_name, action_kind, intent, guard=None, outcomes=None, phase="", versions=None
):
    """Simulate one action in the pipeline."""
    print_header(phase, action_name, action_kind, intent)

    # Step 1: Load input
    print(f"\n  {bold('Step 1: Load input')}")
    print(
        f"  {dim('Rule: RESETTABLE_DOWNSTREAM_STATES → active. CASCADE_BLOCKING_STATES → cascade_skipped.')}"
    )
    for r in records:
        if r.state in FLOWS_AS_ACTIVE:
            old = r.state
            r.transition(
                RecordState.ACTIVE,
                action_name,
                f"input from upstream ({old} → reset to ACTIVE)",
                detail=f"upstream state was {old}",
            )
            print_transition(
                r, old, RecordState.ACTIVE, f"upstream {old} → reset to ACTIVE for this action"
            )
        elif r.state in PROPAGATES_AS_CASCADE:
            old = r.state
            r.transition(
                RecordState.CASCADE_SKIPPED,
                action_name,
                f"upstream was {old} — auto-cascade",
                detail=f"blocked by {old} at upstream action",
            )
            print_transition(
                r, old, RecordState.CASCADE_SKIPPED, f"upstream was {old} — auto-cascade"
            )
        elif r.state == RecordState.GUARD_FILTERED:
            # Filtered records are invisible — don't even print them
            pass
        elif r.state == RecordState.ACTIVE:
            print(
                f"    {r.label:25s} {colored(RecordState.ACTIVE.value, RecordState.ACTIVE)} {dim('(already active)')}"
            )

    print_records(records, "After loading")
    wait("guard evaluation next")

    # Step 2: Guard filter
    processable = [r for r in records if r.is_processable()]
    if guard:
        print(f"\n  {bold('Step 2: Guard evaluation')}")
        print(f"    clause:   {dim(guard['clause'])}")
        print(f"    on_false: {dim(guard['on_false'])}")
        print()

        passing = []
        for r in processable:
            result = guard["eval"](r)
            if result:
                passing.append(r)
                print(
                    f"    {r.label:25s} clause = {colored('true', RecordState.COMMITTED)} → processable"
                )
            else:
                on_false = guard["on_false"]
                state_map = {
                    "skip": (
                        RecordState.GUARD_SKIPPED,
                        "record is fine — doesn't need this action",
                    ),
                    "defer": (RecordState.GUARD_DEFERRED, "not ready yet — come back on rerun"),
                    "filter": (
                        RecordState.GUARD_FILTERED,
                        "doesn't belong — dropped from pipeline",
                    ),
                }
                new_state, msg = state_map[on_false]
                old = r.state
                r.transition(
                    new_state,
                    action_name,
                    f"guard: {guard['clause']}",
                    detail=f"on_false={on_false}",
                )
                print_transition(r, old, new_state, msg)
        processable = passing
    else:
        print(f"\n  {bold('Step 2: Guard evaluation')}")
        print(f"    {dim('No guard — all processable records pass')}")

    print_records(records, "After guard")

    if not processable:
        print(f"\n  {dim('No processable records — skipping invocation')}")
        # Still derive dispositions for settled records
        _print_dispositions(records)
        wait()
        return

    wait("invocation next")

    # Step 3: Invoke
    print(f"\n  {bold(f'Step 3: Invoke ({action_kind})')}")
    if versions:
        print(f"    {dim(f'Running {len(versions)} parallel versions: {versions}')}")
    print()

    for r in processable:
        outcome = (outcomes or {}).get(r.id, "success")
        old = r.state

        if outcome == "success":
            r.transition(RecordState.PROCESSED, action_name, f"{action_kind} returned valid output")
            print_transition(r, old, RecordState.PROCESSED, f"{action_kind} → valid output")
            r.transition(
                RecordState.COMMITTED,
                action_name,
                "enriched + written to target",
                detail="lineage, metadata, passthrough applied",
            )
            print_transition(
                r, RecordState.PROCESSED, RecordState.COMMITTED, "enriched → committed to target"
            )
        elif outcome.startswith("failed"):
            # Support specific failure reasons: "failed:rate_limit", "failed:bad_record", etc.
            fail_reasons = {
                "failed": ("API error: 500 Internal Server Error", "transient server error"),
                "failed:rate_limit": (
                    "Rate limit exceeded: 429 Too Many Requests",
                    "retry after cooldown",
                ),
                "failed:bad_record": (
                    "Schema validation: missing required field 'question'",
                    "bad input data — fix source",
                ),
                "failed:timeout": ("Request timeout after 30s", "transient — retry may succeed"),
                "failed:parse": (
                    "JSON parse error: unexpected token at position 42",
                    "LLM returned malformed output",
                ),
                "failed:auth": (
                    "Authentication failed: 401 Unauthorized",
                    "check API key configuration",
                ),
            }
            reason, detail = fail_reasons.get(outcome, fail_reasons["failed"])
            r.transition(RecordState.FAILED, action_name, reason, detail=detail)
            print_transition(r, old, RecordState.FAILED, f"{reason} — {detail}")
        elif outcome == "exhausted":
            # Show the retry progression
            r.transition(RecordState.PROCESSED, action_name, "attempt 1/3: invalid JSON")
            print_transition(
                r, old, RecordState.PROCESSED, "attempt 1/3 → invalid JSON, retrying..."
            )
            r.transition(RecordState.ACTIVE, action_name, "retry 2/3")
            print_transition(
                r,
                RecordState.PROCESSED,
                RecordState.ACTIVE,
                "attempt 2/3 → invalid JSON, retrying...",
            )
            r.transition(RecordState.PROCESSED, action_name, "attempt 3/3: still invalid JSON")
            print_transition(
                r, RecordState.ACTIVE, RecordState.PROCESSED, "attempt 3/3 → invalid JSON"
            )
            r.transition(
                RecordState.EXHAUSTED,
                action_name,
                "3/3 retries exhausted",
                detail="retriable with different model or prompt",
            )
            print_transition(
                r,
                RecordState.PROCESSED,
                RecordState.EXHAUSTED,
                "all retries depleted — retriable with different model",
            )

    print_records(records, "After invocation")

    # Step 4: Derive dispositions
    _print_dispositions(records)
    wait()


def _print_dispositions(records):
    """Derive and display dispositions from current states."""
    print(f"\n  {bold('Step 4: Derive dispositions')} {dim('(state → disposition, ONE mapping)')}")
    for r in records:
        if r.state == RecordState.GUARD_FILTERED:
            continue
        disp = DISPOSITION_MAP.get(r.state, "?")
        print(f"    {r.label:25s} {r.state_display()} → {bold(disp)}")


# ═══ Expected outcome of the quiz demo (documents cascade-after-exhausted caveat) ═══

EXPECTED_DEMO_FINAL: dict[str, RecordState] = {
    "q1": RecordState.COMMITTED,
    "q2": RecordState.COMMITTED,
    "q3": RecordState.GUARD_FILTERED,
    "q4": RecordState.CASCADE_SKIPPED,
    "q5": RecordState.CASCADE_SKIPPED,
}


def create_demo_records() -> list[Record]:
    return [
        Record("q1", "Q1: container orch", "docs.k8s.io/overview"),
        Record("q2", "Q2: k8s networking", "docs.k8s.io/networking"),
        Record("q3", "Q3: define a pod", "docs.k8s.io/pods-basic"),
        Record("q4", "Q4: service mesh", "docs.k8s.io/mesh"),
        Record("q5", "Q5: CRD practices", "docs.k8s.io/crds"),
    ]


def run_quiz_pipeline(records: list[Record]) -> None:
    """Run the narrative pipeline through format_quiz_text (mutates *records* in place)."""

    action_step(
        records,
        "summarize_page_content",
        "llm",
        "Summarize documentation page for downstream grounding",
        phase="PHASE 1: EXTRACTION",
        outcomes={
            "q1": "success",
            "q2": "success",
            "q3": "success",
            "q4": "success",
            "q5": "success",
        },
    )
    records[0].data["exam_density"] = "high"
    records[1].data["exam_density"] = "high"
    records[2].data["exam_density"] = "low"  # Q3 — low density
    records[3].data["exam_density"] = "medium"
    records[4].data["exam_density"] = "high"

    clear()

    action_step(
        records,
        "extract_raw_qa",
        "llm",
        "Extract Q&A from documentation (3 parallel versions)",
        phase="PHASE 1: EXTRACTION",
        guard={
            "clause": 'summarize.exam_density in ("high", "medium")',
            "on_false": "filter",
            "eval": lambda r: r.data.get("exam_density") in ("high", "medium"),
        },
        versions=[1, 2, 3],
        outcomes={"q1": "success", "q2": "success", "q4": "success", "q5": "success"},
    )

    clear()

    action_step(
        records,
        "canonicalize_qa",
        "llm",
        "Deduplicate Q&A across 3 extraction versions",
        phase="PHASE 1: EXTRACTION",
        outcomes={"q1": "success", "q2": "success", "q4": "success", "q5": "success"},
    )

    clear()

    records[0].data["review_pass"] = True
    records[1].data["review_pass"] = False
    records[3].data["review_pass"] = True
    records[4].data["review_pass"] = True

    action_step(
        records,
        "review_question_quality",
        "llm",
        "Verify question is answerable from source",
        phase="PHASE 3: QUESTION AUTHORING",
        outcomes={"q1": "success", "q2": "success", "q4": "success", "q5": "success"},
    )

    clear()

    action_step(
        records,
        "rewrite_failed_question",
        "llm",
        "Rewrite question fixing issues from review",
        phase="PHASE 3: QUESTION AUTHORING",
        guard={
            "clause": "review_question_quality.pass == false",
            "on_false": "skip",
            "eval": lambda r: r.data.get("review_pass") is False,
        },
        outcomes={"q2": "success"},
    )

    clear()

    action_step(
        records,
        "validate_final_question",
        "llm",
        "3 independent reviewers verify question quality",
        phase="PHASE 3: QUESTION AUTHORING",
        versions=[1, 2, 3],
        outcomes={
            "q1": "success",
            "q2": "success",
            "q4": "success",
            "q5": "exhausted",
        },
    )

    clear()

    # Q5 hits EXHAUSTED here; downstream load steps cascade before later guards run.
    records[0].data["ext_data_ready"] = True
    records[1].data["ext_data_ready"] = True
    records[3].data["ext_data_ready"] = True
    records[4].data["ext_data_ready"] = True

    action_step(
        records,
        "enrich_external_metadata",
        "tool",
        "Enrich with external API data (CRD registry lookup)",
        phase="PHASE 3.5: ENRICHMENT",
        guard={
            "clause": "external_data.status == 'ready'",
            "on_false": "defer",
            "eval": lambda r: r.data.get("ext_data_ready", False),
        },
        outcomes={"q1": "success", "q2": "success", "q4": "success"},
    )

    clear()

    action_step(
        records,
        "generate_distractor_1",
        "llm",
        "Explain why distractor 1 is incorrect",
        phase="PHASE 4: DISTRACTOR EXPLANATIONS",
        outcomes={
            "q1": "success",
            "q2": "success",
            "q4": "failed:rate_limit",
        },
    )

    clear()

    action_step(
        records,
        "reconstruct_options",
        "tool",
        "Merge distractors into final options",
        phase="PHASE 4: DISTRACTOR EXPLANATIONS",
        outcomes={"q1": "success", "q2": "success"},
    )

    clear()

    action_step(
        records,
        "format_quiz_text",
        "tool",
        "Format final quiz output with HTML",
        phase="PHASE 5: FORMATTING",
        outcomes={"q1": "success", "q2": "success"},
    )

    clear()


def assert_demo_invariants(records: list[Record]) -> None:
    """Hard asserts for CI: demo narrative + framework mapping stayed aligned."""

    for r in records:
        expected = EXPECTED_DEMO_FINAL[r.id]
        assert r.state == expected, f"{r.id}: expected {expected.value}, got {r.state.value}"

    q5 = next(r for r in records if r.id == "q5")
    assert any(h["to"] == RecordState.EXHAUSTED for h in q5.history), (
        "Q5 should hit exhausted before cascading (retry-depleted path)"
    )

    q4 = next(r for r in records if r.id == "q4")
    assert any(h["to"] == RecordState.FAILED for h in q4.history), "Q4 should record failed before cascade"


def validate_guard_defer_path() -> None:
    """Isolated path: committed → active → guard defers (same reset/defer semantics as prod)."""

    r = Record("defer", "Synthetic: defer guard", "n/a")
    r.state = RecordState.COMMITTED
    r.data["ready"] = False
    action_step(
        [r],
        "synthetic_enrich",
        "tool",
        "",
        phase="VALIDATION: GUARD_DEFERRED",
        guard={
            "clause": "ready",
            "on_false": "defer",
            "eval": lambda rec: rec.data.get("ready", False),
        },
        outcomes={},
    )
    assert r.state == RecordState.GUARD_DEFERRED, r.state


def run_validated_simulation() -> None:
    """Non-interactive checks: alignment with agent_actions + full demo assertions."""

    global _interactive
    _interactive = False
    with contextlib.redirect_stdout(io.StringIO()):
        validate_framework_alignment()
        records = create_demo_records()
        run_quiz_pipeline(records)
        assert_demo_invariants(records)
        validate_guard_defer_path()


# ─── Main Simulation ─────────────────────────────────────────────────────────


def main() -> None:
    global _interactive

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run framework alignment + demo assertions (no prompts); exit non-zero on failure",
    )
    args = parser.parse_args()

    if args.validate:
        _interactive = False
        run_validated_simulation()
        print("simulate_record_state_machine: validation OK", file=sys.stderr)
        return

    _interactive = True
    clear()

    print(f"""
{bold("╔══════════════════════════════════════════════════════════════════════════════╗")}
{bold("║           RECORD STATE MACHINE — Interactive Pipeline Simulation           ║")}
{bold("║                     qanalabs_quiz_gen workflow                              ║")}
{bold("╚══════════════════════════════════════════════════════════════════════════════╝")}

  This simulation walks through {bold("5 records")} flowing through the quiz generation
  pipeline, demonstrating {bold("every state")} in the Record State Machine
  (same string values as {dim("agent_actions.record.state.RecordState")}):

    {colored(RecordState.ACTIVE.value, RecordState.ACTIVE)}           Every record starts here
    {colored(RecordState.PROCESSED.value, RecordState.PROCESSED)}        LLM/tool returned output (transient)
    {colored(RecordState.COMMITTED.value, RecordState.COMMITTED)}        Written to target — success
    {colored(RecordState.GUARD_SKIPPED.value, RecordState.GUARD_SKIPPED)}    on_false: skip — record is fine
    {colored(RecordState.GUARD_DEFERRED.value, RecordState.GUARD_DEFERRED)}   on_false: defer — not ready yet
    {colored(RecordState.GUARD_FILTERED.value, RecordState.GUARD_FILTERED)}   on_false: filter — doesn't belong
    {colored(RecordState.EXHAUSTED.value, RecordState.EXHAUSTED)}        All retries depleted
    {colored(RecordState.CASCADE_SKIPPED.value, RecordState.CASCADE_SKIPPED)}  Upstream failed/exhausted — blocked
    {colored(RecordState.FAILED.value, RecordState.FAILED)}           API/processing error

  {bold("The 5 records:")}
    Q1: "Container orchestration"    — smooth path, all the way to committed
    Q2: "Kubernetes networking"      — fails review, gets rewritten, passes
    Q3: "Define a pod"               — low density page → guard_filtered (dropped)
    Q4: "Service mesh patterns"      — rate limit at distractor → cascade downstream
    Q5: "CRD best practices"         — exhausted at validate, then {dim("cascade_skipped")}
         (cascade runs at downstream load before any defer guard can apply)
""")

    print_state_machine_diagram()
    print_legend()
    wait("start the pipeline")
    clear()

    records = create_demo_records()
    run_quiz_pipeline(records)

    # ══════════════════════════════════════════════════════════════════════════
    # FINAL SUMMARY
    # ══════════════════════════════════════════════════════════════════════════
    print(f"""
{bold("╔══════════════════════════════════════════════════════════════════════════════╗")}
{bold("║                         PIPELINE COMPLETE                                  ║")}
{bold("╚══════════════════════════════════════════════════════════════════════════════╝")}
""")

    print(f"  {bold('Final record states:')}\n")
    outcome_labels = {
        RecordState.COMMITTED: "Quiz question produced",
        RecordState.GUARD_FILTERED: "Dropped — low density page",
        RecordState.CASCADE_SKIPPED: "Blocked — upstream failed, exhausted, or cascaded",
        RecordState.FAILED: "API error — retriable on rerun",
        RecordState.EXHAUSTED: "Retries depleted — retriable with different model",
        RecordState.GUARD_DEFERRED: "External data not ready — retriable on rerun",
    }
    for r in records:
        outcome = outcome_labels.get(r.state, "")
        print(f"    {r.label:25s} {r.state_display():>35s}  {dim(outcome)}")

    # Rerun candidates
    print(f"\n  {bold('Rerun candidates')} {dim('(settled: retriable)')}\n")
    retriable = [r for r in records if r.state in SETTLED_RETRIABLE]
    if retriable:
        for r in retriable:
            rerun_hint = {
                RecordState.FAILED: "rerun this action",
                RecordState.EXHAUSTED: "rerun with different model/prompt",
                RecordState.CASCADE_SKIPPED: "fix upstream, then rerun",
                RecordState.GUARD_DEFERRED: "wait for external data, then rerun",
            }
            hint = dim(rerun_hint.get(r.state, ""))
            print(f"    {r.label:25s} {r.state_display():>35s}  {hint}")
        print(f"\n    {dim('agac rerun --retriable  → reprocess these records')}")

    # By design
    print(f"\n  {bold('Settled by design')} {dim('(no action needed)')}\n")
    by_design = [r for r in records if r.state in SETTLED_BY_DESIGN]
    for r in by_design:
        print(f"    {r.label:25s} {r.state_display()}")

    wait("show full audit trails")
    clear()

    # ══════════════════════════════════════════════════════════════════════════
    # AUDIT TRAILS
    # ══════════════════════════════════════════════════════════════════════════
    print(f"""
{bold("╔══════════════════════════════════════════════════════════════════════════════╗")}
{bold("║                       RECORD LIFECYCLES (Audit Trail)                      ║")}
{bold("╚══════════════════════════════════════════════════════════════════════════════╝")}

  {dim("Every state transition is recorded with timestamp, action, reason, and detail.")}
  {dim("This is the audit trail that makes guard behavior fully debuggable.")}
""")

    for r in records:
        print_record_timeline(r)
        print()

    print(f"""
{"─" * 80}
  {bold("WHAT THE STATE MACHINE ELIMINATES")}

  {bold('Before (legacy, removed):')}
    • _unprocessed tombstone boolean + ad-hoc metadata.reason strings
    • Overlapping skip/passthrough disposition naming in scattered call sites
    • Upstream cascade detection separate from typed record state

  {bold('Now (cutover):')}
    • ONE lifecycle field: record._state (RecordState enum); missing or invalid errors on read
    • TaskPreparer._is_upstream_unprocessed() uses CASCADE_BLOCKING_STATES + from_record
    • Transitions are append-only via RecordEnvelope.transition with typed reasons

  {bold("States demonstrated in this simulation:")}
    {colored(RecordState.ACTIVE.value, RecordState.ACTIVE):>40s}  ✓  Every record, every action
    {colored(RecordState.PROCESSED.value, RecordState.PROCESSED):>40s}  ✓  Transient during invocation
    {colored(RecordState.COMMITTED.value, RecordState.COMMITTED):>40s}  ✓  Q1, Q2 through the pipeline
    {colored(RecordState.GUARD_SKIPPED.value, RecordState.GUARD_SKIPPED):>40s}  ✓  Q1/Q4/Q5 at rewrite_failed (passed review)
    {colored(RecordState.GUARD_DEFERRED.value, RecordState.GUARD_DEFERRED):>40s}  ✓  Synthetic validate_guard_defer_path() (with --validate)
    {colored(RecordState.GUARD_FILTERED.value, RecordState.GUARD_FILTERED):>40s}  ✓  Q3 at extract_raw_qa (low density page)
    {colored(RecordState.EXHAUSTED.value, RecordState.EXHAUSTED):>40s}  ✓  Q5 at validate_final_question (then cascades)
    {colored(RecordState.CASCADE_SKIPPED.value, RecordState.CASCADE_SKIPPED):>40s}  ✓  Q4/Q5 downstream after fail/exhausted
    {colored(RecordState.FAILED.value, RecordState.FAILED):>40s}  ✓  Q4 at generate_distractor_1 (rate limit)
{"─" * 80}
""")


if __name__ == "__main__":
    main()
