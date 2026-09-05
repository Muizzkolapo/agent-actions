"""A record sent back for reprompting has left the pool of finished work.

The two repair sites evict what they put in flight — "a record is never both
pooled and in flight". The reprompt sites did not, so a record could sit in the
pool as finished while a reprompt round was regenerating it. When the round
comes back without it, `dropped_from` reconstructs it as a failure and the
tombstone overwrites the good pooled copy.

Reachable the same way it was for repair: a provider that returns one custom_id
twice, once passing and once failing, pools the passing copy and resubmits the
failing one in the same round.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_constants import RecoveryPhase
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.services import processing_recovery as pr
from agent_actions.llm.providers.batch_base import BatchResult

ACTION = "author"


def _agent_config() -> dict[str, Any]:
    return {
        "name": ACTION,
        "action_name": ACTION,
        "agent_type": ACTION,
        "json_mode": False,
        "model_name": "test-model",
        "prompt": "Write the options.",
        "reprompt": {"validation": "check_it", "max_attempts": 3},
    }


def _context_map(*ids: str) -> dict[str, Any]:
    return {
        cid: {"target_id": cid, "source_guid": f"sg-{cid}", "content": {"source": {"t": cid}}}
        for cid in ids
    }


def _submit_a_reprompt_round(returned: list[BatchResult], prior: RecoveryState | None):
    """Drive check_and_submit_reprompt and hand back the state it persisted."""
    good = [r for r in returned if r.content and r.content.get("ok")]
    bad = [r for r in returned if not (r.content and r.content.get("ok"))]
    loop = MagicMock()
    loop.split.return_value = (good, bad, {})
    strategy = MagicMock()
    strategy.name = "check_it"
    strategy.max_attempts = 3
    strategy.on_exhausted = "return_last"

    context = MagicMock()
    context.agent_config = _agent_config()
    context.service._resolve_action_name.return_value = ACTION
    context.service._storage_backend = None
    context.service._retry_service.submit_reprompt_batch.side_effect = lambda **kw: (
        "b-rp",
        {r.custom_id for r in kw["failed_results"]},
    )
    saved: list[RecoveryState] = []
    with (
        patch(
            "agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop",
            return_value=(loop, strategy),
        ),
        patch.object(
            pr.RecoveryStateManager, "save", side_effect=lambda *a, **k: saved.append(a[-1])
        ),
        patch.object(pr, "register_recovery_batch"),
    ):
        pr.check_and_submit_reprompt(
            context,
            MagicMock(file_name="f.json"),
            batch_results=returned,
            context_map=_context_map(*{r.custom_id for r in returned}),
            recovery_state=prior,
        )
    assert saved, "the reprompt round did not persist state"
    return saved[-1]


class TestARecordSentForRepromptingLeavesThePool:
    def test_a_record_the_provider_returned_twice_does_not_stay_pooled(self):
        state = _submit_a_reprompt_round(
            [
                BatchResult(custom_id="r1", content={"ok": True}, success=True),
                BatchResult(custom_id="r1", content={"ok": False}, success=True),
            ],
            prior=None,
        )
        pooled = [r.get("custom_id") for r in state.graduated_results]
        assert "r1" not in pooled, (
            f"r1 was pooled by the passing copy and resubmitted by the failing one ({pooled}); "
            "when the round returns without it, its tombstone overwrites the good copy"
        )

    def test_a_record_out_for_repair_is_not_pooled_by_a_reprompt_round(self):
        prior = RecoveryState(
            phase=RecoveryPhase.REPAIR,
            repair_attempt=1,
            repair_max_attempts=2,
            repair_submitted_ids=["out-for-repair"],
            evaluation_strategy_name="expectations",
        )
        state = _submit_a_reprompt_round(
            [
                BatchResult(custom_id="out-for-repair", content={"ok": True}, success=True),
                BatchResult(custom_id="r2", content={"ok": False}, success=True),
            ],
            prior=prior,
        )
        pooled = [r.get("custom_id") for r in state.graduated_results]
        assert "out-for-repair" not in pooled, (
            f"a record the repair loop is regenerating was pooled as finished ({pooled})"
        )


class TestRecordsNobodyIsRegeneratingStillShip:
    def test_a_graduated_record_stays_pooled(self):
        state = _submit_a_reprompt_round(
            [
                BatchResult(custom_id="done", content={"ok": True}, success=True),
                BatchResult(custom_id="r2", content={"ok": False}, success=True),
            ],
            prior=None,
        )
        pooled = [r.get("custom_id") for r in state.graduated_results]
        assert pooled == ["done"], f"the finished record was dropped: {pooled}"

    def test_an_earlier_pool_entry_survives(self):
        from agent_actions.llm.batch.services.retry_serialization import serialize_results

        prior = RecoveryState(
            phase=RecoveryPhase.REPROMPT,
            graduated_results=serialize_results(
                [BatchResult(custom_id="earlier", content={"ok": True}, success=True)]
            ),
            evaluation_strategy_name="validation",
        )
        state = _submit_a_reprompt_round(
            [BatchResult(custom_id="r2", content={"ok": False}, success=True)], prior=prior
        )
        pooled = [r.get("custom_id") for r in state.graduated_results]
        assert "earlier" in pooled


class TestAReturningRepromptRoundRespectsItToo:
    """The other pool write: a reprompt round coming back, not going out."""

    def _handle_a_returning_round(self, repair_holds: list[str]):
        graduated = BatchResult(custom_id="out-for-repair", content={"ok": True}, success=True)
        still_bad = BatchResult(custom_id="r2", content={"ok": False}, success=True)
        state = RecoveryState(
            phase=RecoveryPhase.REPROMPT,
            reprompt_attempt=1,
            reprompt_max_attempts=3,
            validation_name="check_it",
            on_exhausted="return_last",
            repair_submitted_ids=list(repair_holds),
            evaluation_strategy_name="validation",
        )
        loop = MagicMock()
        loop.split.return_value = ([graduated], [still_bad], {})
        strategy = MagicMock()
        strategy.name = "check_it"
        strategy.max_attempts = 3
        strategy.on_exhausted = "return_last"

        context = MagicMock()
        context.agent_config = _agent_config()
        context.service._resolve_action_name.return_value = ACTION
        context.service._storage_backend = None
        context.service._retry_service.submit_reprompt_batch.side_effect = lambda **kw: (
            "b-rp2",
            {r.custom_id for r in kw["failed_results"]},
        )
        saved: list[RecoveryState] = []
        with (
            patch(
                "agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop",
                return_value=(loop, strategy),
            ),
            patch.object(
                pr.RecoveryStateManager, "save", side_effect=lambda *a, **k: saved.append(a[-1])
            ),
            patch.object(pr, "register_recovery_batch"),
            patch.object(pr, "_finalize_and_cleanup", return_value="/out.json"),
            patch.object(pr, "check_and_submit_repair", return_value=True),
        ):
            pr.handle_reprompt_recovery(
                context,
                MagicMock(file_name="f.json"),
                state=state,
                recovery_results=[graduated, still_bad],
                accumulated=[],
                context_map=_context_map("out-for-repair", "r2"),
            )
        return state, saved

    def test_a_record_the_repair_loop_holds_is_not_pooled(self):
        state, _saved = self._handle_a_returning_round(repair_holds=["out-for-repair"])
        pooled = [r.get("custom_id") for r in state.graduated_results]
        assert "out-for-repair" not in pooled, (
            f"the reprompt round pooled a record the repair loop is regenerating ({pooled}); when "
            "the repair round returns without it, its tombstone overwrites this good copy"
        )

    def test_a_record_nobody_holds_is_pooled_normally(self):
        state, _saved = self._handle_a_returning_round(repair_holds=[])
        pooled = [r.get("custom_id") for r in state.graduated_results]
        assert "out-for-repair" in pooled, f"a graduated record was dropped: {pooled}"
