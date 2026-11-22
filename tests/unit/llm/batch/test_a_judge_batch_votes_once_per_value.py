"""Records with the same value share one set of judge votes, in batch as online (1814).

Online, the judge cache spans the action's records: the second record holding a
value already judged is a hit and costs no call. The judge batch dedupes the same
way, and each record still gets the verdict of the value it holds.
"""

from .judge_batch_world import (
    JudgingProvider,
    Run,
    answers,
    judge_rule,
    judged_config,
    value_in,
    verdict,
)

VOTES = 3


def _run():
    provider = JudgingProvider(lambda prompt, vote: verdict(value_in(prompt) == ["good"]))
    run = Run(judged_config([judge_rule(votes=VOTES)], repair="none"), provider)
    run.main_batch_returns(answers({f"r{i}": ["good"] if i % 2 else ["bad"] for i in range(6)}))
    return run, provider


def test_two_distinct_values_cost_one_set_of_votes_each():
    _run_, provider = _run()
    assert provider.batches == [("f.json_judge_1", 2 * VOTES)]


def test_every_record_still_gets_the_verdict_of_its_own_value():
    run, _provider = _run()
    run.recovery_batch_returns()
    assert run.online == []
    passed = {cid: r["overall_pass"] for cid, r in run.verdicts().items()}
    assert passed == {f"r{i}": bool(i % 2) for i in range(6)}
