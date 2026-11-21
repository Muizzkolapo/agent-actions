"""A judge vote the model refused fails the whole judge call, in batch as online.

Online, the refused vote raises and the rule fails with `judge call failed: <refusal>`.
The judge batch read the refused vote, a success with no content, as one empty vote,
so two passing votes out of three passed the rule.
"""

import json

from agent_actions.llm.batch.services.judge_ops import JudgeRequester
from agent_actions.llm.batch.services.side_batch import read_side_batch
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient


def _line(custom_id, message, finish_reason="stop"):
    return {
        "custom_id": custom_id,
        "response": {
            "status_code": 200,
            "body": {"choices": [{"message": message, "finish_reason": finish_reason}]},
        },
    }


def _passing(custom_id):
    text = json.dumps({"passed": True, "reason": "on topic"})
    return _line(custom_id, {"role": "assistant", "content": text})


def _tally(lines):
    client = OpenAIBatchClient(api_key="k")
    results = [client.parse_provider_response(line) for line in lines]
    requests = {line["custom_id"]: "key" for line in lines}
    replies = read_side_batch(results, requests, "judge")
    return {key: JudgeRequester().settle(key, reply) for key, reply in replies.items()}


def test_one_refused_vote_and_two_passing_votes_fail_the_call():
    refused = _line("j_0", {"role": "assistant", "content": None, "refusal": "I cannot judge"})

    assert _tally([refused, _passing("j_1"), _passing("j_2")]) == {
        "key": [False, "judge call failed: The model refused to answer: I cannot judge"]
    }


def test_three_passing_votes_still_pass_the_call():
    assert _tally([_passing("j_0"), _passing("j_1"), _passing("j_2")])["key"][0] is True
