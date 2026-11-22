"""`judge_budget` caps the values judged across every judge batch of the run (1814).

As online, the budget counts real judge calls — one per value, whatever its
votes — and a value past it is skipped, not sent. Each pass rebuilds the suite
from the store, so the balance has to survive each judge batch and each resume.
"""

from agent_actions.llm.batch.core.batch_constants import BatchStatus

from .judge_batch_world import (
    JudgingProvider,
    Run,
    answers,
    judge_rule,
    judged_config,
    value_in,
    verdict,
)


def _judged(provider):
    return [n for name, n in provider.batches if "_judge_" in name]


def _provider():
    return JudgingProvider(
        lambda prompt, _vote: verdict(value_in(prompt) == ["good"], "judged"),
        repair=lambda custom_id: {"options": [f"{custom_id}-repaired"]},
    )


def test_the_budget_caps_the_judge_batches_of_all_rounds_together():
    provider = _provider()
    run = Run(
        judged_config([judge_rule()], repair="auto", max_iterations=2, judge_budget=3),
        provider,
    )
    run.main_batch_returns(answers({"r1": ["bad1"], "r2": ["bad2"]}))
    while run.recovery_batch_returns() is None:
        pass

    assert _judged(provider) == [2, 1], "the repair round's judge batch overspent the budget"
    assert run.online == []
    details = [o["detail"] for v in run.verdicts().values() for o in v["outcomes"]]
    assert any("judge budget exhausted" in d for d in details)


def test_a_value_past_the_budget_is_skipped_not_sent():
    provider = _provider()
    run = Run(judged_config([judge_rule(votes=2)], repair="none", judge_budget=2), provider)
    run.main_batch_returns(answers({"r1": ["bad"], "r2": ["good"], "r3": ["other"]}))

    assert provider.batches == [("f.json_judge_1", 2 * 2)]
    run.recovery_batch_returns()
    (outcome,) = run.verdicts()["r3"]["outcomes"]
    assert outcome["skipped"] is True
    assert "judge budget exhausted" in outcome["detail"]
    assert run.online == []


def test_a_resume_spends_nothing_on_what_is_already_out():
    provider = _provider()
    run = Run(judged_config([judge_rule()], repair="none", judge_budget=5), provider)
    results = answers({"r1": ["bad"], "r2": ["good"]})
    run.main_batch_returns(results)
    balance = run.state().repair_judge_budget_remaining

    provider.status = BatchStatus.IN_PROGRESS
    run.main_batch_returns(answers({"r1": ["bad"], "r2": ["good"]}))

    assert balance == 3
    assert run.state().repair_judge_budget_remaining == balance
