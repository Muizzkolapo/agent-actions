"""`expect.judge_mode` chooses how judge calls go out; online actions are untouched (1814).

Omitted, a batch action's judge calls go out as a batch and an online action's
online. `judge_mode: online` keeps a batch action's judge calls online, as before
judge batches existed; `judge_mode: batch` on an online action is a preflight defect.
"""

import pytest
from pydantic import ValidationError

from agent_actions.config.schema import ExpectConfig
from agent_actions.expectations.service import create_expectation_service_from_config
from agent_actions.validation.expectations_validator import find_expectation_defects

from .judge_batch_world import (
    INVOKE,
    JudgingProvider,
    Run,
    answers,
    judge_rule,
    judged_config,
    verdict,
)

JUDGED = [judge_rule(votes=2)]


def test_an_online_action_still_calls_the_judge_online():
    from unittest.mock import patch

    config = judged_config(JUDGED, repair="none")
    config["run_mode"] = "online"
    service = create_expectation_service_from_config(
        config["expect"], action_name="author", agent_config=config
    )
    with patch(INVOKE, return_value=[{"raw_response": verdict(True, "ok")}]) as invoke:
        result = service.execute(lambda _prompt: ({"options": ["a"]}, True), "Write the options.")
    assert invoke.call_count == 2, "each vote is one online judge call"
    assert result.suite_result.overall_pass is True


def test_judge_mode_online_keeps_a_batch_actions_judge_online():
    provider = JudgingProvider(lambda _prompt, _vote: verdict(True))
    run = Run(judged_config(JUDGED, repair="auto", judge_mode="online"), provider)

    assert run.main_batch_returns(answers({"r1": ["a"], "r2": ["b"]})) is True
    assert provider.batches == []
    assert len(run.online) == 2 * 2


@pytest.mark.parametrize("mode", ["batch", "online"])
def test_the_expect_block_takes_judge_mode(mode):
    assert ExpectConfig(expectations=JUDGED, judge_mode=mode).judge_mode == mode


def test_an_unknown_judge_mode_is_refused():
    with pytest.raises(ValidationError, match="judge_mode"):
        ExpectConfig(expectations=JUDGED, judge_mode="sometimes")


def _defects(run_mode):
    action = {
        "name": "a",
        "run_mode": run_mode,
        "expect": {"judge_mode": "batch", "expectations": JUDGED},
    }
    return find_expectation_defects({"a": action}, {"a": {"options"}})


def test_judge_mode_batch_on_an_online_action_is_a_defect():
    assert any("judge_mode: batch" in m for m in _defects("online")["a"])


def test_judge_mode_batch_on_a_batch_action_is_allowed():
    assert _defects("batch") == {}
