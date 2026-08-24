"""The deferred mechanism itself: submit a round, pause, resume, finalise.

Every defect found in this loop so far was invisible to a green suite because
the tests drove the leaf helpers directly. These drive `check_and_submit_repair`
and `handle_repair_recovery` — the two functions that decide whether a run
pauses, what it persists, and what reaches the output.
"""

from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.expectations.service import ExpectationsExhaustedError
from agent_actions.llm.batch.core.batch_constants import RecoveryPhase
from agent_actions.llm.batch.core.batch_models import (
    BatchIdentity,
    BatchJobEntry,
    BatchRegistryStats,
    RecoveryContext,
)
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
            RecoveryState(
                phase=RecoveryPhase.REPAIR, repair_attempt=1, repair_max_attempts=1
            ).to_dict()
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
        with (
            patch(
                "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                return_value=_prepared(),
            ),
            patch.object(pr, "_finalize_and_cleanup", return_value="/out.json"),
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


class TestTheLoadedStateIsTrustedWhole:
    """The re-entry paths pass None, and the persisted state is the only record
    of where the loop got to.

    A phase guard cannot separate a stale file from a live one — a run that
    crashed mid-repair leaves a REPAIR state too — and discarding the state
    throws away the retry and reprompt bookkeeping the reprompt handoff needs.
    """

    JUDGED = [{"id": "j", "type": "llm_judge", "field": "options", "rule": "on topic"}]

    def _judged_config(self):
        config = _agent_config(judge_budget=5)
        config["expect"]["expectations"] = self.JUDGED
        config["model_vendor"] = "anthropic"
        return config

    def test_a_live_reprompt_state_is_not_discarded_by_the_repair_round(self):
        """`handle_reprompt_recovery` hands repair a None, so repair reloads.

        Driven through `check_and_submit_repair` rather than `carry_forward`,
        because it is the reload that decides what survives — calling the
        composer directly with an explicit prior proves nothing about it.
        """
        import json

        live = RecoveryState(
            phase=RecoveryPhase.REPROMPT,
            missing_ids=["m1"],
            record_failure_counts={"m1": 3},
            retry_attempt=3,
            reprompt_attempt=2,
            validation_name="schema",
        )
        backend = _Backend()
        backend.meta[f"recovery_state:{ACTION}:{FILE}"] = json.dumps(live.to_dict())

        failing = BatchResult(custom_id="r1", content=FAILING, success=True)
        provider = RecordingProvider()
        with patch(
            "agent_actions.processing.task_preparer.TaskPreparer.prepare", return_value=_prepared()
        ):
            pr.check_and_submit_repair(
                _context(provider, backend, _agent_config(max_iterations=2)),
                _identity(),
                batch_results=[failing],
                context_map=_context_map("r1"),
                recovery_state=None,
            )
        saved = _state(backend)
        assert saved.missing_ids == ["m1"], (
            "the repair round discarded the retry bookkeeping finalisation rebuilds "
            "exhausted_recovery from"
        )
        assert saved.record_failure_counts == {"m1": 3}
        assert saved.reprompt_attempt == 2
        assert saved.validation_name == "schema"

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
        with (
            patch.object(repair_ops, "build_repair_strategy", spy),
            patch(
                "agent_actions.expectations.judge.invoke_judge_with_votes",
                return_value=(True, "ok"),
            ),
        ):
            pr.check_and_submit_repair(
                _context(RecordingProvider(), backend, self._judged_config()),
                _identity(),
                batch_results=[passing],
                context_map=_context_map("r1"),
                recovery_state=None,
            )
        assert seen["budget"] == 2


class TestRaiseHaltsWithoutLosingWhatWasAlreadyEarned:
    """`on_exhausted: raise` stops the run — it does not un-earn the round.

    Online, records are persisted as they are processed, so halting keeps
    everything that already succeeded. Batch writes the file once at the end, so
    raising before that point throws away every record the loop had graduated —
    each of which cost a real generation and was already judged.
    """

    def _drive(self, policy: str):
        good = BatchResult(custom_id="paid-for", content=PASSING, success=True)
        bad = BatchResult(custom_id="r1", content=FAILING, success=True)
        state = RecoveryState(
            repair_attempt=1, repair_max_attempts=1, repair_submitted_ids=["paid-for", "r1"]
        )
        config = _agent_config(max_iterations=2, on_exhausted=policy)
        # Patch what the finaliser calls, not the finaliser itself: the ordering
        # under test lives inside it, and a stub would have to mimic that
        # ordering to prove anything about it.
        with (
            patch(
                "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                return_value=_prepared(),
            ),
            patch.object(pr, "finalize_batch_output", return_value="/out.json") as finalize,
            patch.object(pr, "cleanup_recovery"),
            patch.object(pr.RecoveryStateManager, "delete"),
        ):
            raised = None
            try:
                pr.handle_repair_recovery(
                    _context(RecordingProvider(), _Backend(), config),
                    _identity(),
                    state=state,
                    recovery_results=[good, bad],
                    accumulated=[],
                    context_map=_context_map("paid-for", "r1"),
                )
            except ExpectationsExhaustedError as exc:
                raised = exc
        return finalize, raised

    def test_the_run_still_halts(self):
        _finalize, raised = self._drive("raise")
        assert raised is not None, "on_exhausted: raise must stop the run"

    def test_the_output_is_written_before_it_halts(self):
        finalize, _raised = self._drive("raise")
        assert finalize.called, "the file was never written, so the round's work was discarded"

    def test_a_graduated_record_survives_the_halt(self):
        finalize, _raised = self._drive("raise")
        shipped = [r.custom_id for r in finalize.call_args.kwargs["batch_results"]]
        assert "paid-for" in shipped, (
            "a record that passed its expectations was lost when a sibling exhausted"
        )

    def test_the_exhausted_record_is_shipped_with_its_metadata(self):
        finalize, _raised = self._drive("raise")
        shipped = {r.custom_id: r for r in finalize.call_args.kwargs["batch_results"]}
        assert shipped["r1"].recovery_metadata.expectations.failed == ["enough"]

    def test_return_last_does_not_halt(self):
        _finalize, raised = self._drive("return_last")
        assert raised is None

    def test_fail_does_not_halt_but_marks_the_record(self):
        finalize, raised = self._drive("fail")
        assert raised is None
        shipped = {r.custom_id: r for r in finalize.call_args.kwargs["batch_results"]}
        assert shipped["r1"].success is False
        assert shipped["paid-for"].success is True


class TestTheSubmitSideParksItsErrorToo:
    """`check_and_submit_repair` exhausts on the pass that runs out of rounds.

    It returns True and its caller finalises, so the error has to travel on the
    context — raising in place would discard the same round's work as the resume
    path did.
    """

    def _exhaust_on_submit(self, policy: str):
        good = BatchResult(custom_id="paid-for", content=PASSING, success=True)
        bad = BatchResult(custom_id="r1", content=FAILING, success=True)
        context = _context(
            RecordingProvider(), _Backend(), _agent_config(max_iterations=1, on_exhausted=policy)
        )
        with patch(
            "agent_actions.processing.task_preparer.TaskPreparer.prepare", return_value=_prepared()
        ):
            should_continue = pr.check_and_submit_repair(
                context,
                _identity(),
                batch_results=[good, bad],
                context_map=_context_map("paid-for", "r1"),
                recovery_state=None,
            )
        return context, should_continue

    def test_it_does_not_raise_in_place(self):
        context, should_continue = self._exhaust_on_submit("raise")
        assert should_continue is True, "the caller must still get a chance to write the file"
        assert context.pending_exhaustion is not None

    def test_the_finaliser_is_what_raises(self):
        context, _should = self._exhaust_on_submit("raise")
        with pytest.raises(ExpectationsExhaustedError):
            pr.raise_pending_exhaustion(context)

    def test_it_is_raised_once(self):
        context, _should = self._exhaust_on_submit("raise")
        with pytest.raises(ExpectationsExhaustedError):
            pr.raise_pending_exhaustion(context)
        pr.raise_pending_exhaustion(context)

    def test_return_last_parks_nothing(self):
        context, should_continue = self._exhaust_on_submit("return_last")
        assert should_continue is True
        assert context.pending_exhaustion is None

    def test_fail_parks_nothing_to_raise(self):
        context, _should = self._exhaust_on_submit("fail")
        assert context.pending_exhaustion is None


class TestTheOriginalBatchFinaliserAlsoRaises:
    """The original-batch path has its own finaliser, and it is the common one.

    An action with `max_iterations: 1` exhausts on the first pass — no retry, no
    reprompt, no repair round — so this is the shortest route to `raise` and it
    goes through `BatchProcessingService._finalize_batch_output`, not the
    recovery finaliser the other tests drive.
    """

    def _service_and_context(self, policy: str):
        from agent_actions.llm.batch.services.processing import BatchProcessingService

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
            storage_backend=MagicMock(),
            workflow_name=ACTION,
        )
        context = _context(RecordingProvider(), _Backend(), _agent_config(on_exhausted=policy))
        context.service = service
        return service, context

    def _finalise(self, policy: str, pending):
        service, context = self._service_and_context(policy)
        context.pending_exhaustion = pending
        order: list[str] = []
        with (
            patch(
                "agent_actions.llm.batch.services.processing._finalize_batch_output_impl",
                side_effect=lambda *a, **k: order.append("write") or "/out.json",
            ),
            patch(
                "agent_actions.llm.batch.services.processing._cleanup_recovery_impl",
                side_effect=lambda *a, **k: order.append("cleanup"),
            ),
            patch.object(
                __import__(
                    "agent_actions.llm.batch.services.processing", fromlist=["RecoveryStateManager"]
                ).RecoveryStateManager,
                "delete",
            ),
        ):
            raised = None
            try:
                service._finalize_batch_output(
                    context=context,
                    identity=_identity(),
                    batch_results=[],
                    context_map={},
                )
            except ExpectationsExhaustedError as exc:
                raised = exc
        return order, raised

    def test_a_parked_error_is_raised(self):
        order, raised = self._finalise("raise", ExpectationsExhaustedError(ACTION, ["enough"], 1))
        assert raised is not None, (
            "the original-batch finaliser swallowed the halt, so raise degrades to return_last "
            "on the most common path"
        )

    def test_the_output_is_written_and_the_registry_tidied_first(self):
        order, _raised = self._finalise("raise", ExpectationsExhaustedError(ACTION, ["enough"], 1))
        assert order == ["write", "cleanup"], (
            "the file and the registry must both be settled before the run halts, or a re-run "
            "reprocesses and re-raises forever"
        )

    def test_nothing_parked_means_nothing_raised(self):
        order, raised = self._finalise("return_last", None)
        assert raised is None
        assert order == ["write", "cleanup"]


class TestAnUnrelatedFailureIsNotReportedAsAHalt:
    """A write failure must stay a write failure.

    The outer loop dispatches on the exception type: RuntimeError re-raises and
    halts, anything else is logged so the run can tombstone the records and move
    on. Converting a failed write into the halt takes the RuntimeError branch and
    skips that tombstoning, leaving records stuck DEFERRED where the retry
    command cannot find them.
    """

    def _finalise_with_a_broken_write(self, pending, error):
        context = _context(RecordingProvider(), _Backend(), _agent_config(on_exhausted="raise"))
        context.service = MagicMock()
        context.pending_exhaustion = pending
        with (
            patch(
                "agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager.delete"
            ),
            patch(
                "agent_actions.llm.batch.services.processing_recovery.finalize_batch_output",
                side_effect=error,
            ),
        ):
            try:
                pr._finalize_and_cleanup(
                    context=context,
                    identity=_identity(),
                    batch_results=[],
                    context_map={},
                )
            except BaseException as exc:  # noqa: BLE001 - the test is about which one
                return exc
        return None

    def test_a_failed_write_keeps_its_own_type(self):
        raised = self._finalise_with_a_broken_write(
            ExpectationsExhaustedError(ACTION, ["enough"], 1), OSError("No space left on device")
        )
        assert isinstance(raised, OSError), (
            f"the write failure was reported as {type(raised).__name__}; the outer loop then takes "
            "the RuntimeError branch and never tombstones the abandoned records"
        )
        assert "No space left on device" in str(raised), (
            "the operator has to see the disk error in the logged message, which uses str(exc)"
        )

    def test_a_keyboard_interrupt_is_not_replaced(self):
        raised = self._finalise_with_a_broken_write(
            ExpectationsExhaustedError(ACTION, ["enough"], 1), KeyboardInterrupt()
        )
        assert isinstance(raised, KeyboardInterrupt), (
            f"Ctrl-C during the write surfaced as {type(raised).__name__}"
        )

    def test_the_halt_still_fires_when_the_write_succeeds(self):
        context = _context(RecordingProvider(), _Backend(), _agent_config(on_exhausted="raise"))
        context.service = MagicMock()
        context.pending_exhaustion = ExpectationsExhaustedError(ACTION, ["enough"], 1)
        with (
            patch(
                "agent_actions.llm.batch.services.processing_recovery.RecoveryStateManager.delete"
            ),
            patch(
                "agent_actions.llm.batch.services.processing_recovery.finalize_batch_output",
                return_value="/out.json",
            ),
            patch("agent_actions.llm.batch.services.processing_recovery.cleanup_recovery"),
            pytest.raises(ExpectationsExhaustedError),
        ):
            pr._finalize_and_cleanup(
                context=context, identity=_identity(), batch_results=[], context_map={}
            )


class TestNothingSitsBetweenParkingAndRaising:
    """The halt is parked on the statement before the finaliser, not earlier.

    Anything that throws in between — rebuilding the retry metadata, converting
    the records — reaches the outer loop, which logs a non-RuntimeError and moves
    to the next file. A halt parked before that work is simply forgotten.
    """

    def _round_that_exhausts(self, retry_service_error):
        state = RecoveryState(
            phase=RecoveryPhase.REPAIR,
            repair_attempt=1,
            repair_max_attempts=1,
            repair_submitted_ids=["r1"],
            evaluation_strategy_name="expectations",
        )
        state.missing_ids = ["gone"]
        context = _context(
            RecordingProvider(), _Backend(), _agent_config(max_iterations=2, on_exhausted="raise")
        )
        context.service = MagicMock()
        context.service._retry_service.build_exhausted_recovery.side_effect = retry_service_error
        returned = [BatchResult(custom_id="r1", content=FAILING, success=True)]
        with patch.object(pr, "_finalize_and_cleanup", return_value="/out.json") as finalize:
            try:
                pr.handle_repair_recovery(
                    context,
                    _identity(),
                    state,
                    recovery_results=returned,
                    accumulated=[],
                    context_map=_context_map("r1"),
                )
            except BaseException as exc:  # noqa: BLE001 - the test is about which one
                return context, finalize, exc
        return context, finalize, None

    def test_a_throw_before_the_finaliser_leaves_no_forgotten_halt(self):
        context, finalize, raised = self._round_that_exhausts(ValueError("retry bookkeeping"))
        assert isinstance(raised, ValueError)
        assert finalize.call_count == 0, "the finaliser should not have been reached"
        assert context.pending_exhaustion is None, (
            "a halt was parked and then abandoned: the outer loop logs this ValueError and moves "
            "to the next file, so the decision to stop is silently lost"
        )

    def test_the_halt_is_parked_when_the_round_reaches_the_finaliser(self):
        context, finalize, raised = self._round_that_exhausts(None)
        assert raised is None
        assert finalize.call_count == 1
        assert isinstance(context.pending_exhaustion, ExpectationsExhaustedError)


class TestARecordIsNeverBothPooledAndInFlight:
    """A record sent back to the model has left the pool of finished work.

    The pool is what finalisation ships. A record an earlier reprompt round
    graduated sits there tagged with that round's strategy; when the repair loop
    re-evaluates it and it fails, it is resubmitted — and if its stale copy stays
    behind, the final merge ships the record twice, once repaired and verdicted
    and once with no verdict at all.
    """

    def _state_holding(self, *results: BatchResult) -> RecoveryState:
        from agent_actions.llm.batch.services.retry_serialization import serialize_results

        return RecoveryState(
            phase=RecoveryPhase.REPROMPT,
            graduated_results=serialize_results(list(results)),
            evaluation_strategy_name="validation",
        )

    def _submit_a_round_for(self, record_id: str):
        pooled = BatchResult(custom_id=record_id, content=FAILING, success=True)
        prior = self._state_holding(pooled)
        context = _context(
            RecordingProvider(), _Backend(), _agent_config(max_iterations=3, on_exhausted="fail")
        )
        saved: list[RecoveryState] = []
        with (
            patch(
                "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                return_value=_prepared(),
            ),
            patch.object(
                pr.RecoveryStateManager, "save", side_effect=lambda *a, **k: saved.append(a[-1])
            ),
            patch.object(pr, "register_recovery_batch"),
        ):
            pr.check_and_submit_repair(
                context,
                _identity(),
                batch_results=[BatchResult(custom_id=record_id, content=FAILING, success=True)],
                context_map=_context_map(record_id),
                recovery_state=prior,
            )
        assert saved, "the round did not persist state"
        return saved[-1]

    def test_a_resubmitted_record_leaves_the_pool(self):
        state = self._submit_a_round_for("r1")
        pooled_ids = [r.get("custom_id") for r in state.graduated_results]
        assert "r1" in state.repair_submitted_ids
        assert "r1" not in pooled_ids, (
            f"r1 is in flight and still pooled as finished ({pooled_ids}); finalisation merges the "
            "pool with the returning record and ships it twice, one copy unverdicted"
        )

    def test_the_pool_keeps_records_that_are_not_in_flight(self):
        from agent_actions.llm.batch.services.retry_serialization import serialize_results

        bystander = BatchResult(custom_id="untouched", content=PASSING, success=True)
        prior = RecoveryState(
            phase=RecoveryPhase.REPROMPT,
            graduated_results=serialize_results([bystander]),
            evaluation_strategy_name="validation",
        )
        context = _context(
            RecordingProvider(), _Backend(), _agent_config(max_iterations=3, on_exhausted="fail")
        )
        saved: list[RecoveryState] = []
        with (
            patch(
                "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                return_value=_prepared(),
            ),
            patch.object(
                pr.RecoveryStateManager, "save", side_effect=lambda *a, **k: saved.append(a[-1])
            ),
            patch.object(pr, "register_recovery_batch"),
        ):
            pr.check_and_submit_repair(
                context,
                _identity(),
                batch_results=[BatchResult(custom_id="r1", content=FAILING, success=True)],
                context_map=_context_map("r1"),
                recovery_state=prior,
            )
        pooled_ids = [r.get("custom_id") for r in saved[-1].graduated_results]
        assert "untouched" in pooled_ids, (
            "a record nobody resubmitted must stay in the pool or it never reaches the output"
        )

    def test_the_record_reaches_the_output_exactly_once(self):
        """The whole point: two rows for one record, one of them unverdicted."""
        from agent_actions.llm.batch.services.retry_serialization import serialize_results

        stale = BatchResult(custom_id="r1", content=dict(FAILING), success=True)
        state = RecoveryState(
            phase=RecoveryPhase.REPAIR,
            repair_attempt=1,
            repair_max_attempts=1,
            repair_submitted_ids=["r1"],
            graduated_results=serialize_results([stale]),
            evaluation_strategy_name="expectations",
        )
        context = _context(
            RecordingProvider(), _Backend(), _agent_config(max_iterations=2, on_exhausted="fail")
        )
        context.service = MagicMock()
        context.service._retry_service.build_exhausted_recovery.return_value = None
        returned = [BatchResult(custom_id="r1", content=dict(FAILING), success=True)]
        with patch.object(pr, "_finalize_and_cleanup", return_value="/out.json") as finalize:
            pr.handle_repair_recovery(
                context,
                _identity(),
                state,
                recovery_results=returned,
                accumulated=[],
                context_map=_context_map("r1"),
            )
        shipped = finalize.call_args.kwargs["batch_results"]
        ids = [r.custom_id for r in shipped]
        assert ids.count("r1") == 1, f"r1 shipped {ids.count('r1')} times: {ids}"
        assert all("expect" in (r.content or {}) for r in shipped), (
            "a shipped copy carries no verdict even though the action declares expect:"
        )

    def test_a_record_the_provider_returned_twice_does_not_stay_pooled(self):
        """One id, two rows back: one graduates into the pool, one goes back out.

        The pool add and the resubmission both happen in the same round, so the
        pool has to give the id up again when the round puts it in flight.
        """
        state = RecoveryState(
            phase=RecoveryPhase.REPAIR,
            repair_attempt=1,
            repair_max_attempts=3,
            repair_submitted_ids=["r1"],
            evaluation_strategy_name="expectations",
        )
        context = _context(
            RecordingProvider(), _Backend(), _agent_config(max_iterations=4, on_exhausted="fail")
        )
        returned = [
            BatchResult(custom_id="r1", content=dict(PASSING), success=True),
            BatchResult(custom_id="r1", content=dict(FAILING), success=True),
        ]
        saved: list[RecoveryState] = []
        with (
            patch(
                "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                return_value=_prepared(),
            ),
            patch.object(
                pr.RecoveryStateManager, "save", side_effect=lambda *a, **k: saved.append(a[-1])
            ),
            patch.object(pr, "register_recovery_batch"),
        ):
            pr.handle_repair_recovery(
                context,
                _identity(),
                state,
                recovery_results=returned,
                accumulated=[],
                context_map=_context_map("r1"),
            )
        assert saved, "the round did not persist state"
        final = saved[-1]
        pooled_ids = [r.get("custom_id") for r in final.graduated_results]
        assert "r1" in final.repair_submitted_ids
        assert "r1" not in pooled_ids, (
            f"r1 was pooled by the graduating copy and resubmitted by the failing one "
            f"({pooled_ids}); next round it ships twice"
        )


class TestAConfigErrorStopsTheRunRatherThanEmptyingIt:
    """A broken `expect:` block is not a per-file mishap.

    The loop tombstones the records and moves to the next file when one batch
    fails, which is right for a provider or convert failure. A configuration
    error fails identically for every file, so continuing lets the run finish
    reporting success while every affected file is missing from the output.
    """

    def _run_two_files(self, first_error):
        """One file fails, a second succeeds — so the run has something to report."""
        from agent_actions.llm.batch.services.processing import BatchProcessingService

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
            storage_backend=MagicMock(),
            workflow_name=ACTION,
        )
        jobs = {
            name: BatchJobEntry(
                batch_id=f"b-{name}",
                status="completed",
                timestamp="t",
                provider="p",
                file_name=name,
            )
            for name in ("bad.json", "good.json")
        }
        manager = MagicMock()
        manager.get_all_jobs.return_value = jobs
        manager.get_registry_stats.return_value = BatchRegistryStats(
            total_jobs=2, completed=2, failed=0, in_progress=0, cancelled=0
        )

        def per_file(*_a, file_name=None, **_k):
            if file_name == "bad.json":
                raise first_error
            return "/out/good.json"

        with (
            patch.object(service, "_registry_manager_factory", return_value=manager),
            patch.object(service, "_is_batch_ready_for_processing", return_value=True),
            patch.object(service, "_process_single_batch_file", side_effect=per_file),
            patch.object(service, "_fail_abandoned_records") as tombstone,
        ):
            try:
                written = service.process_all_batch_results(
                    output_directory="/out", agent_config=_agent_config(), action_name=ACTION
                )
            except BaseException as exc:  # noqa: BLE001 - the test is about which one
                return exc, None, tombstone
        return None, written, tombstone

    def test_an_action_wide_config_error_reaches_the_caller(self):
        from agent_actions.expectations.service import ExpectationConfigurationError

        raised, written, _t = self._run_two_files(
            ExpectationConfigurationError("names suite 'x' but no project root")
        )
        assert isinstance(raised, ExpectationConfigurationError), (
            f"the run swallowed an action-wide config error and reported success with {written}; "
            "every file carries that same action config, so they are all silently missing"
        )

    def test_a_per_record_config_error_only_costs_its_own_file(self):
        """A malformed lifecycle state is one record's problem, not the run's."""
        from agent_actions.errors import ConfigurationError

        raised, written, tombstone = self._run_two_files(
            ConfigurationError("Record is missing `_state`")
        )
        assert raised is None, (
            "one record with a bad lifecycle state aborted the whole run; every other file's "
            "results were already paid for and are now unprocessed"
        )
        assert written == ["/out/good.json"]
        assert tombstone.call_count == 1, "its records still need tombstoning for the retry command"

    def test_a_per_file_failure_still_only_costs_that_file(self):
        raised, written, tombstone = self._run_two_files(ValueError("one bad convert"))
        assert raised is None, "a single bad file must not take the whole run down"
        assert written == ["/out/good.json"]
        assert tombstone.call_count == 1, "its records still need tombstoning for the retry command"


class TestAResumeDoesNotShipThePreRepairResults:
    """The original batch is re-processed on every resume, with stale content.

    Its registry entry stays COMPLETED at the provider and is never retired, so
    each pass re-enters with the pre-repair results. When the rounds are spent,
    that pass finalises — and if it finalises from those results, every record
    the repair loop rewrote ships unrepaired and the pool is thrown away.
    """

    def _resume_with_a_spent_loop(self):
        from agent_actions.llm.batch.services.retry_serialization import serialize_results

        repaired = BatchResult(custom_id="r1", content=dict(PASSING), success=True)
        state = RecoveryState(
            phase=RecoveryPhase.REPAIR,
            repair_attempt=1,
            repair_max_attempts=1,
            repair_submitted_ids=[],
            graduated_results=serialize_results([repaired]),
            evaluation_strategy_name="expectations",
        )
        context = _context(
            RecordingProvider(), _Backend(), _agent_config(max_iterations=2, on_exhausted="fail")
        )
        # What the original batch produced, before any repair round ran.
        originals = [
            BatchResult(custom_id="r1", content=dict(FAILING), success=True),
            BatchResult(custom_id="never-repaired", content=dict(PASSING), success=True),
        ]
        with patch.object(pr.RecoveryStateManager, "load", return_value=state):
            pr.check_and_submit_repair(
                context,
                _identity(),
                batch_results=originals,
                context_map=_context_map("r1", "never-repaired"),
                recovery_state=None,
            )
        return originals

    def test_the_repaired_content_is_what_ships(self):
        shipped = {r.custom_id: r.content for r in self._resume_with_a_spent_loop()}
        assert shipped["r1"]["options"] == PASSING["options"], (
            f"r1 shipped its pre-repair content {shipped['r1']}; every round the loop paid for "
            "was discarded"
        )

    def test_a_record_the_loop_never_touched_still_ships(self):
        shipped = {r.custom_id: r.content for r in self._resume_with_a_spent_loop()}
        assert "never-repaired" in shipped, "a record outside the repair loop was dropped"

    def test_no_record_is_duplicated(self):
        ids = [r.custom_id for r in self._resume_with_a_spent_loop()]
        assert sorted(ids) == ["never-repaired", "r1"], f"duplicate or missing record: {ids}"


class TestEveryEntryPointActuallyConsultsRepair:
    """The loop is only useful if something reaches it.

    Each branch is one `if not check_and_submit_repair(...)` that can be deleted
    without any other test noticing — and with it gone `expect:` silently stops
    repairing and `on_exhausted: raise` degrades to return_last. These drive the
    callers, not the function, so an unwired branch fails here.
    """

    def _service(self):
        from agent_actions.llm.batch.services.processing import BatchProcessingService

        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=MagicMock(),
            storage_backend=None,
            workflow_name=ACTION,
        )
        service._action_indices = {ACTION: 0}
        service._dependency_configs = {}
        return service

    def _failing(self):
        return [BatchResult(custom_id="r1", content=dict(FAILING), success=True)]

    def _run_original_batch(self):
        """Drive the original-batch path end to end and report what happened."""
        service = self._service()
        provider = RecordingProvider()
        entry = BatchJobEntry(
            batch_id="b-1", status="completed", timestamp="t", provider="p", file_name="f.json"
        )
        service._client_resolver.get_for_batch_id.return_value = provider
        service._context_manager.load_batch_context_map.return_value = _context_map("r1")
        with (
            patch(
                "agent_actions.llm.batch.services.processing.retrieve_and_reconcile",
                return_value=self._failing(),
            ),
            patch.object(service, "_check_and_submit_reprompt", return_value=True),
            patch.object(service, "_finalize_batch_output", return_value="/out.json") as finalize,
            patch(
                "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                return_value=_prepared(),
            ),
            patch.object(pr.RecoveryStateManager, "save"),
            patch.object(pr.RecoveryStateManager, "load", return_value=None),
            patch.object(pr, "register_recovery_batch"),
        ):
            returned = service._process_original_batch(
                batch_id="b-1",
                file_name="f.json",
                entry=entry,
                output_directory="/out",
                agent_config=_agent_config(max_iterations=3, on_exhausted="fail"),
                manager=MagicMock(),
                action_name=ACTION,
            )
        return returned, provider.submitted, finalize

    def test_the_original_batch_path_submits_a_repair_round(self):
        _returned, submitted, _f = self._run_original_batch()
        assert submitted, (
            "a failing record went straight to the output: the original-batch path never "
            "consulted the repair loop, so expect: does not repair at all here"
        )

    def test_it_defers_instead_of_writing_the_file(self):
        returned, _submitted, finalize = self._run_original_batch()
        assert returned is None, "the pass wrote the file while a repair round was in flight"
        assert finalize.call_count == 0

    def _run_recovery(self, handler, state, **kw):
        """Drive one recovery handler and report whether it reached repair."""
        provider = RecordingProvider()
        context = _context(
            provider, _Backend(), _agent_config(max_iterations=3, on_exhausted="fail")
        )
        context.service = MagicMock()
        context.service._resolve_action_name.return_value = ACTION
        context.service._action_indices = {ACTION: 0}
        context.service._dependency_configs = {}
        context.service._storage_backend = None
        context.service._retry_service.build_exhausted_recovery.return_value = None
        context.service._retry_service.process_retry_results.return_value = (
            self._failing(),
            set(),
            {},
            None,
        )
        with (
            patch(
                "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                return_value=_prepared(),
            ),
            patch.object(pr.RecoveryStateManager, "save"),
            patch.object(pr.RecoveryStateManager, "load", return_value=state),
            patch.object(pr, "register_recovery_batch"),
            patch.object(pr, "_finalize_and_cleanup", return_value="/out.json") as finalize,
            patch.object(pr, "check_and_submit_reprompt", return_value=True),
            patch.object(pr, "cleanup_recovery"),
        ):
            returned = handler(
                context,
                _identity(),
                state=state,
                recovery_results=self._failing(),
                accumulated=self._failing(),
                context_map=_context_map("r1"),
                **kw,
            )
        return returned, provider.submitted, finalize

    def test_the_retry_recovery_path_submits_a_repair_round(self):
        state = RecoveryState(phase=RecoveryPhase.RETRY, evaluation_strategy_name="validation")
        returned, submitted, finalize = self._run_recovery(pr.handle_retry_recovery, state)
        assert submitted, "the retry recovery path never consulted the repair loop"
        assert returned is None and finalize.call_count == 0, "it wrote the file anyway"

    def test_the_reprompt_recovery_path_submits_a_repair_round(self):
        """Reprompt has two exits into repair — this drives the one with no loop."""
        state = RecoveryState(phase=RecoveryPhase.REPROMPT, evaluation_strategy_name="validation")
        provider = RecordingProvider()
        context = _context(
            provider, _Backend(), _agent_config(max_iterations=3, on_exhausted="fail")
        )
        context.service = MagicMock()
        context.service._resolve_action_name.return_value = ACTION
        context.service._action_indices = {ACTION: 0}
        context.service._dependency_configs = {}
        context.service._storage_backend = None
        with (
            patch(
                "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                return_value=_prepared(),
            ),
            patch.object(pr.RecoveryStateManager, "save"),
            patch.object(pr.RecoveryStateManager, "load", return_value=state),
            patch.object(pr, "register_recovery_batch"),
            patch.object(pr, "_finalize_and_cleanup", return_value="/out.json") as finalize,
            patch(
                "agent_actions.llm.batch.services.reprompt_ops.build_evaluation_loop",
                return_value=None,
            ),
        ):
            returned = pr.handle_reprompt_recovery(
                context,
                _identity(),
                state=state,
                recovery_results=self._failing(),
                accumulated=self._failing(),
                context_map=_context_map("r1"),
            )
        assert provider.submitted, "the reprompt recovery path never consulted the repair loop"
        assert returned is None and finalize.call_count == 0, "it wrote the file anyway"


class TestEveryExitAppliesTheSamePolicy:
    """Which pass noticed the loop was over must not change what happens.

    `check_and_submit_repair` has three ways to stop: the rounds are spent,
    nothing can be repaired, or the submission failed. Only the first applied
    `on_exhausted`, so a run halted or tombstoned depending on which one it hit
    — while `handle_repair_recovery` applied the policy on the same fall-through.
    """

    def _stop_via(self, exit_kind: str, policy: str):
        context = _context(
            RecordingProvider(), _Backend(), _agent_config(max_iterations=3, on_exhausted=policy)
        )
        if exit_kind == "nothing_repairable":
            results = [
                BatchResult(custom_id="r1", content=None, success=False, error="429 rate limited")
            ]
            patches = []
        else:
            # Nothing prepares: the record has no context_map row to rebuild its
            # prompt from, so the submission comes back empty.
            results = [BatchResult(custom_id="r1", content=dict(FAILING), success=True)]
            patches = [
                patch(
                    "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                    return_value=_prepared(),
                )
            ]
        context_map = {} if exit_kind == "submit_failed" else _context_map("r1")
        with ExitStack() as stack:
            for patcher in patches:
                stack.enter_context(patcher)
            should_continue = pr.check_and_submit_repair(
                context,
                _identity(),
                batch_results=results,
                context_map=context_map,
                recovery_state=None,
            )
        return context, should_continue, results

    def test_nothing_repairable_still_halts_under_raise(self):
        context, should_continue, _r = self._stop_via("nothing_repairable", "raise")
        assert should_continue is True
        assert context.pending_exhaustion is not None, (
            "the loop gave up but on_exhausted: raise did nothing, purely because this exit was "
            "taken instead of the spent-rounds one"
        )

    def test_a_failed_submission_still_halts_under_raise(self):
        context, should_continue, _r = self._stop_via("submit_failed", "raise")
        assert should_continue is True
        assert context.pending_exhaustion is not None

    def test_fail_marks_the_record_at_every_exit(self):
        for exit_kind in ("nothing_repairable", "submit_failed"):
            _ctx, _sc, results = self._stop_via(exit_kind, "fail")
            assert results[0].success is False, f"{exit_kind} left the record looking successful"

    def test_a_provider_failure_keeps_its_cause_at_these_exits(self):
        _ctx, _sc, results = self._stop_via("nothing_repairable", "fail")
        assert "429 rate limited" in (results[0].error or "")

    def test_return_last_parks_nothing_at_every_exit(self):
        for exit_kind in ("nothing_repairable", "submit_failed"):
            context, _sc, _r = self._stop_via(exit_kind, "return_last")
            assert context.pending_exhaustion is None, exit_kind
