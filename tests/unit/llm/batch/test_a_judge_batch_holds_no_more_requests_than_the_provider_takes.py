"""A judge batch holds no more requests than the provider takes in one batch.

The values past the cap stay unjudged and go out in the next judge round, as the
calls of a second model do, until every value is judged.
"""

import pytest

from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient
from agent_actions.llm.providers.batch_base import BATCH_MAX_REQUESTS_ENV, batch_request_cap
from agent_actions.llm.providers.groq.batch_client import GroqBatchClient
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient

from .judge_batch_world import JudgingProvider, Run, answers, judge_rule, judged_config, verdict

VALUES = {f"r{i}": [f"v{i}"] for i in range(5)}


def _judge_all(cap: int, repair: str):
    provider = JudgingProvider(lambda _prompt, _vote: verdict(True, "fine"))
    provider.max_batch_requests = cap
    run = Run(judged_config([judge_rule(votes=2)], repair=repair), provider)
    assert run.main_batch_returns(answers(VALUES)) is False
    out = None
    for _pass in range(10):
        out = run.recovery_batch_returns()
        if out is not None:
            break
    return run, provider, out


@pytest.mark.parametrize("repair", ["auto", "none"])
def test_more_pending_judge_requests_than_the_cap_go_out_in_several_rounds(repair):
    run, provider, out = _judge_all(cap=4, repair=repair)

    assert out == "/out.json", "a value was left unjudged and the file never finished"
    assert provider.batches == [
        ("f.json_judge_1", 4),
        ("f.json_judge_2", 4),
        ("f.json_judge_3", 2),
    ]
    assert run.online == []
    verdicts = run.verdicts()
    assert set(verdicts) == set(VALUES)
    assert all(v["overall_pass"] for v in verdicts.values())


def test_a_value_whose_votes_pass_the_cap_still_goes_out_alone():
    _run, provider, out = _judge_all(cap=1, repair="none")

    assert out == "/out.json"
    assert [n for _name, n in provider.batches] == [2] * len(VALUES)


def test_each_provider_caps_its_batches_at_its_documented_limit():
    assert OpenAIBatchClient.max_batch_requests == 50_000
    assert GroqBatchClient.max_batch_requests == 50_000
    assert AnthropicBatchClient.max_batch_requests == 100_000


def test_the_environment_variable_replaces_the_cap(monkeypatch):
    provider = JudgingProvider(lambda _prompt, _vote: verdict(True))
    monkeypatch.setenv(BATCH_MAX_REQUESTS_ENV, "7")
    assert batch_request_cap(provider) == 7
    monkeypatch.setenv(BATCH_MAX_REQUESTS_ENV, "0")
    with pytest.raises(ValueError, match=BATCH_MAX_REQUESTS_ENV):
        batch_request_cap(provider)
    monkeypatch.setenv(BATCH_MAX_REQUESTS_ENV, " ")
    assert batch_request_cap(provider) == provider.max_batch_requests
