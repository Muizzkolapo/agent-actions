"""Composing the auto-repair regeneration prompt."""

from agent_actions.expectations.repair import compose_repair_prompt
from agent_actions.expectations.types import Outcome, SuiteResult


def _outcome(oid, passed, severity="fail", detail=""):
    return Outcome(
        id=oid,
        type="item_count",
        severity=severity,
        passed=passed,
        detail=detail,
        definition_hash="abc123",
    )


def test_composed_prompt_names_failures_with_reasons_and_hints():
    result = SuiteResult(
        suite_name="s",
        outcomes=[
            _outcome("option_count", False, detail="expected exactly 4 items, found 2"),
            _outcome("stem_present", True),
        ],
    )
    prompt = compose_repair_prompt(
        "ORIGINAL",
        {"options": ["a", "b"]},
        result,
        hints={"option_count": "add plausible distractors"},
    )
    assert "ORIGINAL" in prompt
    assert '"options"' in prompt
    assert "option_count" in prompt
    assert "expected exactly 4 items, found 2" in prompt
    assert "add plausible distractors" in prompt
    assert "stem_present" in prompt


def test_composed_prompt_omits_missing_hints_without_placeholders():
    result = SuiteResult(
        suite_name="s", outcomes=[_outcome("option_count", False, detail="found 2")]
    )
    prompt = compose_repair_prompt("P", {"options": []}, result, hints={})
    assert "hint" not in prompt.lower()


def test_warn_failures_appear_in_the_prompt_with_their_severity_labeled():
    result = SuiteResult(
        suite_name="s",
        outcomes=[
            _outcome("hard", False, detail="hard failed"),
            _outcome("soft", False, severity="warn", detail="soft failed"),
        ],
    )
    prompt = compose_repair_prompt("P", {}, result, hints={})
    assert "hard failed" in prompt
    assert "soft failed" in prompt
    assert "[warn]" in prompt


def test_empty_passing_list_renders_no_empty_header_content():
    result = SuiteResult(suite_name="s", outcomes=[_outcome("only", False, detail="d")])
    prompt = compose_repair_prompt("P", {}, result, hints={})
    assert "(none yet)" in prompt
