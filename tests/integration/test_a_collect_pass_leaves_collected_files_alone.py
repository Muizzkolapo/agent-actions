"""A collect pass reads only the files whose results it still owes.

Two input files of one batch action, driven through the real pipeline, store, registry
and collect pass (``process_all_batch_results``). Only the provider is fake, and it keeps
a batch's results however often it is asked, as a real provider does for a while.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from agent_actions.config.types import RunMode
from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.pipeline import create_processing_pipeline_from_params
from tests.integration.test_batch_rerun_matches_online import (
    ACTION,
    SKIP,
    UPSTREAM,
    _config,
    answers,
    rec,
)


class _Provider:
    """Answers each input with its name and the batch that carried it.

    An input named in ``withheld`` is left out of every first answer, as a provider that
    loses a record does, and answered by the retry batch sent for it.
    """

    vendor_type = "openai"

    def __init__(self) -> None:
        self.batches: dict[str, list[dict[str, Any]]] = {}
        self.names: dict[str, str] = {}
        self.asked: list[str] = []
        self.withheld: set[str] = set()

    def prepare_tasks(self, tasks: list[dict[str, Any]], config: dict[str, Any]):
        return [{"custom_id": task["target_id"], "body": task} for task in tasks]

    def submit_batch(self, tasks, batch_name, output_directory):
        batch_id = f"batch-{len(self.batches) + 1}"
        self.batches[batch_id] = tasks
        self.names[batch_id] = batch_name
        return batch_id, BatchStatus.SUBMITTED

    def check_status(self, batch_id: str) -> str:
        self.asked.append(batch_id)
        return BatchStatus.COMPLETED

    def retrieve_results(self, batch_id: str, output_directory: str | None = None):
        self.asked.append(batch_id)
        retry = self.names[batch_id].endswith("_retry")
        return [
            BatchResult(
                custom_id=task["custom_id"],
                content={"answer": f"{_item(task)}@{batch_id}"},
                success=True,
            )
            for task in self.batches[batch_id]
            if retry or _item(task) not in self.withheld
        ]


def _item(task: dict[str, Any]) -> str:
    """The input a task is for, read off the target id `rec` gives it."""
    return task["body"]["target_id"].removeprefix("t-")


class _Action:
    def __init__(self, tmp_path: Path, extra: dict[str, Any] | None = None) -> None:
        self.backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
        self.backend.initialize()
        self.backend.save_metadata("execution_order", json.dumps([UPSTREAM, ACTION]))
        self.backend.save_metadata(
            "dependency_graph", json.dumps({UPSTREAM: [], ACTION: [UPSTREAM]})
        )
        self.root = tmp_path / "agent_io" / "target" / ACTION
        self.provider = _Provider()
        self.config = _config(RunMode.BATCH, {**SKIP, **(extra or {})})

    def run(self, files: dict[str, list[dict[str, Any]]], retry: Any = ()) -> None:
        """One `agac run` over every file, then the collect pass the next run makes.

        *retry* names the records a repair is for, whose dispositions `agac retry` clears
        before it runs.
        """
        for guid in retry:
            self.backend.clear_disposition(ACTION, record_id=guid)
        self.upstream_holds(files)
        for name, inputs in files.items():
            self.process(name, inputs, retry)
        self.collect()

    def upstream_holds(self, files: dict[str, list[dict[str, Any]]]) -> None:
        """The action above stores these files, and no others, as its own run would."""
        self.backend.delete_target(UPSTREAM)
        for name, inputs in files.items():
            rows = [{**row, "_delta_mode": "full", "_state": "processed"} for row in inputs]
            self.backend._write_target_raw(UPSTREAM, name, rows)
        self.backend._reconstruction_cache.clear()

    def process(self, name: str, inputs: list[dict[str, Any]], retry: Any = ()) -> None:
        """Submit one file, as the runner hands a file read from the store."""
        pipeline = create_processing_pipeline_from_params(
            action_config=self.config,
            action_name=ACTION,
            idx=1,
            action_configs={ACTION: self.config},
            storage_backend=self.backend,
            retried_records=frozenset(retry),
        )
        path = self.root / name
        with patch(
            "agent_actions.llm.batch.infrastructure.batch_client_resolver."
            "BatchClientResolver.get_for_config",
            return_value=self.provider,
        ):
            pipeline.process(
                str(path), str(self.root), str(path.parent), data=json.loads(json.dumps(inputs))
            )

    def collect(self) -> None:
        registry = BatchRegistryManager(self.backend, ACTION)
        if not registry.has_uncollected_jobs():
            return
        resolver = MagicMock()
        resolver.get_for_batch_id.return_value = self.provider
        BatchProcessingService(
            client_resolver=resolver,
            context_manager=BatchContextManager(),
            result_processor=BatchResultStrategy(),
            registry_manager_factory=lambda name: registry,
            workflow_name=ACTION,
            storage_backend=self.backend,
        ).process_all_batch_results(str(self.root), agent_config=self.config, action_name=ACTION)

    def reset(self) -> None:
        """What a reset does to an action about to run again from new input."""
        self.backend.clear_disposition(ACTION)
        self.backend.clear_checkpoint_records(ACTION)
        self.backend.clear_batch_state(ACTION)

    def fresh(self) -> None:
        """What `agac run --fresh` does to the action and the one above it."""
        for action in (UPSTREAM, ACTION):
            self.backend.delete_target(action)
            self.backend.clear_disposition(action)
            self.backend.clear_batch_state(action)

    def held(self, name: str) -> list[str]:
        self.backend._reconstruction_cache.clear()
        return answers(self.backend.read_target_for_rewrite(ACTION, name))

    def files(self) -> dict[str, list[str]]:
        """Every file the action stores, with what each holds."""
        return {name: self.held(name) for name in self.backend.list_target_files(ACTION)}


def test_a_file_a_later_run_wrote_is_not_written_again_from_its_spent_batch(tmp_path):
    action = _Action(tmp_path)
    action.run({"page1.json": [rec("a1", keep=True)], "page2.json": [rec("b1", keep=True)]})
    assert action.held("page1.json") == ["processed:a1@batch-1"]

    # a1 leaves page1 and a3, which the guard skips, arrives: nothing is sent for page1,
    # so this run writes page1 itself. page2 gains b2, which is sent.
    action.run(
        {
            "page1.json": [rec("a3", keep=False)],
            "page2.json": [rec("b1", keep=True), rec("b2", keep=True)],
        }
    )

    assert action.held("page1.json") == ["guard_skipped:a3"]
    assert action.held("page2.json") == ["processed:b1@batch-2", "processed:b2@batch-3"]


def test_a_spent_batch_is_not_asked_about_again(tmp_path):
    action = _Action(tmp_path)
    action.run({"page1.json": [rec("a1", keep=True)], "page2.json": [rec("b1", keep=True)]})
    asked_before = len(action.provider.asked)

    action.run(
        {
            "page1.json": [rec("a1", keep=True)],
            "page2.json": [rec("b1", keep=True), rec("b2", keep=True)],
        }
    )

    assert set(action.provider.asked[asked_before:]) == {"batch-3"}
