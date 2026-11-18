"""A batch run driven pass by pass, with a provider that answers judge requests.

Shared by the judge-batch tests (1814). Every pass goes through the functions a
collect pass calls — `check_and_submit_repair` once the main batch is back, and
`process_recovery_batch` for each recovery batch — and the provider records what
it was sent and which batch ids were read. Any online judge call is recorded too.
"""

import json
import re
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.llm.batch.core.batch_models import BatchIdentity, BatchJobEntry
from agent_actions.llm.batch.infrastructure.recovery_state import RecoveryState
from agent_actions.llm.batch.services import processing_recovery as pr
from agent_actions.llm.providers.agac.batch_client import AgacBatchClient
from agent_actions.llm.providers.batch_base import BatchResult

from .recording_provider import RecordingProvider
from .test_repair_deferral import ACTION, FILE, _agent_config, _Backend, _context_map, _prepared

INVOKE = "agent_actions.llm.realtime.services.invocation.ClientInvocationService.invoke_client"
ERRORED = object()


def judged_config(expectations, **expect: Any) -> dict[str, Any]:
    config = _agent_config(**expect)
    config["model_vendor"] = "openai"
    config["expect"]["expectations"] = expectations
    return config


def judge_rule(rule: str = "Every option is on topic.", votes: int = 1, **params: Any):
    return {
        "id": "on_topic",
        "type": "llm_judge",
        "field": "options",
        "params": {"rule": rule, "votes": votes, **params},
    }


def value_in(prompt: str) -> Any:
    """The value a judge prompt puts under test."""
    match = re.search(r"## Value under test\n(.*)\n\nRespond with ONLY", prompt, re.S)
    assert match, prompt
    return json.loads(match.group(1))


def verdict(passed: bool, reason: str = "because") -> str:
    return json.dumps({"passed": passed, "reason": reason})


class Registry:
    """The registry calls the recovery steps make, kept in a dict."""

    def __init__(self) -> None:
        self.jobs: dict[str, BatchJobEntry] = {}

    def batch_id_at(self, name):
        entry = self.jobs.get(name)
        return entry.batch_id if entry else None

    def save_batch_job(self, name, entry):
        self.jobs[name] = entry

    def remove_batch_job(self, name):
        return self.jobs.pop(name, None) is not None

    def get_all_jobs(self):
        return dict(self.jobs)

    def update_status(self, batch_id, status):
        return True

    def mark_collected(self, name, when=None):
        return True


class JudgingProvider(RecordingProvider):
    """Answers each judge request with `reply(prompt, vote)`, and a repair round with `repair`.

    `reply` returns the reply text, or ERRORED for a request the provider failed.
    """

    def __init__(
        self,
        reply: Callable[[str, int], Any],
        repair: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__()
        self.reply = reply
        self.repair = repair
        self.batches: list[tuple[str, int]] = []
        self.read: list[str] = []
        self._tasks: dict[str, list[dict[str, Any]]] = {}

    def submit_batch(self, tasks, batch_name, output_directory):
        batch_id = f"batch-{len(self.batches) + 1}"
        self.batches.append((batch_name, len(tasks)))
        self._tasks[batch_id] = tasks
        self.submitted = tasks
        return batch_id, "submitted"

    def retrieve_results(self, batch_id, output_directory):
        self.read.append(batch_id)
        return [self._answer(task) for task in self._tasks[batch_id]]

    def _answer(self, task) -> BatchResult:
        custom_id = task["custom_id"]
        if not custom_id.startswith("j_"):
            assert self.repair is not None, "a repair round went out with nothing to answer it"
            return BatchResult(custom_id=custom_id, content=self.repair(custom_id), success=True)
        prompt = task["body"]["messages"][0]["content"]
        text = self.reply(prompt, int(custom_id.rsplit("_", 1)[1]))
        if text is ERRORED:
            line = {"custom_id": custom_id, "error": {"message": "rate limited"}}
        else:
            line = {
                "custom_id": custom_id,
                "response": {"body": {"choices": [{"message": {"content": text}}]}},
            }
        # Read as a real provider reads its result file, JSON parse and all.
        return AgacBatchClient.parse_provider_response(AgacBatchClient(), line)


class Run:
    """One file's batch run: the main batch back, then each recovery batch as it returns."""

    def __init__(self, config: dict[str, Any], provider: JudgingProvider) -> None:
        self.config = config
        self.provider = provider
        self.backend = _Backend()
        self.registry = Registry()
        self.online: list[Any] = []
        self.finalized: list[BatchResult] | None = None
        self.written: dict[str, Any] = {}
        self.context_map: dict[str, Any] = {}

    def _patches(self, stack: ExitStack) -> None:
        def online_call(**kwargs):
            self.online.append(kwargs)
            return [{"raw_response": verdict(True, "online")}]

        def finalize(context, identity, batch_results, context_map, exhausted_recovery=None):
            self.finalized = batch_results
            self.written = _write(context.agent_config, batch_results, context_map)
            return "/out.json"

        stack.enter_context(
            patch(
                "agent_actions.processing.task_preparer.TaskPreparer.prepare",
                return_value=_prepared(),
            )
        )
        stack.enter_context(patch(INVOKE, side_effect=online_call))
        stack.enter_context(patch.object(pr, "_finalize_and_cleanup", side_effect=finalize))

    def _service(self):
        service = MagicMock()
        service._storage_backend = self.backend
        service._action_indices = {ACTION: 0}
        service._dependency_configs = {}
        service._resolve_action_name.return_value = ACTION
        service._apply_workflow_session_id.side_effect = lambda config, entry: config
        service._client_resolver.get_for_batch_id.return_value = self.provider
        service._context_manager.load_batch_context_map.return_value = self.context_map
        service._retry_service.build_exhausted_recovery.return_value = None
        return service

    def main_batch_returns(self, results: list[BatchResult]) -> bool:
        """The pass over the main batch; True when it would write the file."""
        from agent_actions.llm.batch.core.batch_models import RecoveryContext

        # A test that prepared its records for real has already put their rows here.
        for custom_id, row in _context_map(*[r.custom_id for r in results]).items():
            self.context_map.setdefault(custom_id, row)
        context = RecoveryContext(
            service=self._service(),
            manager=self.registry,
            provider=self.provider,
            agent_config=self.config,
            output_directory="/tmp/test",
            action_name=ACTION,
            start_time=0.0,
        )
        identity = BatchIdentity(
            batch_id="b-main",
            file_name=FILE,
            entry=BatchJobEntry(
                batch_id="b-main", status="completed", timestamp="t", provider="openai"
            ),
        )
        with ExitStack() as stack:
            self._patches(stack)
            should_continue = pr.check_and_submit_repair(
                context, identity, batch_results=results, context_map=self.context_map
            )
        self.config = context.agent_config
        return should_continue

    def live_entry(self) -> BatchJobEntry | None:
        (entry,) = self.registry.jobs.values() or [None]
        return entry

    def recovery_batch_returns(self) -> str | None:
        """The pass over the live recovery batch; the output path when it wrote the file."""
        entry = self.live_entry()
        assert entry is not None, "no recovery batch is out"
        with ExitStack() as stack:
            self._patches(stack)
            return pr.process_recovery_batch(
                self._service(),
                entry.batch_id,
                entry.file_name,
                entry,
                "/tmp/test",
                self.config,
                self.registry,
                action_name=ACTION,
            )

    def state(self) -> RecoveryState | None:
        raw = self.backend.meta.get(f"recovery_state:{ACTION}:{FILE}")
        return RecoveryState(**json.loads(raw)) if raw else None

    def verdicts(self) -> dict[str, dict[str, Any]]:
        """Each record's verdict as the result writer ships it."""
        assert self.finalized is not None, "the file was never written"
        return self.written


def _write(agent_config, batch_results, context_map) -> dict[str, Any]:
    """Run the real result writer, and read each record's verdict off its output row."""
    from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy

    written = {}
    for result in BatchResultStrategy().process(
        batch_results, context_map=context_map, agent_config=agent_config
    ):
        for row in result.data or []:
            written[row["target_id"]] = row["content"][ACTION].get("expect")
    return written


def answers(values: dict[str, Any]) -> list[BatchResult]:
    """Main-batch results: each record's `options` set to its value."""
    return [
        BatchResult(custom_id=cid, content={"options": v}, success=True)
        for cid, v in values.items()
    ]
