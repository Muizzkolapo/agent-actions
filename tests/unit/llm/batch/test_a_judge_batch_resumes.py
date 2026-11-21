"""A run stopped while its judge batch is out picks it up again, and never sends it twice (1814).

The main batch's registry entry is never retired, so a resume can hand the pass
the main results again while the judge batch is still out, or already finished
and not yet read.
"""

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus

from .judge_batch_world import JudgingProvider, Run, answers, judge_rule, judged_config, verdict

VALUES = {"r1": ["a"], "r2": ["b"]}


def _sent(repair="auto"):
    provider = JudgingProvider(lambda _prompt, _vote: verdict(True, "fine"))
    run = Run(judged_config([judge_rule(votes=2)], repair=repair), provider)
    assert run.main_batch_returns(answers(VALUES)) is False
    return run, provider


@pytest.mark.parametrize("status", [BatchStatus.IN_PROGRESS, BatchStatus.COMPLETED])
def test_a_resume_while_the_judge_batch_is_unread_sends_nothing_new(status):
    run, provider = _sent()
    provider.status = status

    assert run.main_batch_returns(answers(VALUES)) is False, "the pass did not wait for it"
    assert provider.batches == [("f.json_judge_1", 4)], "a second judge batch went out"
    assert run.online == []


def test_the_finished_batch_is_read_by_the_id_it_was_registered_under():
    run, provider = _sent()
    registered = run.live_entry().batch_id

    assert run.recovery_batch_returns() == "/out.json"
    assert provider.read == [registered]
    assert provider.batches == [("f.json_judge_1", 4)], "the finished batch was sent again"
    assert run.online == []
    assert all(v["overall_pass"] for v in run.verdicts().values())


def test_the_verdicts_are_kept_while_the_step_waits_on_another_batch():
    """Read from the store, not from memory: a resume is a new process."""
    run, _provider = _sent()
    state = run.state()
    assert state is not None and state.side_requests and state.side_waiting


def test_a_judge_batch_the_provider_failed_fails_its_judgements_closed():
    run, provider = _sent(repair="none")
    run.live_entry().status = BatchStatus.FAILED

    run.recovery_batch_returns()

    assert provider.read == [], "a failed batch has nothing to read"
    assert provider.batches == [("f.json_judge_1", 4)]
    assert run.online == []
    for record in run.verdicts().values():
        (outcome,) = record["outcomes"]
        assert outcome["passed"] is False
        assert outcome["detail"].startswith("judge call failed")


def test_a_failed_judge_batch_still_holds_its_main_batch():
    """Otherwise the main batch is read again from scratch and its judge batch sent again."""
    from agent_actions.llm.batch.core.batch_models import BatchJobEntry
    from agent_actions.llm.batch.services.processing import _superseded_entries

    def entry(name, status, **recovery):
        return BatchJobEntry(
            batch_id=f"b-{name}",
            status=status,
            timestamp="t",
            provider="openai",
            file_name=name,
            **recovery,
        )

    jobs = {
        "f.json": entry("f.json", BatchStatus.COMPLETED),
        "f.json_judge_1": entry(
            "f.json_judge_1",
            BatchStatus.FAILED,
            parent_file_name="f.json",
            recovery_type="side",
            side_kind="judge",
            recovery_attempt=1,
        ),
    }
    assert _superseded_entries(jobs) == {"f.json"}
