"""Online prompt-prep failures are classified FAILED, matching the batch path.

A record whose prompt fails to render is a genuine failure of this action — not
upstream cascade-quarantine — so it must count toward terminal-failure detection.
When every record prep-fails, the action must not report success.
"""

import pytest

from agent_actions.processing.result_collector import CollectionStats
from agent_actions.processing.strategies.online_llm import _build_prep_failed_result
from agent_actions.processing.types import ProcessingContext, ProcessingStatus
from agent_actions.record.reasons import PREP_FAILED


def _ctx():
    return ProcessingContext(agent_config={}, agent_name="vote_quality")


def test_prep_failed_result_is_classified_failed():
    result = _build_prep_failed_result(
        {"source_guid": "g1"}, _ctx(), "Template references undefined variables: key"
    )
    assert result.status == ProcessingStatus.FAILED


def test_prep_failed_result_preserves_lineage_tombstone():
    result = _build_prep_failed_result({"source_guid": "g1"}, _ctx(), "render error")
    assert result.data, "a tombstone must be preserved so downstream can cascade-skip"
    assert result.source_guid == "g1"
    assert result.skip_reason == PREP_FAILED


def test_prep_failed_result_without_source_guid_still_failed():
    # Junk upstream records can lack a source_guid; the prep failure must still
    # register as a failure rather than vanishing into the unprocessed bucket.
    result = _build_prep_failed_result({"content": {}}, _ctx(), "render error")
    assert result.status == ProcessingStatus.FAILED


def test_all_prep_failed_trips_terminal_failure_guard():
    # With prep-failures counted as failed (not unprocessed), an action whose
    # records all prep-fail has active_input_count > 0 and success == 0, so the
    # circuit-breaker raises instead of the run silently reporting success.
    stats = CollectionStats(success=0, failed=3, unprocessed=0)
    with pytest.raises(RuntimeError, match="0 successful records"):
        stats.raise_if_terminal_failure("vote_quality", data=[{}, {}, {}], output=[])


def test_prep_failures_in_unprocessed_bucket_would_not_trip_guard():
    # Guards against regressing to the old classification: if prep-failures were
    # counted as unprocessed, they would be subtracted from active_input_count and
    # the guard would not fire — the exact bug this fix closes.
    stats = CollectionStats(success=0, failed=0, unprocessed=3)
    stats.raise_if_terminal_failure("vote_quality", data=[{}, {}, {}], output=[])  # no raise
