"""Checks that depend on an action's type read its kind, never its name."""

import pytest

from agent_actions.validation.orchestration.action_entry_validation_orchestrator import (
    ActionEntryValidationOrchestrator,
)
from agent_actions.validation.preflight.vendor_compatibility_validator import (
    VendorCompatibilityValidator,
)


def _entry(name: str, kind: str, **overrides) -> dict:
    # The shape the renderer builds for every action: agent_type holds the name.
    entry = {
        "agent_type": name,
        "name": name,
        "kind": kind,
        "model_vendor": "tool" if kind == "tool" else "openai",
        "model_name": "gpt-4o-mini",
        "is_operational": True,
        "dependencies": [],
        "granularity": "file" if kind == "hitl" else "record",
        "run_mode": "online",
        "json_mode": True,
    }
    entry.update(overrides)
    return entry


def _check(entry: dict) -> tuple[list[str], list[str]]:
    orchestrator = ActionEntryValidationOrchestrator()
    orchestrator.validate_action_entry(entry, "wf")
    return orchestrator.get_validation_errors(), orchestrator.get_validation_warnings()


@pytest.mark.parametrize("name", ["function", "tool", "llm", "summarize"])
@pytest.mark.parametrize("kind", ["llm", "tool", "hitl"])
def test_an_action_is_accepted_whatever_its_name(name, kind):
    errors, _ = _check(_entry(name, kind))

    assert errors == []


def test_an_action_without_a_model_name_is_still_refused():
    entry = _entry("summarize", "llm")
    del entry["model_name"]

    errors, _ = _check(entry)

    assert errors == ["agent entry summarize in 'wf' missing required key(s): model_name."]


def test_a_tool_with_no_vendor_is_not_asked_for_one():
    check = VendorCompatibilityValidator()

    check.validate_vendor_config({"agent_type": "fetch", "kind": "tool", "model_vendor": ""})

    assert check.get_errors() == []


def test_an_llm_action_with_no_vendor_is_asked_for_one():
    check = VendorCompatibilityValidator()

    check.validate_vendor_config({"agent_type": "tool", "kind": "llm", "model_vendor": ""})

    assert check.get_errors() == ["model_vendor is required for non-tool agents"]
