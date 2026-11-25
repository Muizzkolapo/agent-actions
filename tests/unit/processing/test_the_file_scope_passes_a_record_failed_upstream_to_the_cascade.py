"""The FILE scope pass hands a record failed upstream to the cascade filter, unjudged.

A record an upstream LLM action failed with a parse error carries that action's namespace
as `{raw_response, _parse_error}`, without the fields an action below observes. The FILE
scope pass runs before the cascade filter, so it used to refuse such a record as the FILE
action's own failure (`observe_field_missing`); RECORD mode and the FILE guard leave it
`unprocessed / upstream_unprocessed`. Now the scope pass keeps it, at its position, and
`UnifiedProcessor` quarantines it like any other cascade-blocked record.
"""

from typing import Any

import pytest

from agent_actions.processing.types import ProcessingContext, ProcessingResult
from agent_actions.processing.unified import UnifiedProcessor
from agent_actions.prompt.context.scope_application import apply_context_scope_for_records
from agent_actions.record.reasons import OBSERVE_FIELD_MISSING, UPSTREAM_UNPROCESSED
from agent_actions.workflow.pipeline import scope_refusals

_SCOPE = {"observe": ["a1.n"]}


def _failed_upstream(guid: str, state: str) -> dict:
    return {
        "source_guid": guid,
        "_state": state,
        "content": {"a1": {"raw_response": "I can't help with that.", "_parse_error": "refusal"}},
    }


def _active(guid: str, n: int) -> dict:
    return {"source_guid": guid, "content": {"a1": {"n": n}}}


class _SpyStrategy:
    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []

    def invoke(self, records, context) -> list[ProcessingResult]:
        self.received.extend(records)
        return [ProcessingResult.success(data=[r], source_guid=r["source_guid"]) for r in records]


@pytest.mark.parametrize("state", ["failed", "cascade_skipped", "exhausted"])
class TestTheScopePassKeepsTheRecordAtItsPosition:
    def test_it_is_not_refused(self, state):
        records = [_active("g0", 0), _failed_upstream("g1", state), _active("g2", 2)]

        prepared, skipped = apply_context_scope_for_records(
            records, _SCOPE, source_data=records, action_name="b"
        )

        assert skipped == []
        assert [r["source_guid"] for r in prepared] == ["g0", "g1", "g2"]
        assert prepared[1]["_state"] == state

    @pytest.mark.parametrize("scope", [_SCOPE, {"observe": ["a1.*"]}])
    def test_it_gets_no_flat_keys_and_its_content_is_untouched(self, state, scope):
        """A wildcard would flatten the failed answer's `raw_response` into it."""
        records = [_active("g0", 0), _failed_upstream("g1", state)]

        prepared, _skipped = apply_context_scope_for_records(
            records, scope, source_data=records, action_name="b"
        )

        assert prepared[0]["content"]["n"] == 0, "the active record is still enriched"
        assert prepared[1]["content"] == records[1]["content"]

    def test_an_active_record_missing_the_field_is_still_refused(self, state):
        """The control: only a cascade-blocked record is passed on unjudged."""
        records = [{"source_guid": "g0", "content": {"a1": {"raw_response": "x"}}}]

        prepared, skipped = apply_context_scope_for_records(
            records, _SCOPE, source_data=records, action_name="b"
        )

        assert prepared == []
        assert [s["reason"] for s in skipped] == [OBSERVE_FIELD_MISSING]


@pytest.mark.parametrize("state", ["failed", "cascade_skipped"])
def test_the_cascade_filter_leaves_it_unprocessed_upstream_unprocessed(state):
    """What `pipeline.py` does with the scoped list for a FILE tool or HITL action."""
    records = [_active("g0", 0), _failed_upstream("g1", state)]
    scoped, skipped = apply_context_scope_for_records(
        records, _SCOPE, source_data=records, action_name="b"
    )
    context = ProcessingContext(
        agent_config={"agent_type": "b", "name": "b", "context_scope": _SCOPE},
        agent_name="b",
    )
    strategy = _SpyStrategy()

    dropped = {skip["position"] for skip in skipped}
    pre_observe = [record for at, record in enumerate(records) if at not in dropped]

    output, stats = UnifiedProcessor().process(
        scoped,
        context,
        strategy,
        raw_records=pre_observe,
        refused=scope_refusals(skipped, records),
    )

    assert [r["source_guid"] for r in strategy.received] == ["g0"]
    assert stats.unprocessed == 1
    assert stats.failed == 0
    (tombstone,) = [r for r in output if r["source_guid"] == "g1"]
    assert tombstone["metadata"]["reason"] == UPSTREAM_UNPROCESSED
