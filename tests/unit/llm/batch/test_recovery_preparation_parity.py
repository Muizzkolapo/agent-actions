"""A recovery round is prepared exactly as the first submission was.

The first submission gives its preparator the action's version and the run's
workflow metadata. A retry or repair round that omits either cannot render a
prompt or evaluate a guard that reads `version.*` or `workflow.*`.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.services.processing import BatchProcessingService
from agent_actions.llm.batch.services.repair_ops import (
    build_repair_strategy,
    submit_repair_batch,
)
from agent_actions.llm.batch.services.retry_ops import submit_retry_batch
from agent_actions.llm.batch.services.shared import recovery_preparator
from agent_actions.llm.providers.batch_base import BatchResult

PREPARATOR = "agent_actions.llm.batch.processing.preparator.BatchTaskPreparator"
PROCESSING = "agent_actions.llm.batch.services.processing"
METADATA = {"name": "wf", "run_id": "run_7"}
VERSION = {"i": 2, "idx": 1, "length": 3}


class RecordingPreparator:
    """Stands in for BatchTaskPreparator and records how it was built and called."""

    instances: list["RecordingPreparator"] = []

    def __init__(self, **init_kwargs: Any):
        self.init_kwargs = init_kwargs
        self.prepare_kwargs: dict[str, Any] = {}
        RecordingPreparator.instances.append(self)

    def prepare_tasks(self, **prepare_kwargs: Any):
        self.prepare_kwargs = prepare_kwargs
        return SimpleNamespace(tasks=[{"custom_id": "rec_1"}], context_map={})


@pytest.fixture(autouse=True)
def _reset_recorder():
    RecordingPreparator.instances = []


def _provider() -> MagicMock:
    provider = MagicMock()
    provider.submit_batch.return_value = ("round_batch", 1)
    return provider


class TestRecoveryPreparator:
    def test_a_versioned_action_carries_the_version_the_pipeline_builds(self):
        config = {"is_versioned_agent": True, "_version_context": dict(VERSION)}

        preparator = recovery_preparator(None, config, {"a": 0}, {"a": {}})

        assert preparator.version_context == VERSION
        assert preparator.action_indices == {"a": 0}
        assert preparator.dependency_configs == {"a": {}}

    def test_it_agrees_with_what_the_first_submission_builds(self):
        from agent_actions.workflow.pipeline import ProcessingPipeline

        config = {"is_versioned_agent": True, "_version_context": dict(VERSION)}

        first_submission = ProcessingPipeline._build_pipeline_context(config, {})[2]

        assert recovery_preparator(None, config, {}, {}).version_context == first_submission

    def test_a_non_versioned_action_has_no_version_context(self):
        assert recovery_preparator(None, {"name": "a"}, {}, {}).version_context is None

    def test_no_agent_config_has_no_version_context(self):
        assert recovery_preparator(None, None, {}, {}).version_context is None


class TestRetryRoundIsPreparedLikeTheFirstSubmission:
    def test_retry_hands_the_preparator_the_version_and_the_run_metadata(self):
        with patch(PREPARATOR, RecordingPreparator):
            submit_retry_batch(
                storage_backend=None,
                provider=_provider(),
                missing_ids={"rec_1"},
                context_map={"rec_1": {"target_id": "rec_1"}},
                output_directory="/tmp/out",
                file_name="f.json",
                agent_config={"is_versioned_agent": True, "_version_context": VERSION},
                action_indices={"act": 0},
                dependency_configs={"act": {}},
                workflow_metadata=METADATA,
            )

        built = RecordingPreparator.instances[0]
        assert built.init_kwargs["version_context"] == VERSION
        assert built.init_kwargs["action_indices"] == {"act": 0}
        assert built.prepare_kwargs["workflow_metadata"] == METADATA

    def test_retry_without_run_metadata_still_prepares(self):
        with patch(PREPARATOR, RecordingPreparator):
            result = submit_retry_batch(
                storage_backend=None,
                provider=_provider(),
                missing_ids={"rec_1"},
                context_map={"rec_1": {"target_id": "rec_1"}},
                output_directory="/tmp/out",
                file_name="f.json",
                agent_config={"name": "act"},
                action_indices={},
                dependency_configs={},
            )

        assert result == ("round_batch", 1)
        assert RecordingPreparator.instances[0].prepare_kwargs["workflow_metadata"] is None


class TestRepairRoundIsPreparedLikeTheFirstSubmission:
    @staticmethod
    def _agent_config() -> dict[str, Any]:
        return {
            "name": "act",
            "action_name": "act",
            "agent_type": "act",
            "json_mode": False,
            "model_name": "m",
            "prompt": "p",
            "run_mode": "batch",
            "is_versioned_agent": True,
            "_version_context": VERSION,
            "expect": {
                "repair": "auto",
                "expectations": [
                    {
                        "id": "enough",
                        "type": "item_count",
                        "field": "options",
                        "params": {"min": 2},
                        "hint": "two options",
                    }
                ],
            },
        }

    def test_repair_hands_the_preparator_the_version_and_the_run_metadata(self):
        config = self._agent_config()
        strategy = build_repair_strategy(config)
        failed = BatchResult(custom_id="rec_1", content={"options": ["x"]}, success=True)
        strategy.evaluate(failed)

        with (
            patch(PREPARATOR, RecordingPreparator),
            patch(
                "agent_actions.llm.batch.services.repair_ops._load_source_data",
                return_value=None,
            ),
        ):
            submit_repair_batch(
                action_indices={"act": 0},
                dependency_configs={"act": {}},
                storage_backend=None,
                provider=_provider(),
                failed_results=[failed],
                strategy=strategy,
                context_map={"rec_1": {"target_id": "rec_1", "source_guid": "sg-1"}},
                output_directory="/tmp/out",
                file_name="f.json",
                agent_config=config,
                attempt=1,
                workflow_metadata=METADATA,
            )

        built = RecordingPreparator.instances[0]
        assert built.init_kwargs["version_context"] == VERSION
        assert built.prepare_kwargs["workflow_metadata"] == METADATA
        assert built.prepare_kwargs["attempt"] == 1


class TestMetadataReachesTheRoundsThroughTheCollectPass:
    def test_the_first_pass_retry_receives_the_run_metadata(self):
        manager = MagicMock()
        entry = BatchJobEntry(
            batch_id="b1", status="completed", timestamp="t", provider="mock", file_name="f.json"
        )
        service = BatchProcessingService(
            client_resolver=MagicMock(),
            context_manager=MagicMock(),
            result_processor=MagicMock(),
            registry_manager_factory=lambda name: manager,
            workflow_name="wf",
        )
        service._context_manager.load_batch_context_map.return_value = {
            "rec_1": {"target_id": "rec_1", "source_guid": "g1"}
        }
        service._retry_service = MagicMock()
        service._retry_service.submit_retry_batch.return_value = ("retry_b", 1)

        with (
            patch(f"{PROCESSING}.retrieve_and_reconcile", return_value=[]),
            patch(f"{PROCESSING}.register_recovery_batch"),
            patch(f"{PROCESSING}.RecoveryStateManager"),
        ):
            output = service._process_original_batch(
                "b1",
                "f.json",
                entry,
                "/tmp/out",
                {"retry": {"enabled": True, "max_attempts": 2}},
                manager,
                "act",
                workflow_metadata=METADATA,
            )

        assert output is None
        sent = service._retry_service.submit_retry_batch.call_args.kwargs
        assert sent["workflow_metadata"] == METADATA


PROMPT = "Run {{ workflow.run_id }} voter {{ version.i }}: write options."
FAILING = {"options": ["only-one"]}


def _chain_config(*, retry: bool, repair_rounds: int = 0) -> dict[str, Any]:
    config: dict[str, Any] = {
        "name": "act",
        "action_name": "act",
        "agent_type": "act",
        "json_mode": False,
        "model_name": "test-model",
        "prompt": PROMPT,
        "run_mode": "batch",
        "context_scope": {"observe": ["source.text"]},
        "is_versioned_agent": True,
        "_version_context": VERSION,
    }
    if retry:
        config["retry"] = {"enabled": True, "max_attempts": 3}
    if repair_rounds:
        config["expect"] = {
            "repair": "auto",
            "max_iterations": repair_rounds + 1,
            "expectations": [
                {
                    "id": "enough",
                    "type": "item_count",
                    "field": "options",
                    "params": {"min": 2},
                    "hint": "two options",
                }
            ],
        }
    return config


class _World:
    """A real service, registry and preparator, with only the provider's answers scripted."""

    def __init__(self, tmp_path, config: dict[str, Any]):
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
        from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

        from .recording_provider import RecordingProvider

        self.config = config
        self.out = str(tmp_path / "out")
        self.backend = SQLiteBackend(str(tmp_path / "store" / "wf.db"), "wf")
        self.backend.initialize()
        self.manager = BatchRegistryManager(self.backend, "act")
        self.manager.save_batch_job(
            "f.json",
            BatchJobEntry(
                batch_id="b1",
                status="completed",
                timestamp="t",
                provider="mock",
                file_name="f.json",
            ),
        )
        self.provider = RecordingProvider()
        resolver = MagicMock()
        resolver.get_for_batch_id.return_value = self.provider
        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {
            "t-1": {
                "target_id": "t-1",
                "source_guid": "sg-1",
                "content": {"source": {"text": "in"}},
            }
        }
        self.service = BatchProcessingService(
            client_resolver=resolver,
            context_manager=context_manager,
            result_processor=MagicMock(),
            registry_manager_factory=lambda name: self.manager,
            action_indices={"act": 0},
            dependency_configs={},
            storage_backend=self.backend,
            workflow_name="wf",
        )
        self.original: list[BatchResult] = []
        self.recovery: list[BatchResult] = []

    def collect(self, metadata: dict[str, Any] | None) -> None:
        """One collect pass: the original batch answers `original`, any round answers `recovery`."""

        def answers(provider, batch_id, *args, **kwargs):
            return self.original if batch_id == "b1" else self.recovery

        for entry in self.manager.get_all_jobs().values():
            if entry.parent_file_name:
                self.manager.update_status(entry.batch_id, "completed")
        with (
            patch(f"{PROCESSING}.retrieve_and_reconcile", side_effect=answers),
            patch(f"{PROCESSING}_recovery.retrieve_and_reconcile", side_effect=answers),
        ):
            self.service.process_all_batch_results(
                self.out, self.config, "act", workflow_metadata=metadata
            )

    def latest_prompt(self) -> str:
        return self.provider.submitted[-1]["body"]["messages"][0]["content"]

    def close(self) -> None:
        self.backend.close()


@pytest.fixture
def world(tmp_path):
    made: list[_World] = []

    def make(config: dict[str, Any]) -> _World:
        made.append(_World(tmp_path, config))
        return made[-1]

    yield make
    for w in made:
        w.close()


def _failing() -> BatchResult:
    return BatchResult(custom_id="t-1", content=FAILING, success=True)


class TestEveryRecoverySiteRendersTheRunsMetadataAndVersion:
    """Driven through the real collect pass, so dropping the argument at any hop fails."""

    def test_repair_first_pass(self, world):
        w = world(_chain_config(retry=False, repair_rounds=2))
        w.original = [_failing()]

        w.collect({"name": "wf", "run_id": "run_7"})

        assert w.latest_prompt().startswith("Run run_7 voter 2:")

    def test_retry_first_pass(self, world):
        w = world(_chain_config(retry=True))
        w.original = []

        w.collect({"name": "wf", "run_id": "run_7"})

        assert w.latest_prompt().startswith("Run run_7 voter 2:")

    def test_retry_recovery_uses_the_run_that_collects_it(self, world):
        w = world(_chain_config(retry=True))
        w.original = []
        w.collect({"name": "wf", "run_id": "run_7"})

        w.recovery = []
        w.collect({"name": "wf", "run_id": "run_8"})

        assert w.latest_prompt().startswith("Run run_8 voter 2:")

    def test_a_repair_round_started_from_a_retry_recovery(self, world):
        w = world(_chain_config(retry=True, repair_rounds=2))
        w.original = []
        w.collect({"name": "wf", "run_id": "run_7"})

        w.recovery = [_failing()]
        w.collect({"name": "wf", "run_id": "run_8"})

        assert w.latest_prompt().startswith("Run run_8 voter 2:")
        assert "only-one" in w.latest_prompt()

    def test_repair_recovery_uses_the_run_that_collects_it(self, world):
        w = world(_chain_config(retry=False, repair_rounds=3))
        w.original = [_failing()]
        w.collect({"name": "wf", "run_id": "run_7"})

        w.recovery = [_failing()]
        w.collect({"name": "wf", "run_id": "run_8"})

        assert w.latest_prompt().startswith("Run run_8 voter 2:")


class TestRecoveryTracesCarryTheCollectingRunsId:
    def test_a_repair_rounds_trace_row_has_the_run_id(self, world):
        w = world(_chain_config(retry=False, repair_rounds=2))
        w.original = [_failing()]

        w.collect({"name": "wf", "run_id": "run_7"})

        rows = [r for r in w.backend.get_prompt_traces("act") if r["attempt"] == 1]
        assert [r["run_id"] for r in rows] == ["run_7"]

    def test_a_retried_records_trace_row_has_the_run_id(self, world):
        w = world(_chain_config(retry=True))
        w.original = []

        w.collect({"name": "wf", "run_id": "run_7"})

        rows = w.backend.get_prompt_traces("act")
        assert [r["run_id"] for r in rows] == ["run_7"]
