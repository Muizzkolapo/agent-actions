"""The deferred mechanism itself: submit a round, pause, resume, finalise.

Every defect found in this loop so far was invisible to a green suite because
the tests drove the leaf helpers directly. These drive `check_and_submit_repair`
and `handle_repair_recovery` — the two functions that decide whether a run
pauses, what it persists, and what reaches the output.
"""

from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_models import BatchIdentity, BatchJobEntry, RecoveryContext
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.services import processing_recovery as pr
from agent_actions.llm.providers.batch_base import BatchResult

from .test_reprompt_feedback_delivery import RecordingProvider

ACTION = "author"
FILE = "f.json"
PROMPT = "Write the options."

EXPECTATIONS = [{"id": "enough", "type": "item_count", "field": "options", "min": 2}]
FAILING = {"options": ["one"]}
PASSING = {"options": ["a", "b"]}


def _agent_config(**expect: Any) -> dict[str, Any]:
    return {
        "name": ACTION,
        "action_name": ACTION,
        "agent_type": ACTION,
        "json_mode": False,
        "model_name": "test-model",
        "prompt": PROMPT,
        "run_mode": "batch",
        "expect": {"expectations": EXPECTATIONS, "repair": "auto", **expect},
    }


class _Backend:
    """Just enough storage for the recovery state to round-trip."""

    def __init__(self) -> None:
        self.meta: dict[str, str] = {}

    def save_metadata(self, key: str, value: str) -> None:
        self.meta[key] = value

    def load_metadata(self, key: str) -> str | None:
        return self.meta.get(key)

    def delete_metadata(self, key: str) -> bool:
        return self.meta.pop(key, None) is not None

    def list_source_files(self):
        return []


def _context(provider, backend, agent_config):
    service = MagicMock()
    service._storage_backend = backend
    service._action_indices = {ACTION: 0}
    service._dependency_configs = {}
    service._resolve_action_name.return_value = ACTION
    return RecoveryContext(
        service=service,
        manager=MagicMock(),
        provider=provider,
        agent_config=agent_config,
        output_directory="/tmp/test",
        action_name=ACTION,
        start_time=0.0,
    )


def _identity() -> BatchIdentity:
    return BatchIdentity(
        batch_id="b1",
        file_name=FILE,
        entry=BatchJobEntry(
            batch_id="b1", status="completed", timestamp="t", provider="ollama_cloud"
        ),
    )


def _context_map(*ids: str) -> dict[str, Any]:
    return {
        cid: {"target_id": cid, "source_guid": f"sg-{cid}", "content": {"source": {"t": "x"}}}
        for cid in ids
    }


def _prepared():
    prepared = MagicMock()
    prepared.formatted_prompt = PROMPT
    prepared.llm_context = {"source": {"t": "x"}}
    prepared.should_execute = True
    return prepared


def _submit(results, agent_config=None, recovery_state=None):
    """Run check_and_submit_repair; returns (should_continue, provider, backend)."""
    provider = RecordingProvider()
    backend = _Backend()
    config = agent_config or _agent_config()
    with patch(
        "agent_actions.processing.task_preparer.TaskPreparer.prepare", return_value=_prepared()
    ):
        should_continue = pr.check_and_submit_repair(
            _context(provider, backend, config),
            _identity(),
            batch_results=results,
            context_map=_context_map(*[r.custom_id for r in results]),
            recovery_state=recovery_state,
        )
    return should_continue, provider, backend


def _state(backend: _Backend) -> RecoveryState | None:
    raw = backend.meta.get(f"recovery_state:{ACTION}:{FILE}")
    if raw is None:
        return None
    import json

    return RecoveryState(**json.loads(raw))


class TestSubmittingARound:
    def test_a_failing_record_pauses_the_run(self):
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        should_continue, provider, _ = _submit([failing])
        assert should_continue is False, "a repair round was due but the run did not pause"
        assert provider.submitted

    def test_an_all_passing_set_does_not_pause(self):
        passing = BatchResult(custom_id="r1", content=PASSING, success=True)
        should_continue, provider, _ = _submit([passing])
        assert should_continue is True
        assert provider.submitted == []

    def test_a_passing_record_carries_its_verdict_without_a_round(self):
        passing = BatchResult(custom_id="r1", content=PASSING, success=True)
        _submit([passing])
        assert passing.content["expect"]["overall_pass"] is True

    def test_observe_mode_never_pauses(self):
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        should_continue, provider, _ = _submit([failing], _agent_config(repair="none"))
        assert should_continue is True
        assert provider.submitted == []


class TestWhatTheRoundPersists:
    def test_the_ids_it_sent_are_recorded_for_the_resuming_pass(self):
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        _should, _provider, backend = _submit([failing])
        assert _state(backend).repair_submitted_ids == ["r1"]

    def test_a_record_that_passed_is_graduated_not_resubmitted(self):
        passing = BatchResult(custom_id="ok", content=PASSING, success=True)
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        _should, provider, backend = _submit([passing, failing])
        assert _state(backend).repair_submitted_ids == ["r1"]
        assert len(_state(backend).graduated_results) == 1

    def test_a_provider_failure_is_kept_rather_than_dropped(self):
        """It failed at the provider, not at its expectations — there is nothing
        to regenerate, but it still has to reach the output with its error."""
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        api_error = BatchResult(custom_id="bad", content=None, success=False, error="429")
        _should, _provider, backend = _submit([failing, api_error])
        carried = _state(backend).graduated_results
        assert any(r.get("custom_id") == "bad" for r in carried), (
            "a provider-failed record was dropped when a sibling needed repair"
        )

    def test_the_retry_bookkeeping_is_not_discarded(self):
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        prior = RecoveryState(missing_ids=["m1"], record_failure_counts={"m1": 2}, retry_attempt=1)
        _should, _provider, backend = _submit([failing], recovery_state=prior)
        state = _state(backend)
        assert state.missing_ids == ["m1"]
        assert state.record_failure_counts == {"m1": 2}


class TestTheRoundIsBounded:
    def test_the_last_round_does_not_submit_again(self):
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        spent = RecoveryState(repair_attempt=1, repair_max_attempts=1)
        should_continue, provider, _ = _submit(
            [failing], _agent_config(max_iterations=2), recovery_state=spent
        )
        assert should_continue is True, "the iterations were spent but another round was submitted"
        assert provider.submitted == []

    def test_the_exhausted_record_is_stamped_with_what_failed(self):
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        spent = RecoveryState(repair_attempt=1, repair_max_attempts=1)
        _submit([failing], _agent_config(max_iterations=2), recovery_state=spent)
        assert failing.recovery_metadata.expectations.failed == ["enough"]

    def test_max_iterations_of_one_never_submits_a_round(self):
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        should_continue, provider, _ = _submit([failing], _agent_config(max_iterations=1))
        assert should_continue is True
        assert provider.submitted == []

    def test_the_counter_is_read_from_state_not_the_caller(self):
        """The original batch is re-processed on every resume and passes None.

        Reading the counter from persisted state is what stops that path
        submitting a fresh round forever.
        """
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        provider = RecordingProvider()
        backend = _Backend()
        import json

        backend.meta[f"recovery_state:{ACTION}:{FILE}"] = json.dumps(
            RecoveryState(repair_attempt=1, repair_max_attempts=1).to_dict()
        )
        with patch(
            "agent_actions.processing.task_preparer.TaskPreparer.prepare", return_value=_prepared()
        ):
            should_continue = pr.check_and_submit_repair(
                _context(provider, backend, _agent_config(max_iterations=2)),
                _identity(),
                batch_results=[failing],
                context_map=_context_map("r1"),
                recovery_state=None,
            )
        assert should_continue is True
        assert provider.submitted == []


class TestResumingTheRound:
    def _resume(self, state, recovery_results, agent_config=None):
        provider = RecordingProvider()
        backend = _Backend()
        config = agent_config or _agent_config()
        with (
            patch(
                "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                return_value=_prepared(),
            ),
            patch.object(pr, "_finalize_and_cleanup", return_value="/out.json") as finalize,
        ):
            out = pr.handle_repair_recovery(
                _context(provider, backend, config),
                _identity(),
                state=state,
                recovery_results=recovery_results,
                accumulated=[],
                context_map=_context_map(*[r.custom_id for r in recovery_results]),
            )
        return out, finalize, provider

    def test_a_repaired_record_finalises_with_its_verdict(self):
        state = RecoveryState(repair_attempt=1, repair_max_attempts=1, repair_submitted_ids=["r1"])
        repaired = BatchResult(custom_id="r1", content=PASSING, success=True)
        out, finalize, _ = self._resume(state, [repaired])
        assert out == "/out.json"
        assert repaired.content["expect"]["overall_pass"] is True
        finalized = finalize.call_args.kwargs["batch_results"]
        assert [r.custom_id for r in finalized] == ["r1"]

    def test_a_record_the_provider_never_returned_still_reaches_the_output(self):
        state = RecoveryState(
            repair_attempt=1, repair_max_attempts=1, repair_submitted_ids=["r1", "gone"]
        )
        repaired = BatchResult(custom_id="r1", content=PASSING, success=True)
        _out, finalize, _ = self._resume(state, [repaired])
        finalized = finalize.call_args.kwargs["batch_results"]
        assert "gone" in [r.custom_id for r in finalized], (
            "a record submitted for repair and never returned vanished from the output"
        )

    def test_the_retry_bookkeeping_reaches_finalisation(self):
        state = RecoveryState(
            repair_attempt=1,
            repair_max_attempts=1,
            repair_submitted_ids=["r1"],
            missing_ids=["m1"],
            record_failure_counts={"m1": 2},
        )
        repaired = BatchResult(custom_id="r1", content=PASSING, success=True)
        _out, finalize, _ = self._resume(state, [repaired])
        assert finalize.call_args.kwargs["exhausted_recovery"] is not None


class TestTheBudgetBoundsTheRunNotTheRound:
    """Each deferred pass rebuilds the service, so the balance has to be carried.

    Without it, `max_iterations` rounds each start from a full `judge_budget`
    and can spend that many times the configured cap.
    """

    JUDGED = [
        {"id": "enough", "type": "item_count", "field": "options", "min": 2},
        {"id": "on_topic", "type": "llm_judge", "field": "options", "rule": "on topic"},
    ]

    def _judged_config(self, **expect):
        config = _agent_config(**expect)
        config["expect"]["expectations"] = self.JUDGED
        config["model_vendor"] = "anthropic"
        return config

    def test_the_balance_is_persisted_when_a_round_defers(self):
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        _should, _provider, backend = _submit([failing], self._judged_config(judge_budget=5))
        assert _state(backend).repair_judge_budget_remaining is not None

    def test_the_resuming_pass_starts_from_the_balance(self):
        from agent_actions.llm.batch.services.repair_ops import build_repair_strategy

        strategy = build_repair_strategy(self._judged_config(judge_budget=5), 2)
        assert strategy.judge_budget_remaining == 2

    def test_an_uncapped_budget_stays_uncapped(self):
        from agent_actions.llm.batch.services.repair_ops import build_repair_strategy

        strategy = build_repair_strategy(self._judged_config(), None)
        assert strategy.judge_budget_remaining is None

    def test_a_spent_balance_of_zero_is_honoured_not_treated_as_absent(self):
        from agent_actions.llm.batch.services.repair_ops import build_repair_strategy

        strategy = build_repair_strategy(self._judged_config(judge_budget=5), 0)
        assert strategy.judge_budget_remaining == 0

    def test_a_suite_that_never_judges_has_no_budget_to_carry(self):
        from agent_actions.llm.batch.services.repair_ops import build_repair_strategy

        assert build_repair_strategy(_agent_config(judge_budget=5)).judge_budget_remaining is None


class TestANonTerminalRoundKeepsWhatItCannotResubmit:
    """The default max_iterations is 3, so the first round is not the last one.

    Only resubmitted records come back on the next pass; anything else has to
    enter the persisted pool before the run defers, or it is in no pool at all.
    """

    def _resume_continuing(self, recovery_results):
        state = RecoveryState(
            repair_attempt=1,
            repair_max_attempts=2,
            repair_submitted_ids=[r.custom_id for r in recovery_results],
        )
        provider = RecordingProvider()
        backend = _Backend()
        with patch(
            "agent_actions.processing.task_preparer.TaskPreparer.prepare", return_value=_prepared()
        ):
            out = pr.handle_repair_recovery(
                _context(provider, backend, _agent_config(max_iterations=3)),
                _identity(),
                state=state,
                recovery_results=recovery_results,
                accumulated=[],
                context_map=_context_map(*[r.custom_id for r in recovery_results]),
            )
        return out, state

    def test_a_provider_failure_is_pooled_before_the_next_round(self):
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        api_error = BatchResult(custom_id="e1", content=None, success=False, error="429")
        out, state = self._resume_continuing([failing, api_error])
        assert out is None, "another round was due, so the run should have deferred"
        pooled = [r.get("custom_id") for r in state.graduated_results]
        assert "e1" in pooled, "a provider failure vanished when another round was submitted"

    def test_the_error_message_survives_being_pooled(self):
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        api_error = BatchResult(custom_id="e1", content=None, success=False, error="429 rate limit")
        _out, state = self._resume_continuing([failing, api_error])
        pooled = {r.get("custom_id"): r for r in state.graduated_results}
        assert pooled["e1"].get("error") == "429 rate limit"


class TestReEnteringADeferredRoundDoesNotDuplicate:
    """A deferring round leaves its registry entry COMPLETED at the provider.

    The runner iterates every completed job each pass, so the same repair round
    is handed back more than once. What it graduates must land in the pool once.
    """

    def _resume_twice(self):
        state = RecoveryState(
            repair_attempt=1, repair_max_attempts=2, repair_submitted_ids=["g1", "r1"]
        )
        graduated = BatchResult(custom_id="g1", content=PASSING, success=True)
        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        provider = RecordingProvider()
        backend = _Backend()
        with patch(
            "agent_actions.processing.task_preparer.TaskPreparer.prepare", return_value=_prepared()
        ):
            for _pass in range(2):
                pr.handle_repair_recovery(
                    _context(provider, backend, _agent_config(max_iterations=3)),
                    _identity(),
                    state=state,
                    recovery_results=[graduated, failing],
                    accumulated=[],
                    context_map=_context_map("g1", "r1"),
                )
        return state

    def test_the_pool_holds_one_entry_per_record(self):
        state = self._resume_twice()
        ids = [r.get("custom_id") for r in state.graduated_results]
        assert sorted(ids) == sorted(set(ids)), f"a record was pooled more than once: {ids}"


class TestAStaleStateFileCannotStarveTheJudge:
    """`_process_original_batch` passes recovery_state=None deliberately — an
    existing file there may be left over from a crashed run.

    Reading the counter back is what stops the loop resubmitting forever, but a
    stale budget of 0 would turn every judged expectation into a hard failure on
    an otherwise fresh run.
    """

    JUDGED = [{"id": "j", "type": "llm_judge", "field": "options", "rule": "on topic"}]

    def _judged_config(self):
        config = _agent_config(judge_budget=5)
        config["expect"]["expectations"] = self.JUDGED
        config["model_vendor"] = "anthropic"
        return config

    def test_a_state_left_by_a_crashed_run_does_not_supply_a_spent_budget(self):
        import json

        from agent_actions.llm.batch.core.batch_constants import RecoveryPhase

        stale = RecoveryState(phase=RecoveryPhase.RETRY, repair_judge_budget_remaining=0)
        backend = _Backend()
        backend.meta[f"recovery_state:{ACTION}:{FILE}"] = json.dumps(stale.to_dict())

        seen = {}
        real = pr.__dict__.get("_noop")
        import agent_actions.llm.batch.services.repair_ops as repair_ops

        original = repair_ops.build_repair_strategy

        def spy(agent_config, judge_budget_remaining=None):
            seen["budget"] = judge_budget_remaining
            return original(agent_config, judge_budget_remaining)

        passing = BatchResult(custom_id="r1", content=PASSING, success=True)
        with patch.object(repair_ops, "build_repair_strategy", spy):
            pr.check_and_submit_repair(
                _context(RecordingProvider(), backend, self._judged_config()),
                _identity(),
                batch_results=[passing],
                context_map=_context_map("r1"),
                recovery_state=None,
            )
        assert seen["budget"] is None, (
            "a stale non-repair state supplied a spent judge budget to a fresh pass"
        )

    def test_an_in_flight_repair_state_still_supplies_its_balance(self):
        import json

        from agent_actions.llm.batch.core.batch_constants import RecoveryPhase

        live = RecoveryState(
            phase=RecoveryPhase.REPAIR, repair_attempt=1, repair_judge_budget_remaining=2
        )
        backend = _Backend()
        backend.meta[f"recovery_state:{ACTION}:{FILE}"] = json.dumps(live.to_dict())

        seen = {}
        import agent_actions.llm.batch.services.repair_ops as repair_ops

        original = repair_ops.build_repair_strategy

        def spy(agent_config, judge_budget_remaining=None):
            seen["budget"] = judge_budget_remaining
            return original(agent_config, judge_budget_remaining)

        passing = BatchResult(custom_id="r1", content=PASSING, success=True)
        with patch.object(repair_ops, "build_repair_strategy", spy):
            pr.check_and_submit_repair(
                _context(RecordingProvider(), backend, self._judged_config()),
                _identity(),
                batch_results=[passing],
                context_map=_context_map("r1"),
                recovery_state=None,
            )
        assert seen["budget"] == 2
