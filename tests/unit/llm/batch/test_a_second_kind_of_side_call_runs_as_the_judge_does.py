"""A second kind of side call runs by the action's run mode, with no change to the framework.

`llm_judge` was the first feature to call the model beside an action's main request.
Here a requester the framework has never heard of, registered through the hook the
judge registers through, asks the model to repeat each record's answer. Online its
call runs at once. In a batch run its calls are held, go out as `<file>_echo_<n>`,
and come back to it under their keys, through the round that carries the judge's.

One side batch carries one kind. A batch is prepared from one config and sent to
one model, and its name is what a waiting record is reported against, so two kinds
pending for one step go out in turn, each as its own batch, the way two judge
models already do.
"""

import json
from typing import Any
from unittest.mock import patch

import pytest

from agent_actions.llm.batch.core.batch_constants import BatchStatus, RecoveryType
from agent_actions.llm.batch.infrastructure.recovery_state import (
    RecoveryState,
    RecoveryStateManager,
)
from agent_actions.llm.batch.services.side_batch import (
    SideStep,
    register_side_requester,
    side_requester,
    unregister_side_requester,
)
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.llm.side_calls import (
    HeldSideCalls,
    OnlineSideCalls,
    SideCall,
    SideCallExecutor,
    SideReplies,
)

from .judge_batch_world import (
    ERRORED,
    INVOKE,
    JudgingProvider,
    Run,
    answers,
    judge_rule,
    judged_config,
    verdict,
)
from .test_repair_deferral import ACTION, _agent_config, _Backend

VALUES = {"r1": ["a"], "r2": ["b"]}
COPIES = 2


class Echo:
    """A requester of side calls: has the model repeat a value, `COPIES` times over.

    `ask` is all it does with an executor, online or held. The rest is what a batch
    run asks of any requester.
    """

    kind = "echo"

    def __init__(self) -> None:
        self.charged: list[list[str]] = []
        self.heard: dict[str, list[Any]] = {}

    def ask(self, calls: SideCallExecutor, key: str, value: Any) -> list[Any] | None:
        """What the model repeated; None while the call waits on a batch."""
        prompt = f"Repeat after me: {json.dumps(value)}"
        replies = calls.run(SideCall(self.kind, key, prompt, copies=COPIES))
        return None if replies is None else self.settle(key, replies)

    def collect(self, step: SideStep) -> dict[str, SideCall]:
        held = HeldSideCalls()
        heard = step.settled(self.kind)
        for result in step.results:
            if str(result.custom_id) not in heard:
                self.ask(held, str(result.custom_id), result.content["options"])
        return held.pending

    def sent(self, step: SideStep, calls: dict[str, SideCall]) -> None:
        self.charged.append(sorted(calls))

    def settle(self, key: str, replies: SideReplies) -> list[Any]:
        heard = (
            [f"unheard: {replies.error}"] if replies.error is not None else list(replies.replies)
        )
        self.heard[key] = heard
        return heard


@pytest.fixture
def echo():
    requester = Echo()
    register_side_requester(requester)
    yield requester
    unregister_side_requester(requester.kind)


class EchoingProvider(JudgingProvider):
    """Answers an echo request with what it was asked to repeat, and the rest as its base does."""

    def __init__(self, heard=lambda prompt: f"heard {prompt.split(': ', 1)[1]}") -> None:
        super().__init__(lambda _prompt, _vote: verdict(True, "fine"))
        self.heard = heard

    def _answer(self, task) -> BatchResult:
        custom_id = task["custom_id"]
        if not custom_id.startswith("e_"):
            return super()._answer(task)
        text = self.heard(task["body"]["messages"][0]["content"])
        if text is ERRORED:
            line = {"custom_id": custom_id, "error": {"message": "rate limited"}}
        else:
            line = {
                "custom_id": custom_id,
                "response": {"body": {"choices": [{"message": {"content": text}}]}},
            }
        return AgacBatchClient.parse_provider_response(AgacBatchClient(), line)


def _plain_config() -> dict[str, Any]:
    """A batch action with no `expect:` block: nothing in it asks for a judge."""
    config = _agent_config()
    del config["expect"]
    config["model_vendor"] = "openai"
    return config


HEARD = {
    "r1": ['heard ["a"]'] * COPIES,
    "r2": ['heard ["b"]'] * COPIES,
}


class TestOnline:
    def test_its_call_runs_at_once_on_the_online_executor(self):
        sent = []

        def online_call(**kwargs):
            sent.append(kwargs)
            return [{"raw_response": "heard it"}]

        with patch(INVOKE, side_effect=online_call):
            heard = Echo().ask(OnlineSideCalls(_plain_config(), ACTION), "r1", ["a"])

        assert heard == ["heard it"] * COPIES
        assert len(sent) == COPIES
        for request in sent:
            assert request["prompt_config"] == 'Repeat after me: ["a"]'
            assert request["action_name"] == f"{ACTION}_echo"
            assert request["agent_config"]["json_mode"] is False
            assert request["schema"] is None

    def test_a_copy_that_fails_fails_the_call(self):
        with (
            patch(INVOKE, side_effect=ConnectionError("provider unreachable")),
            pytest.raises(ConnectionError),
        ):
            Echo().ask(OnlineSideCalls(_plain_config(), ACTION), "r1", ["a"])


class TestInABatchRun:
    def test_its_calls_go_out_as_a_batch_named_for_its_kind(self, echo):
        provider = EchoingProvider()
        run = Run(_plain_config(), provider)

        assert run.main_batch_returns(answers(VALUES)) is False, "the step did not defer"

        assert provider.batches == [("f.json_echo_1", len(VALUES) * COPIES)]
        assert run.online == [], "a side call of a batch action was made online"
        entry = run.live_entry()
        assert (entry.file_name, entry.recovery_type, entry.side_kind) == (
            "f.json_echo_1",
            RecoveryType.SIDE,
            "echo",
        )
        assert echo.charged == [["r1", "r2"]]

    def test_its_batch_holds_no_more_requests_than_the_provider_takes(self, echo):
        provider = EchoingProvider()
        provider.max_batch_requests = COPIES
        run = Run(_plain_config(), provider)

        assert run.main_batch_returns(answers(VALUES)) is False
        out = None
        for _pass in range(len(VALUES) + 1):
            out = run.recovery_batch_returns()
            if out is not None:
                break

        assert out == "/out.json"
        assert provider.batches == [("f.json_echo_1", COPIES), ("f.json_echo_2", COPIES)]
        assert echo.charged == [["r1"], ["r2"]]
        assert echo.heard == HEARD

    @pytest.mark.parametrize("status", [BatchStatus.IN_PROGRESS, BatchStatus.COMPLETED])
    def test_a_resume_while_its_batch_is_unread_sends_nothing_new(self, echo, status):
        provider = EchoingProvider()
        run = Run(_plain_config(), provider)
        run.main_batch_returns(answers(VALUES))
        provider.status = status

        assert run.main_batch_returns(answers(VALUES)) is False, "the pass did not wait for it"
        assert provider.batches == [("f.json_echo_1", len(VALUES) * COPIES)]

    def test_the_returned_batch_is_read_by_id_and_its_replies_reach_the_requester(self, echo):
        provider = EchoingProvider()
        run = Run(_plain_config(), provider)
        run.main_batch_returns(answers(VALUES))
        registered = run.live_entry().batch_id

        assert run.recovery_batch_returns() == "/out.json"

        assert provider.read == [registered]
        assert provider.batches == [("f.json_echo_1", len(VALUES) * COPIES)], "sent again"
        assert run.online == []
        assert echo.heard == HEARD
        assert sorted(r.custom_id for r in run.finalized) == ["r1", "r2"]

    def test_a_batch_the_provider_failed_fails_its_calls_closed(self, echo):
        provider = EchoingProvider()
        run = Run(_plain_config(), provider)
        run.main_batch_returns(answers(VALUES))
        run.live_entry().status = BatchStatus.FAILED

        assert run.recovery_batch_returns() == "/out.json"

        assert provider.read == [], "a failed batch has nothing to read"
        assert provider.batches == [("f.json_echo_1", len(VALUES) * COPIES)]
        assert echo.heard == {
            key: ["unheard: the echo batch returned no reply for this request"] for key in VALUES
        }

    def test_one_request_the_provider_failed_fails_only_its_call(self, echo):
        provider = EchoingProvider(heard=lambda prompt: ERRORED if '"a"' in prompt else "heard it")
        run = Run(_plain_config(), provider)
        run.main_batch_returns(answers(VALUES))

        run.recovery_batch_returns()

        heard = echo.heard
        assert heard["r2"] == ["heard it"] * COPIES
        assert heard["r1"][0].startswith("unheard: ") and "rate limited" in heard["r1"][0]

    def test_a_failed_batch_of_its_kind_still_holds_its_main_batch(self):
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
            "f.json_echo_1": entry(
                "f.json_echo_1",
                BatchStatus.FAILED,
                parent_file_name="f.json",
                recovery_type="side",
                side_kind="echo",
                recovery_attempt=1,
            ),
        }
        assert _superseded_entries(jobs) == {"f.json"}


class TestBesideTheJudge:
    """Both kinds have calls to make over one step: one batch each, the judge's first."""

    @pytest.mark.parametrize("repair", ["none", "auto"])
    def test_each_kind_goes_out_as_its_own_batch_and_gets_its_own_replies(self, echo, repair):
        provider = EchoingProvider()
        run = Run(judged_config([judge_rule(votes=3)], repair=repair), provider)

        assert run.main_batch_returns(answers(VALUES)) is False
        assert provider.batches == [("f.json_judge_1", len(VALUES) * 3)]
        assert run.live_entry().side_kind == "judge"

        assert run.recovery_batch_returns() is None, "the echo calls were never sent"
        assert provider.batches == [
            ("f.json_judge_1", len(VALUES) * 3),
            ("f.json_echo_1", len(VALUES) * COPIES),
        ]
        assert run.live_entry().side_kind == "echo"

        assert run.recovery_batch_returns() == "/out.json"
        assert len(provider.batches) == 2, "a third batch went out"
        assert provider.read == ["batch-1", "batch-2"]
        assert run.online == []
        assert echo.heard == HEARD
        assert all(v["overall_pass"] for v in run.verdicts().values())
        assert run.state().side_attempts == {"judge": 1, "echo": 1}

    def test_a_request_of_one_kind_is_not_read_as_the_others(self, echo):
        """Each batch holds only its kind's requests, so a reply cannot cross over."""
        provider = EchoingProvider()
        run = Run(judged_config([judge_rule()], repair="none"), provider)
        run.main_batch_returns(answers(VALUES))
        judge_ids = {task["custom_id"] for task in provider.submitted}
        run.recovery_batch_returns()
        echo_ids = {task["custom_id"] for task in provider.submitted}

        assert all(i.startswith("j_") for i in judge_ids)
        assert all(i.startswith("e_") for i in echo_ids)


class TestTheHook:
    def test_the_judge_is_registered_through_it(self):
        from agent_actions.llm.batch.services.judge_ops import JudgeRequester

        assert isinstance(side_requester("judge"), JudgeRequester)

    @pytest.mark.parametrize("name", ["retry", "repair", "side", "Echo", "two words", ""])
    def test_a_kind_that_cannot_name_a_batch_is_refused(self, name):
        requester = Echo()
        requester.kind = name

        with pytest.raises(ValueError, match="cannot name a batch"):
            register_side_requester(requester)

    def test_a_returned_batch_of_an_unregistered_kind_is_not_read_as_another(self):
        with pytest.raises(ValueError, match="nothing is registered"):
            side_requester("echo")

    def test_the_state_of_a_round_survives_the_store(self):
        backend = _Backend()
        state = RecoveryState(
            side_attempts={"judge": 2, "echo": 1},
            side_kind="echo",
            side_requests={"e_0123456789abcdef_0": "r1"},
            side_results={"judge": {"k": [True, "fine"]}, "echo": {"r1": ["heard"]}},
            side_waiting=[{"custom_id": "r1", "content": {"options": ["a"]}, "success": True}],
            side_resumes="evaluate",
        )

        RecoveryStateManager.save(backend, ACTION, "f.json", state)

        assert RecoveryStateManager.load(backend, ACTION, "f.json") == state


def test_what_waits_on_a_side_batch_is_reported_by_its_kind(echo, caplog):
    """The report names the round a record waits on: a judge batch, or an echo batch."""
    import logging

    from agent_actions.llm.batch.infrastructure.recovery_state import AwaitingRecovery
    from agent_actions.workflow.managers.batch import BatchLifecycleManager

    waiting = {
        "g1": AwaitingRecovery(RecoveryType.SIDE, 1, 1, None, "judge"),
        "g2": AwaitingRecovery(RecoveryType.SIDE, 2, 2, None, "echo"),
    }
    manager = BatchLifecycleManager.__new__(BatchLifecycleManager)
    manager.storage_backend = object()
    with (
        patch(
            "agent_actions.llm.batch.infrastructure.recovery_state.records_awaiting_recovery",
            return_value=waiting,
        ),
        caplog.at_level(logging.INFO),
    ):
        rest = manager._report_records_awaiting_recovery(ACTION, {"g1", "g2", "g3"})

    assert rest == {"g3"}
    assert "1 record(s) wait on judge batch 1: ['g1']" in caplog.text
    assert "1 record(s) wait on echo batch 2: ['g2']" in caplog.text
