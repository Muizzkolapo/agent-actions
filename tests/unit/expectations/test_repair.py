"""Composing the auto-repair regeneration prompt."""

from agent_actions.expectations.repair import compose_repair_prompt
from agent_actions.expectations.types import Outcome, SuiteResult


def _outcome(oid, passed, severity="error", detail="", skipped=False):
    return Outcome(
        id=oid,
        type="item_count",
        severity=severity,
        passed=passed,
        detail=detail,
        definition_hash="abc123",
        skipped=skipped,
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


def test_skipped_outcomes_are_not_presented_as_failures_to_fix():
    result = SuiteResult(
        suite_name="s",
        outcomes=[
            _outcome("judged", False, detail="judge budget exhausted", skipped=True),
            _outcome("kept", True),
        ],
    )
    prompt = compose_repair_prompt("P", {}, result, hints={"judged": "be concise"})
    assert "judged" not in prompt
    assert "judge budget exhausted" not in prompt
    assert "(none)" in prompt


def test_multiline_detail_and_hint_render_on_one_bullet_line():
    result = SuiteResult(
        suite_name="s",
        outcomes=[_outcome("raiser", False, detail="check raised ValueError:\nline two")],
    )
    prompt = compose_repair_prompt("P", {}, result, hints={"raiser": "keep it\nshort"})
    line = next(li for li in prompt.splitlines() if li.startswith("- raiser"))
    assert "check raised ValueError: line two" in line
    assert "keep it short" in line


def test_a_waived_rule_is_not_offered_as_something_the_output_already_satisfies():
    result = SuiteResult(
        suite_name="s",
        outcomes=[
            _outcome("genuinely_passing", True),
            _outcome("waived", True, skipped=True),
            _outcome("broken", False, detail="2 words, expected at least 6"),
        ],
    )
    prompt = compose_repair_prompt("P", {"summary": "x"}, result, hints={})
    assert "genuinely_passing" in prompt
    assert "waived" not in prompt


def test_a_partly_skipped_outcome_still_reaches_the_repair_prompt():
    # Only a wholly-unevaluated rule is unactionable; a rule where some element
    # genuinely failed must keep its detail in the feedback.
    result = SuiteResult(
        suite_name="s",
        outcomes=[_outcome("on_topic", False, detail="off topic; budget exhausted")],
    )
    prompt = compose_repair_prompt("P", {"ideas": ["bad"]}, result, hints={})
    assert "off topic" in prompt
    assert "(none)" not in prompt


def test_a_hint_still_reaches_a_record_indexed_outcome():
    # A multi-record response tags outcomes with their record index; the hint
    # is authored against the rule, not the record.
    result = SuiteResult(
        suite_name="s", outcomes=[_outcome("option_count[1]", False, detail="found 2")]
    )
    prompt = compose_repair_prompt("P", {}, result, hints={"option_count": "add distractors"})
    assert "add distractors" in prompt
