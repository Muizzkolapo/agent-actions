"""A retry round, then a judge batch, then the file: the judge step rebuilds exhaustion as retry left it.

The step that runs once a judge batch returns rebuilds retry exhaustion from the
saved state. A record the retry recovered is not exhausted, and a record the retry
gave up on carries the failures it counted.
"""

from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.core.batch_constants import RecoveryPhase
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)
from agent_actions.llm.batch.services.retry import BatchRetryService
from agent_actions.llm.batch.services.retry_serialization import serialize_results

from .judge_batch_world import JudgingProvider, Run, answers, judge_rule, judged_config, verdict
from .test_repair_deferral import ACTION, FILE, _context_map


def _after_a_retry(repair: str, *, retried: list[str], max_attempts: int) -> Run:
    """r2 was missing from the main batch; its retry batch returns *retried*."""
    provider = JudgingProvider(
        lambda _prompt, _vote: verdict(True, "fine"),
        repair=lambda _custom_id: {"options": ["v2"]},
    )
    run = Run(judged_config([judge_rule()], repair=repair), provider)
    run.retry_service = MagicMock(wraps=BatchRetryService())
    run.context_map.update(_context_map("r1", "r2"))
    RecoveryStateManager.save(
        run.backend,
        ACTION,
        FILE,
        RecoveryState(
            phase=RecoveryPhase.RETRY,
            retry_attempt=1,
            retry_max_attempts=max_attempts,
            missing_ids=["r2"],
            record_failure_counts={"r2": 1},
            accumulated_results=serialize_results(answers({"r1": ["v1"]})),
        ),
    )
    provider._tasks["batch-retry"] = [{"custom_id": cid} for cid in retried]
    run.registry.save_batch_job(
        f"{FILE}_retry_1",
        BatchJobEntry(
            batch_id="batch-retry",
            status="completed",
            timestamp="t",
            provider="openai",
            record_count=1,
            file_name=f"{FILE}_retry_1",
            parent_file_name=FILE,
            recovery_type="retry",
            recovery_attempt=1,
        ),
    )
    assert run.recovery_batch_returns() is None, "the retry step sent no judge batch"
    assert run.live_entry().recovery_type == "judge"
    assert run.recovery_batch_returns() == "/out.json"
    return run


@pytest.mark.parametrize("repair", ["auto", "none"])
def test_a_record_the_retry_recovered_is_not_rebuilt_as_exhausted(repair):
    run = _after_a_retry(repair, retried=["r2"], max_attempts=3)

    assert [name for name, _n in run.provider.batches] == [f"{FILE}_judge_1"]
    assert run.exhausted is None, f"rebuilt as exhausted: {sorted(run.exhausted or {})}"
    finalized = {r.custom_id: r for r in run.finalized}
    assert finalized["r2"].success is True
    assert not finalized["r2"].exhausted


@pytest.mark.parametrize("repair", ["auto", "none"])
def test_a_record_the_retry_gave_up_on_carries_every_failure_it_counted(repair):
    run = _after_a_retry(repair, retried=[], max_attempts=2)

    assert run.exhausted is not None and set(run.exhausted) == {"r2"}
    retry = run.exhausted["r2"].retry
    assert (retry.attempts, retry.failures, retry.succeeded) == (2, 2, False)
