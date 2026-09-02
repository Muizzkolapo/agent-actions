"""ExpectConfig shape rules and defaults."""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ActionConfig, ExpectConfig

INLINE = [{"type": "item_count", "field": "ideas", "min": 5}]


def test_defaults_make_a_bare_block_retry():
    cfg = ExpectConfig(expectations=INLINE)
    assert cfg.repair == "auto"
    assert cfg.max_iterations == 3
    assert cfg.on_exhausted == "return_last"


def test_named_suite_is_accepted():
    assert ExpectConfig(suite="scenario_question").suite == "scenario_question"


def test_both_suite_and_inline_expectations_is_rejected():
    with pytest.raises(ValidationError, match="at most one"):
        ExpectConfig(suite="s", expectations=INLINE)


def test_a_bare_expect_block_reads_the_actions_own_schema():
    cfg = ExpectConfig(repair="none")
    assert cfg.suite is None
    assert cfg.expectations is None


@pytest.mark.parametrize("mode", ["none", "retry", "auto"])
def test_named_repair_modes_are_accepted(mode):
    assert ExpectConfig(expectations=INLINE, repair=mode).repair == mode


def test_repair_prompt_mapping_is_accepted():
    cfg = ExpectConfig(expectations=INLINE, repair={"prompt": "$wf.Fix"})
    assert cfg.repair == {"prompt": "$wf.Fix"}


def test_unknown_repair_mode_is_rejected():
    with pytest.raises(ValidationError, match="none, retry, auto"):
        ExpectConfig(expectations=INLINE, repair="regenerate")


def test_repair_mapping_with_unexpected_keys_is_rejected():
    with pytest.raises(ValidationError, match="prompt"):
        ExpectConfig(expectations=INLINE, repair={"prompt": "$wf.Fix", "extra": 1})


def test_observe_mode_rejects_max_iterations():
    with pytest.raises(ValidationError, match="max_iterations"):
        ExpectConfig(expectations=INLINE, repair="none", max_iterations=3)


def test_observe_mode_rejects_on_exhausted():
    with pytest.raises(ValidationError, match="on_exhausted"):
        ExpectConfig(expectations=INLINE, repair="none", on_exhausted="fail")


def test_observe_mode_without_loop_keys_is_valid():
    assert ExpectConfig(expectations=INLINE, repair="none").repair == "none"


def test_unknown_key_is_rejected():
    with pytest.raises(ValidationError):
        ExpectConfig(expectations=INLINE, max_iteration=3)


def test_max_iterations_is_bounded():
    with pytest.raises(ValidationError):
        ExpectConfig(expectations=INLINE, max_iterations=0)
    with pytest.raises(ValidationError):
        ExpectConfig(expectations=INLINE, max_iterations=11)


def test_action_config_accepts_an_expect_block():
    action = ActionConfig(
        name="brainstorm",
        intent="Generate ideas",
        expect={"expectations": INLINE, "repair": "none"},
    )
    assert action.expect is not None
    assert action.expect.repair == "none"


def test_action_config_without_expect_defaults_to_none():
    assert ActionConfig(name="a", intent="i").expect is None
