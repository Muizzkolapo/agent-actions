"""FILE granularity needs an upstream action to read a file of, and preflight says so.

Checked in the static analyzer, not the action-entry validators: the entry those see is
rebuilt by `prompt/renderer.py`, which hardcodes `dependencies: []`, so every action
looks first-stage there (#1076).
"""

import pytest

from agent_actions.validation.static_analyzer import analyze_workflow

MARKER = "FILE granularity"

SCOPE = {"observe": ["source.text"]}


def _refusals(actions, defaults=None):
    config = {"name": "wf", "actions": actions}
    if defaults:
        config["defaults"] = defaults
    return [e for e in analyze_workflow(config).errors if MARKER in e.message]


def _one(refusals):
    assert len(refusals) == 1, f"expected one refusal, got {[r.message for r in refusals]}"
    return refusals[0]


@pytest.mark.parametrize(
    ("kind", "granularity"),
    [("tool", "File"), ("hitl", None)],
    ids=["tool-declares-file", "hitl-defaults-to-file"],
)
def test_a_first_stage_file_action_is_refused(kind, granularity):
    """Both kinds that reach FILE mode reach the same pipeline, which has no dispatch
    for either, so the refusal cannot be tool-only. HITL resolves to file without
    saying so, which is why granularity is left unset for it here."""
    action = {"name": "roll_up", "kind": kind, "context_scope": SCOPE}
    if granularity:
        action["granularity"] = granularity

    error = _one(_refusals([action]))

    assert "roll_up" in error.message, f"a workflow of thirty needs the action named: {error}"
    assert "dependencies" in error.message.lower(), (
        f"the refusal has to say an upstream action is what is missing, or it reads as "
        f"'FILE is unsupported' and the author deletes the granularity: {error.message}"
    )


def test_the_refusal_says_what_to_do_instead():
    """The shape is reachable — every FILE tool in the sample project puts a RECORD
    action in front — so the refusal should point there rather than only decline."""
    action = {
        "name": "roll_up",
        "kind": "tool",
        "granularity": "File",
        "context_scope": SCOPE,
    }

    error = _one(_refusals([action]))

    assert "RECORD" in (error.hint or "") or "RECORD" in error.message


@pytest.mark.parametrize("dependencies", [["first"], ["first", "second"]])
def test_a_file_action_with_an_upstream_is_accepted(dependencies):
    """Control: the shape the framework does run."""
    actions = [
        {"name": "first", "kind": "tool", "context_scope": SCOPE},
        {"name": "second", "kind": "tool", "context_scope": SCOPE},
        {
            "name": "roll_up",
            "kind": "tool",
            "granularity": "File",
            "dependencies": dependencies,
            "context_scope": {"observe": ["first.text"]},
        },
    ]

    assert _refusals(actions) == []


def test_a_first_stage_record_tool_is_accepted():
    """Control: a first-stage tool is fine at RECORD granularity — `ql_code_centered`
    opens with one. The refusal is about the granularity, not about being first."""
    assert _refusals([{"name": "prescreen", "kind": "tool", "context_scope": SCOPE}]) == []


def test_a_first_stage_llm_action_at_file_granularity_is_not_this_refusal():
    """Control: an LLM action never reaches a FILE strategy at any stage, so this rule
    has nothing to say about it.

    Not because another guard catches it: the kind-based rule in the action-entry
    validators does not run in the real preflight path either, so such a config passes
    `agac inspect` today and the granularity is silently ignored. That is stage-independent
    and out of scope here — the point is only that this check must not claim it.
    """
    assert _refusals([{"name": "summarize", "granularity": "File", "context_scope": SCOPE}]) == []


def test_an_empty_dependencies_list_is_still_first_stage():
    """`dependencies: []` names no upstream, so it is the shape of omitting the key —
    and a truthiness check is the easy thing to get wrong here."""
    action = {
        "name": "roll_up",
        "kind": "tool",
        "granularity": "File",
        "dependencies": [],
        "context_scope": SCOPE,
    }

    error = _one(_refusals([action]))

    assert "roll_up" in error.message


def test_file_granularity_inherited_from_defaults_is_refused_too():
    """The granularity need not be written on the action: the analyzer resolves it
    through the workflow defaults the way the expander does, and a first action
    inherits it."""
    error = _one(
        _refusals(
            [{"name": "roll_up", "kind": "tool", "context_scope": SCOPE}],
            defaults={"granularity": "File"},
        )
    )

    assert "roll_up" in error.message
