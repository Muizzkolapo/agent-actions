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


def test_a_bare_expect_block_is_legal():
    cfg = ExpectConfig(repair="none")
    assert cfg.suite is None
    assert cfg.expectations is None


@pytest.mark.parametrize("mode", ["none", "retry", "auto"])
def test_named_repair_modes_are_accepted(mode):
    assert ExpectConfig(expectations=INLINE, repair=mode).repair == mode


def test_repair_prompt_mapping_is_accepted():
    cfg = ExpectConfig(expectations=INLINE, repair={"prompt": "$wf.Fix"})
    assert cfg.repair == {"prompt": "$wf.Fix"}


def test_observe_mode_without_loop_keys_is_valid():
    assert ExpectConfig(expectations=INLINE, repair="none").repair == "none"


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


def test_judge_budget_defaults_to_none():
    config = ExpectConfig(repair="none", expectations=[{"type": "not_null", "field": "x"}])
    assert config.judge_budget is None


def test_judge_budget_accepts_a_positive_int():
    config = ExpectConfig(
        repair="none", expectations=[{"type": "not_null", "field": "x"}], judge_budget=20
    )
    assert config.judge_budget == 20


def test_judge_budget_is_allowed_under_repair_none():
    config = ExpectConfig(
        repair="none", expectations=[{"type": "not_null", "field": "x"}], judge_budget=5
    )
    assert config.judge_budget == 5


_NOT_NULL = [{"type": "not_null", "field": "x"}]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        pytest.param({"suite": "s", "expectations": INLINE}, "at most one", id="suite_and_inline"),
        pytest.param({"expectations": []}, "empty", id="empty_list"),
        pytest.param({"suite": ""}, "empty", id="empty_suite"),
        pytest.param(
            {"expectations": INLINE, "repair": "regenerate"},
            "none, retry, auto",
            id="unknown_repair",
        ),
        pytest.param(
            {"expectations": INLINE, "repair": {"prompt": "$wf.Fix", "extra": 1}},
            "prompt",
            id="repair_extra_key",
        ),
        pytest.param(
            {"expectations": INLINE, "repair": "none", "max_iterations": 3},
            "max_iterations",
            id="observe_max_iter",
        ),
        pytest.param(
            {"expectations": INLINE, "repair": "none", "on_exhausted": "fail"},
            "on_exhausted",
            id="observe_on_exhausted",
        ),
        pytest.param({"expectations": INLINE, "max_iteration": 3}, None, id="unknown_key"),
        pytest.param({"expectations": INLINE, "max_iterations": 0}, None, id="max_iter_0"),
        pytest.param({"expectations": INLINE, "max_iterations": 11}, None, id="max_iter_11"),
        pytest.param(
            {"repair": "none", "expectations": _NOT_NULL, "judge_budget": 0}, None, id="judge_0"
        ),
        pytest.param(
            {"repair": "none", "expectations": _NOT_NULL, "judge_budget": -5}, None, id="judge_neg"
        ),
    ],
)
def test_invalid_expect_block_is_rejected(kwargs, match):
    with pytest.raises(ValidationError, match=match):
        ExpectConfig(**kwargs)
