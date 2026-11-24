"""
Mock Batch Client for Testing.

Provides a simple mock batch client for testing batch processing
without hitting real APIs. Uses schema-based fake data generation.

A batch completes at its first status check, unless the sandbox scenario's ``batch``
block delays it.
"""

import glob
import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_actions.config import sandbox
from agent_actions.config.paths import PathManagerError
from agent_actions.llm.providers.agac import faults
from agent_actions.llm.providers.agac.client import AgacClient
from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator
from agent_actions.llm.providers.batch_base import (
    BaseBatchClient,
    BatchTask,
)
from agent_actions.llm.providers.mixins import OpenAICompatibleResponseMixin
from agent_actions.utils.constants import RECORD_GUID_KEY

logger = logging.getLogger(__name__)

# Longer than any atomic write takes to create its temp file and rename it,
# short enough that a record abandoned by a killed process is reclaimed by
# the next run rather than the one after it.
_ABANDONED_WRITE_SECONDS = 60.0
# How long a record's submissions are counted after its last one.
_ATTEMPTS_KEPT_SECONDS = 7 * 24 * 3600.0


def _task_action(task: dict[str, Any]) -> str:
    """The action a task was prepared for, from the rules it carries."""
    spec = task.get("contract")
    return str(spec.get("action") or "action") if isinstance(spec, dict) else "action"


def _shared_contracts(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Each distinct rule set the tasks carry, by key; each task then holds only its key."""
    contracts: dict[str, Any] = {}
    for task in tasks:
        spec = task.get("contract")
        if isinstance(spec, dict):
            text = json.dumps(spec, sort_keys=True, default=str)
            key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            contracts[key] = spec
            task["contract"] = key
    return contracts


@dataclass
class MockBatchState:
    """Tracks state of a mock batch job."""

    batch_id: str
    tasks: list[BatchTask] = field(default_factory=list)
    status: str = "in_progress"
    poll_count: int = 0
    polls_until_complete: int = 0
    created_at: float = field(default_factory=time.time)
    complete_after_seconds: float = 0.0


class AgacBatchClient(OpenAICompatibleResponseMixin, BaseBatchClient):
    """Mock batch client for testing batch processing without real APIs.

    A batch completes at its first status check. Under ``agac run --sandbox`` the
    scenario's ``batch`` block can hold it for ``polls_until_complete`` status checks or
    ``complete_after_seconds``, drop results, or fail the batch of an action it names.
    """

    _vendor_label = faults.VENDOR

    # In-process cache. The durable copy is on disk, because a batch workflow
    # spans two runs by design: submitting pauses and asks to be run again, and
    # that is a new process with an empty cache.
    _batches: dict[str, MockBatchState] = {}
    _tasks_by_batch: dict[str, list[dict[str, Any]]] = {}
    # The rules a batch's tasks name by key, kept once for the batch.
    _contracts_by_batch: dict[str, dict[str, Any]] = {}
    # Two actions' batches are submitted at once in a parallel run, and both count in one file.
    _attempts_lock = threading.Lock()

    def __init__(
        self,
        polls_until_complete: int | None = None,
        complete_after_seconds: float | None = None,
        **kwargs,
    ):
        followed = sandbox.scenario()
        timing = followed.batch if followed is not None else None
        self.polls_until_complete: int = (
            polls_until_complete
            if polls_until_complete is not None
            else (timing.polls_until_complete if timing else 0)
        )
        self.complete_after_seconds: float = (
            complete_after_seconds
            if complete_after_seconds is not None
            else (timing.complete_after_seconds if timing else 0.0)
        )
        logger.info(
            "AgacBatchClient initialized: polls=%d, complete_after=%.1fs",
            self.polls_until_complete,
            self.complete_after_seconds,
        )

    # ========== Required abstract method implementations ==========

    def _get_default_model(self) -> str:
        """Return default model name."""
        return "agac-model"

    def prepare_tasks(
        self, data: list[dict[str, Any]], agent_config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Each task also carries the action's rules, which the answer must meet as online."""
        from agent_actions.llm.providers.agac.contract import Contract, observed_refs, rules_for

        # Read before the base class takes keys off each row.
        guids = {
            str(row.get("target_id", row.get("id", ""))): row.get(RECORD_GUID_KEY) for row in data
        }
        tasks = super().prepare_tasks(data, agent_config)
        action = AgacClient._action_name(agent_config)
        spec = Contract(
            action=action,
            rules=rules_for(agent_config, action),
            context={},
            observe=observed_refs(agent_config),
            workflow_session_id=agent_config.get("workflow_session_id"),
        ).to_task()
        for task in tasks:
            task["contract"] = spec
            guid = guids.get(str(task.get("custom_id")))
            if isinstance(guid, str) and guid:
                task["record"] = guid
        return tasks

    def format_task_for_provider(
        self, batch_task: BatchTask, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Format task for mock processing."""
        return {
            "custom_id": batch_task.custom_id,
            "prompt": batch_task.prompt,
            "user_content": batch_task.user_content,
            # Only what the action sets, as a provider's request line holds it.
            "model_config": {k: v for k, v in batch_task.model_config.items() if v is not None},
            "schema": schema,
        }

    @staticmethod
    def _state_dir() -> Path:
        """Where a submitted batch is recorded, derivable without any argument.

        The resume path is given a batch id and nothing else, so the location
        cannot depend on the output directory the submit happened to use. From
        the project root the CLI resolved, not the working directory: `agac` runs
        from a subdirectory without chdir. Not under `agent_io/`, which marks a
        workflow to the docs scanner.

        Resolved, never created — only a submit creates it.
        """
        from agent_actions.utils.path_utils import get_path_manager

        return get_path_manager().get_project_root() / ".agac" / "batch_state"

    @classmethod
    def _write_state(
        cls,
        state: MockBatchState,
        tasks: list[dict[str, Any]],
        contracts: dict[str, Any] | None = None,
    ) -> None:
        """Record a submitted batch where the next run can find it.

        Written atomically: a truncated file reads back as no batch at all, which
        is the failure this exists to prevent, arrived at silently.
        """
        from agent_actions.utils.atomic_write import atomic_json_write
        from agent_actions.utils.path_utils import ensure_directory_exists

        state_dir = cls._state_dir()
        ensure_directory_exists(state_dir)
        atomic_json_write(
            state_dir / f"{state.batch_id}.json",
            # Reconstructible by definition, and rewritten on every poll: durability
            # here would buy nothing and cost an fsync per status check.
            {
                "batch_id": state.batch_id,
                "status": state.status,
                "poll_count": state.poll_count,
                "polls_until_complete": state.polls_until_complete,
                "created_at": state.created_at,
                "complete_after_seconds": state.complete_after_seconds,
                "tasks": tasks,
                "contracts": contracts or {},
            },
            fsync=False,
        )

    @classmethod
    def release_batch(cls, batch_id: str) -> None:
        """Drop a batch's record, once nothing can be sent back to the batch.

        Not when results are read: the caller still has to write, parse and
        reconcile them, and a failure there brings the next run back for the same
        batch — which a spent record answers with `Batch not found`.

        The `.tmp` of a killed write holds the same payload under a name nothing
        else looks for, so it goes with the record it was.
        """
        state_dir = cls._state_dir()
        # Every provider's ids reach this now. One that is not already a bare
        # file name never named a record here, and reinterpreting it would reach
        # a different batch's.
        name = batch_id
        if not name or name != Path(name).name:
            return
        (state_dir / f"{name}.json").unlink(missing_ok=True)
        for partial in state_dir.glob(f"{glob.escape(name)}_*.tmp"):
            partial.unlink(missing_ok=True)
        cls._batches.pop(batch_id, None)
        cls._tasks_by_batch.pop(batch_id, None)
        cls._contracts_by_batch.pop(batch_id, None)

    @classmethod
    def discard_partial_writes(cls) -> None:
        """Drop every `.tmp` an interrupted write left behind.

        A completed write renames its temp away, so one still sitting here
        describes no batch anybody can reach. Except one a write is still
        holding — taking that fails the write — and age tells them apart: a live
        temp was touched now, an abandoned one whenever the process died.
        """
        cutoff = time.time() - _ABANDONED_WRITE_SECONDS
        for partial in cls._state_dir().glob("*.tmp"):
            try:
                if partial.stat().st_mtime > cutoff:
                    continue
                partial.unlink(missing_ok=True)
            except OSError as e:
                # One unreadable or undeletable file is not a reason to leave the
                # rest of a directory of payloads sitting there.
                logger.debug("Could not reclaim a half-written record: %s", e)

    @classmethod
    def _load_state(cls, batch_id: str) -> MockBatchState | None:
        """Read a batch this process did not submit. None when there is no such batch.

        Not a fallback that invents one: a batch id with no readable record is
        genuinely unknown, and saying so is what lets the caller report it. A
        record missing a field is unreadable in the same sense — it says nothing
        about a batch — rather than an error to raise from a status check.
        """
        try:
            path = cls._state_dir() / f"{batch_id}.json"
            stored = json.loads(path.read_text(encoding="utf-8"))
            state = MockBatchState(
                batch_id=stored["batch_id"],
                status=stored["status"],
                poll_count=stored["poll_count"],
                polls_until_complete=stored["polls_until_complete"],
                created_at=stored["created_at"],
                complete_after_seconds=stored["complete_after_seconds"],
            )
            tasks = stored["tasks"]
            contracts = stored.get("contracts") or {}
        except (OSError, json.JSONDecodeError, KeyError, TypeError, PathManagerError):
            logger.debug("No readable batch record for %s", batch_id)
            return None
        cls._batches[batch_id] = state
        cls._tasks_by_batch[batch_id] = tasks
        cls._contracts_by_batch[batch_id] = contracts if isinstance(contracts, dict) else {}
        return state

    @classmethod
    def _state_for(cls, batch_id: str) -> MockBatchState | None:
        """The batch, from this process or from the run that submitted it."""
        cached = cls._batches.get(batch_id)
        return cached if cached is not None else cls._load_state(batch_id)

    def _fetch_status(self, batch_id: str) -> str:
        """Fetch raw status from mock state with time-based auto-completion."""
        state = self._state_for(batch_id)
        if not state:
            return "unknown"

        state.poll_count += 1

        elapsed = time.time() - state.created_at
        if state.status == "failed":
            logger.debug("Mock batch %s failed at the provider, as the scenario asks", batch_id)
        elif elapsed >= state.complete_after_seconds:
            state.status = "completed"
            logger.debug(
                "Mock batch %s auto-completed after %.1fs",
                batch_id,
                elapsed,
            )
        elif state.polls_until_complete > 0 and state.poll_count >= state.polls_until_complete:
            state.status = "completed"
            logger.debug(
                "Mock batch %s completed after %d polls",
                batch_id,
                state.poll_count,
            )
        else:
            remaining = state.complete_after_seconds - elapsed
            logger.debug(
                "Mock batch %s status: %s (poll %d, %.1fs remaining)",
                batch_id,
                state.status,
                state.poll_count,
                remaining,
            )

        # A poll is state: `polls_until_complete` counts them, and a run that
        # started its count from the submitted value would never reach the
        # threshold — each run polls once and there are two runs by design.
        tasks = self._tasks_by_batch.get(batch_id)
        if tasks is not None:
            self._write_state(state, tasks, self._contracts_by_batch.get(batch_id))
        return state.status

    def _normalize_status(self, raw_status: str) -> str:
        """A batch with no readable record has failed: nothing will come back for it.

        Taken as still running, as a status no mapping knows is, it would hold the
        action for good.
        """
        return "failed" if raw_status == "unknown" else raw_status

    def _fetch_raw_results(self, batch_id: str) -> bytes:
        """Generate mock results as JSONL bytes using schema-based fake data."""
        state = self._state_for(batch_id)
        if not state:
            raise ValueError(f"Batch {batch_id} not found")

        from agent_actions.llm.providers.agac.contract import Contract

        tasks = self._tasks_by_batch.get(batch_id, [])
        contracts = self._contracts_by_batch.get(batch_id) or {}
        lines = []

        followed = sandbox.scenario()
        for task in tasks:
            custom_id = task.get("custom_id", "unknown")

            # Stamped at submit; a task this client never submitted counts in memory.
            stamped = task.get("attempt")
            attempt = (
                stamped if isinstance(stamped, int) else self._get_attempt_for_custom_id(custom_id)
            )

            # A submitted task names its batch's rules by key; a prepared one holds them.
            spec = task.get("contract")
            if isinstance(spec, str):
                key, spec = spec, contracts.get(spec)
                if spec is None:
                    logger.warning(
                        "Mock batch %s: task %s names rules %s that the batch record does "
                        "not hold; answering from the schema only",
                        batch_id,
                        custom_id,
                        key,
                    )
            contract = Contract.from_task(spec, task.get("user_content"))
            # A text-mode request that ends by offering its answer's shapes, as a side
            # call's may (a judge's does), gets one of them, seeded by the request alone.
            request = task.get("user_content") or ""
            text_mode = not (task.get("model_config") or {}).get("json_mode", True)
            shapes = FakeDataGenerator.offered_answer_shapes(request) if text_mode else None

            # A side call's task names no record; only judge.pass_rate governs it.
            record = task.get("record")
            rules = fault = None
            if followed is not None and contract is not None and isinstance(record, str):
                if followed.drops(contract.action, record, attempt):
                    followed.count("dropped")
                    continue
                rules = followed.rules_for(contract.action, task.get("user_content"))
                fault = followed.error_for(contract.action, record, attempt, rules)

            # Straight off the task this client wrote, which holds both.
            openai_response = FakeDataGenerator.generate_openai_response(
                custom_id, task.get("schema"), task.get("prompt"), attempt, contract=contract
            )
            message = openai_response["choices"][0]["message"]
            if shapes:
                passing = (
                    followed.judge_passes(contract.action, request)
                    if followed is not None and contract is not None
                    else None
                )
                message["content"] = FakeDataGenerator.generate_offered_answer(
                    shapes, request, passing
                )
            elif rules is not None and fault is None and followed is not None:
                assert contract is not None and isinstance(record, str)
                answer = json.loads(message["content"])
                schema = task.get("schema")
                unwrapped = FakeDataGenerator.unwrap_schema(schema) if schema else {}
                contract.follow(followed, rules, answer, unwrapped, record, attempt)
                message["content"] = json.dumps(answer)

            # Wrap in batch result format
            result = {
                "id": f"batch_req_{uuid.uuid4().hex[:24]}",
                "custom_id": custom_id,
                "response": {
                    "status_code": 200,
                    "body": openai_response,
                },
                "error": None,
            }
            if fault is not None and followed is not None:
                followed.count("errors")
                result = faults.batch_line(fault, result)

            lines.append(json.dumps(result))

        logger.info(
            "Mock batch %s: returning %d results",
            batch_id,
            len(lines),
        )

        return "\n".join(lines).encode("utf-8")

    def _get_attempt_for_custom_id(self, custom_id: str) -> int:
        """
        Track attempt count per custom_id across batch resubmissions.

        Args:
            custom_id: Custom ID to track

        Returns:
            Current attempt number (1-indexed)
        """
        if not hasattr(self, "_custom_id_attempts"):
            self._custom_id_attempts: dict[str, int] = {}

        if custom_id not in self._custom_id_attempts:
            self._custom_id_attempts[custom_id] = 1
        else:
            self._custom_id_attempts[custom_id] += 1

        return self._custom_id_attempts[custom_id]

    def _get_result_file_name(self, batch_id: str) -> str:
        """Get result file name."""
        return f"{batch_id}_mock_results.jsonl"

    def _prepare_batch_input_file(
        self, tasks: list[dict[str, Any]], batch_dir: Path, batch_name: str
    ) -> Path:
        """Write tasks to input file."""
        return self._write_jsonl_file(tasks, batch_dir, batch_name, "mock")

    def _submit_to_provider_api(self, input_file: Path, batch_name: str) -> tuple[str, str]:
        """Submit mock batch job."""
        batch_id = f"mock_batch_{uuid.uuid4().hex[:12]}"

        # Read tasks from input file
        tasks = []
        with open(input_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    tasks.append(json.loads(line))

        actions = {_task_action(task) for task in tasks}
        followed = sandbox.scenario()
        failing = followed is not None and any(followed.fails_batch(name) for name in actions)
        state = MockBatchState(
            batch_id=batch_id,
            status="failed" if failing else "in_progress",
            polls_until_complete=self.polls_until_complete,
            complete_after_seconds=self.complete_after_seconds,
        )
        self._count_submissions(tasks)
        contracts = _shared_contracts(tasks)
        self._batches[batch_id] = state
        self._tasks_by_batch[batch_id] = tasks
        self._contracts_by_batch[batch_id] = contracts
        self._write_state(state, tasks, contracts)

        logger.info(
            "Mock batch %s submitted: %d tasks",
            batch_id,
            len(tasks),
        )

        return batch_id, "in_progress"

    @classmethod
    def _attempts_file(cls) -> Path:
        return cls._state_dir().parent / "batch_attempts.json"

    @classmethod
    def _count_submissions(cls, tasks: list[dict[str, Any]]) -> None:
        """Stamp each task with its record's submission count for its action, from 1.

        Kept on disk: a retry or repair batch is often submitted and collected by later
        runs, and a scenario's ``heal_on_attempt`` reads the count.
        """
        from agent_actions.utils.atomic_write import atomic_json_write
        from agent_actions.utils.path_utils import ensure_directory_exists

        path = cls._attempts_file()
        with cls._attempts_lock:
            try:
                counts = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                counts = {}
            if not isinstance(counts, dict):
                counts = {}
            now = time.time()
            counts = {
                key: entry
                for key, entry in counts.items()
                if isinstance(entry, list)
                and len(entry) == 2
                and now - entry[1] < _ATTEMPTS_KEPT_SECONDS
            }
            for task in tasks:
                key = f"{_task_action(task)}:{task.get('custom_id')}"
                attempt = counts.get(key, [0, now])[0] + 1
                counts[key] = [attempt, now]
                task["attempt"] = attempt
            ensure_directory_exists(path.parent)
            atomic_json_write(path, counts, fsync=False)

    def _extract_error_from_response(self, raw_response: dict[str, Any]) -> str | None:
        """A failed line's own message, as online raises it; else the status the line holds."""
        error = raw_response.get("error") if isinstance(raw_response, dict) else None
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        return super()._extract_error_from_response(raw_response)

    # ========== Test utilities ==========

    @classmethod
    def reset(cls):
        """Reset all mock batch state. Useful between tests."""
        cls._batches.clear()
        cls._tasks_by_batch.clear()
        cls._contracts_by_batch.clear()
        for stale in cls._state_dir().glob("*.json"):
            stale.unlink(missing_ok=True)
        cls._attempts_file().unlink(missing_ok=True)
        cls.discard_partial_writes()
        logger.debug("AgacBatchClient state reset")

    @classmethod
    def get_batch_state(cls, batch_id: str) -> MockBatchState | None:
        """Get internal state of a batch (for testing/debugging)."""
        return cls._state_for(batch_id)
