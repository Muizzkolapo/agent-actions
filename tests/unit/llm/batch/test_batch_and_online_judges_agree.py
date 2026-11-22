"""The same judge replies give the same verdict in batch as online (1814).

Each case is one value judged with N votes, each vote answered with a recorded
reply. Online reads the replies through `invoke_judge`; batch sends the votes as
a judge batch, the provider reads the replies from its result file, and the
result writer ships the verdict. Online votes run concurrently, so which vote
gets which reply varies; the verdict, the tally and the dissents must not.
"""

import re
import threading
from unittest.mock import patch

import pytest

from agent_actions.expectations.service import create_expectation_service_from_config

from .judge_batch_world import (
    ERRORED,
    INVOKE,
    JudgingProvider,
    Run,
    answers,
    judge_rule,
    judged_config,
    verdict,
)

QUOTES_THE_EXAMPLE = 'No. The example {"passed": true, "reason": "x"} does not apply here.'
CASES = {
    "a majority passes": [verdict(True, "ok"), verdict(False, "off"), verdict(True, "ok")],
    "a tie fails closed": [verdict(True, "ok"), verdict(False, "off")],
    "a fenced verdict is read": ['```json\n{"passed": true, "reason": "fenced"}\n```'],
    "prose is not a verdict": ["I think every option is on topic."],
    "quoting the example is not a verdict": [QUOTES_THE_EXAMPLE],
    "a verdict without a boolean fails": ['{"passed": "yes", "reason": "sure"}'],
    "an errored request fails the call": [ERRORED],
    "one errored vote fails the call": [verdict(True, "ok"), ERRORED, verdict(True, "ok")],
}


def _comparable(passed: bool, detail: str):
    match = re.fullmatch(r"(\d+/\d+ judge votes passed)(?:: (.*))?", detail, re.S)
    if match is None:
        return passed, detail
    return passed, match.group(1), sorted((match.group(2) or "").split("; "))


def _config(votes: int):
    return judged_config([judge_rule(votes=votes)], repair="none")


def _online(replies):
    queue, lock = list(replies), threading.Lock()

    def reply(**_kwargs):
        with lock:
            text = queue.pop(0)
        if text is ERRORED:
            raise RuntimeError("rate limited")
        return [{"raw_response": text}]

    config = _config(len(replies))
    service = create_expectation_service_from_config(
        config["expect"], action_name="author", agent_config=config
    )
    with patch(INVOKE, side_effect=reply):
        (outcome,) = service.validate({"options": ["a", "b"]}).outcomes
    return _comparable(outcome.passed, outcome.detail)


def _batch(replies):
    run = Run(_config(len(replies)), JudgingProvider(lambda _prompt, vote: replies[vote]))
    run.main_batch_returns(answers({"r1": ["a", "b"]}))
    run.recovery_batch_returns()
    assert run.online == [], "the batch path called the judge online"
    (outcome,) = run.verdicts()["r1"]["outcomes"]
    return _comparable(outcome["passed"], outcome["detail"])


@pytest.mark.parametrize("replies", CASES.values(), ids=CASES.keys())
def test_batch_reads_the_replies_as_online_does(replies):
    assert _batch(replies) == _online(replies)


def test_the_tie_and_the_quoted_example_both_fail():
    """Pinned outright, so agreeing on a wrong answer cannot pass the parity test."""
    assert _batch(CASES["a tie fails closed"])[0] is False
    assert _batch(CASES["quoting the example is not a verdict"])[0] is False
    assert _batch(CASES["a majority passes"])[0] is True
