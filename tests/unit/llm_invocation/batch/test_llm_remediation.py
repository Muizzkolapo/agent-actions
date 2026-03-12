"""Tests for LLM module remediation fixes (Buckets 1 and 2).

Covers: 1-A malformed registry, 1-B stale result reuse, 1-C model hardcoding,
1-E path traversal, 2-A api_key required fields, 2-B cache key, 2-C job_manager
delegation, 2-D StopIteration + JSONL blanks, 2-E vendor type, 2-F SubmissionResult.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── 1-A: are_all_jobs_completed returns False on malformed registry ──


class TestMalformedRegistryHandling:
    """Commit 1-A: Malformed registry should return False, not True."""

    def test_returns_false_on_malformed_json(self, tmp_path):
        from agent_actions.llm.batch.infrastructure.job_manager import BatchJobManager

        # Create malformed registry file
        batch_dir = tmp_path / "batch"
        batch_dir.mkdir()
        registry_file = batch_dir / ".batch_registry.json"
        registry_file.write_text("{invalid json content")

        manager = BatchJobManager(client_resolver=MagicMock())
        result = manager.are_all_jobs_completed(str(tmp_path))

        assert result is False

    def test_returns_true_when_no_registry_file(self, tmp_path):
        from agent_actions.llm.batch.infrastructure.job_manager import BatchJobManager

        manager = BatchJobManager(client_resolver=MagicMock())
        result = manager.are_all_jobs_completed(str(tmp_path))

        assert result is True

    def test_returns_true_for_empty_output_directory(self):
        from agent_actions.llm.batch.infrastructure.job_manager import BatchJobManager

        manager = BatchJobManager(client_resolver=MagicMock())
        result = manager.are_all_jobs_completed("")

        assert result is True


# ── 1-B: Retrieval always writes fresh results ──


class TestRetrievalOverwritesExistingResults:
    """Commit 1-B: Fresh results should overwrite existing files."""

    def test_overwrites_existing_results_file(self, tmp_path):
        from agent_actions.llm.batch.services.retrieval import BatchRetrievalService

        # Create existing file with old content
        existing_file = tmp_path / "batch_123_results.jsonl"
        existing_file.write_text("old content\n")

        entry = MagicMock()
        entry.file_name = None
        entry.record_count = 1

        manager = MagicMock()
        manager.get_batch_job_by_id.return_value = entry

        context_manager = MagicMock()
        context_manager.load_batch_context_map.return_value = {}

        provider = MagicMock()
        result1 = MagicMock()
        result1.custom_id = "record_1"
        result1.content = {"answer": "new"}
        result1.usage = {"tokens": 10}
        provider.retrieve_results.return_value = [result1]

        client_resolver = MagicMock()
        client_resolver.get_for_batch_id.return_value = provider

        service = BatchRetrievalService(
            client_resolver=client_resolver,
            context_manager=context_manager,
            registry_manager_factory=MagicMock(return_value=manager),
        )

        result_file = service.retrieve_results("batch_123", str(tmp_path))

        # Verify new content replaced old
        content = Path(result_file).read_text()
        assert "old content" not in content
        assert "record_1" in content


# ── 1-C: Gemini/Mistral use configured model ──


class TestConfiguredModelUsed:
    """Commit 1-C: prepare_tasks should store configured model for submit."""

    def test_prepare_tasks_stores_configured_model(self):
        from agent_actions.llm.providers.batch_base import BaseBatchClient

        # Create a concrete subclass for testing
        class TestClient(BaseBatchClient):
            def _get_default_model(self):
                return "default-model"

            def format_task_for_provider(self, batch_task, schema=None):
                return {"id": batch_task.custom_id}

            def _extract_error_from_response(self, raw_response):
                return None

            def _extract_content_from_response(self, raw_response):
                return ""

            def _extract_metadata_from_response(self, raw_response):
                return {}

            def _extract_usage_from_response(self, raw_response):
                return None

            def _get_result_file_name(self, batch_id):
                return f"{batch_id}.jsonl"

            def _fetch_raw_results(self, batch_id):
                return b""

            def _prepare_batch_input_file(self, tasks, batch_dir, batch_name):
                return batch_dir / "input.jsonl"

            def _submit_to_provider_api(self, input_file, batch_name):
                return ("batch_123", "submitted")

            def _fetch_status(self, batch_id):
                return "completed"

            def _normalize_status(self, raw_status):
                return raw_status

        client = TestClient()

        # Call prepare_tasks with custom model
        agent_config = {"model_name": "custom-model-v2", "prompt": "test"}
        data = [{"target_id": "1", "content": "test"}]
        client.prepare_tasks(data, agent_config)

        assert client._configured_model == "custom-model-v2"

    def test_prepare_tasks_uses_default_model_when_not_configured(self):
        from agent_actions.llm.providers.batch_base import BaseBatchClient

        class TestClient(BaseBatchClient):
            def _get_default_model(self):
                return "default-model"

            def format_task_for_provider(self, batch_task, schema=None):
                return {"id": batch_task.custom_id}

            def _extract_error_from_response(self, raw_response):
                return None

            def _extract_content_from_response(self, raw_response):
                return ""

            def _extract_metadata_from_response(self, raw_response):
                return {}

            def _extract_usage_from_response(self, raw_response):
                return None

            def _get_result_file_name(self, batch_id):
                return f"{batch_id}.jsonl"

            def _fetch_raw_results(self, batch_id):
                return b""

            def _prepare_batch_input_file(self, tasks, batch_dir, batch_name):
                return batch_dir / "input.jsonl"

            def _submit_to_provider_api(self, input_file, batch_name):
                return ("batch_123", "submitted")

            def _fetch_status(self, batch_id):
                return "completed"

            def _normalize_status(self, raw_status):
                return raw_status

        client = TestClient()

        # Call prepare_tasks without model_name
        agent_config = {"prompt": "test"}
        data = [{"target_id": "1", "content": "test"}]
        client.prepare_tasks(data, agent_config)

        assert client._configured_model == "default-model"


# ── 1-E: Path traversal rejection ──


class TestPathTraversalRejection:
    """Commit 1-E: Path traversal in file names should be rejected."""

    def test_recovery_state_rejects_path_traversal(self):
        from agent_actions.llm.batch.infrastructure.recovery_state import (
            RecoveryStateManager,
        )

        with pytest.raises(ValueError, match="path traversal"):
            RecoveryStateManager._get_path("/tmp", "../../etc/passwd")

    def test_recovery_state_strips_directory_components(self):
        from agent_actions.llm.batch.infrastructure.recovery_state import (
            RecoveryStateManager,
        )

        path = RecoveryStateManager._get_path("/tmp", "subdir/file.json")
        assert "subdir" not in str(path)
        assert ".recovery_state_file.json.json" in str(path)

    def test_context_map_rejects_path_traversal(self):
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager

        with pytest.raises(ValueError, match="path traversal"):
            BatchContextManager._get_context_path("/tmp", "../../etc/passwd")

    def test_context_map_strips_directory_components(self):
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager

        path = BatchContextManager._get_context_path("/tmp", "subdir/batch.json")
        assert "subdir" not in str(path)
        assert ".context_map_batch.json" in str(path)

    def test_recovery_state_allows_normal_names(self):
        from agent_actions.llm.batch.infrastructure.recovery_state import (
            RecoveryStateManager,
        )

        path = RecoveryStateManager._get_path("/tmp", "my_batch.json")
        assert str(path) == "/tmp/batch/.recovery_state_my_batch.json.json"

    def test_context_map_allows_normal_names(self):
        from agent_actions.llm.batch.infrastructure.context import BatchContextManager

        path = BatchContextManager._get_context_path("/tmp", "my_batch.json")
        assert str(path) == "/tmp/batch/.context_map_my_batch.json"


# ── 2-A: api_key not required in resolver ──


class TestApiKeyNotRequired:
    """Commit 2-A: api_key should not be a required field."""

    def test_config_without_api_key_does_not_raise(self):
        from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
            BatchClientResolver,
        )

        resolver = BatchClientResolver()

        # Should not raise for missing api_key
        # (will still fail on client creation, but not on validation)
        config = {"model_vendor": "openai", "model_name": "gpt-4o-mini"}
        try:
            resolver.get_for_config(config)
        except Exception as e:
            # Should not be a "missing api_key" error
            assert "api_key" not in str(e).lower() or "missing" not in str(e).lower()


# ── 2-B: Cache key includes api_key hash ──


class TestCacheKeyIncludesApiKey:
    """Commit 2-B: Different api_keys should produce different cache keys."""

    def test_different_api_keys_produce_different_cache_keys(self):
        from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
            BatchClientResolver,
        )

        key1 = BatchClientResolver._build_cache_key("openai", {"api_key": "key-1"})
        key2 = BatchClientResolver._build_cache_key("openai", {"api_key": "key-2"})

        assert key1 != key2
        assert key1.startswith("openai:")
        assert key2.startswith("openai:")

    def test_same_api_key_produces_same_cache_key(self):
        from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
            BatchClientResolver,
        )

        key1 = BatchClientResolver._build_cache_key("openai", {"api_key": "same-key"})
        key2 = BatchClientResolver._build_cache_key("openai", {"api_key": "same-key"})

        assert key1 == key2

    def test_no_api_key_uses_vendor_only(self):
        from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
            BatchClientResolver,
        )

        key = BatchClientResolver._build_cache_key("openai", {})
        assert key == "openai"

    def test_get_for_batch_id_finds_hashed_cache_entry(self):
        from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
            BatchClientResolver,
        )

        mock_client = MagicMock()
        resolver = BatchClientResolver(client_cache={"openai:abc123def456": mock_client})

        registry_manager = MagicMock()
        entry = MagicMock()
        entry.provider = "openai"
        registry_manager.get_batch_job_by_id.return_value = entry

        result = resolver.get_for_batch_id("batch_99", registry_manager)
        assert result is mock_client

    def test_get_for_batch_id_skips_ambiguous_multi_key_cache(self):
        from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
            BatchClientResolver,
        )

        client_a = MagicMock()
        client_b = MagicMock()
        resolver = BatchClientResolver(
            client_cache={"openai:aaa": client_a, "openai:bbb": client_b}
        )

        registry_manager = MagicMock()
        entry = MagicMock()
        entry.provider = "openai"
        registry_manager.get_batch_job_by_id.return_value = entry

        fresh_client = MagicMock()
        with patch(
            "agent_actions.llm.batch.infrastructure.batch_client_resolver.BatchClientFactory.create_client",
            return_value=fresh_client,
        ):
            result = resolver.get_for_batch_id("batch_99", registry_manager)

        # Should NOT return either cached client — ambiguous; falls through to factory
        assert result is not client_a
        assert result is not client_b
        assert result is fresh_client

    def test_get_for_batch_id_finds_plain_cache_entry(self):
        from agent_actions.llm.batch.infrastructure.batch_client_resolver import (
            BatchClientResolver,
        )

        mock_client = MagicMock()
        resolver = BatchClientResolver(client_cache={"openai": mock_client})

        registry_manager = MagicMock()
        entry = MagicMock()
        entry.provider = "openai"
        registry_manager.get_batch_job_by_id.return_value = entry

        result = resolver.get_for_batch_id("batch_99", registry_manager)
        assert result is mock_client


# ── 2-C: job_manager delegates to registry manager ──


class TestJobManagerDelegation:
    """Commit 2-C: job_manager should delegate to BatchRegistryManager."""

    def test_are_all_jobs_completed_delegates_to_registry_manager(self, tmp_path):
        from agent_actions.llm.batch.infrastructure.job_manager import BatchJobManager

        registry_manager = MagicMock()
        registry_manager.are_all_jobs_completed.return_value = True

        manager = BatchJobManager(
            client_resolver=MagicMock(),
            registry_manager=registry_manager,
        )
        result = manager.are_all_jobs_completed(str(tmp_path))

        # Registry manager doesn't need a file since we pre-set it
        assert result is True

    def test_get_registry_status_delegates_to_registry_manager(self, tmp_path):
        from agent_actions.llm.batch.infrastructure.job_manager import BatchJobManager

        registry_manager = MagicMock()
        registry_manager.get_overall_status.return_value = "completed"

        manager = BatchJobManager(
            client_resolver=MagicMock(),
            registry_manager=registry_manager,
        )
        result = manager.get_registry_status(str(tmp_path))

        assert result == "completed"


# ── 2-D: find_agent_name and JSONL blank lines ──


class TestFindAgentNameEmptyConfig:
    """Commit 2-D: find_agent_name should raise on empty dict.

    Note: ConfigManager has a circular import issue when loaded in test context,
    so we test the method logic directly by extracting the function behavior.
    """

    def _get_find_agent_name(self):
        """Get the find_agent_name function, working around circular import."""
        import importlib
        import sys

        # The circular import is: config -> workflow.models -> workflow.__init__
        # -> workflow.coordinator -> config. We mock the coordinator import.
        sentinel = object()
        old = sys.modules.get("agent_actions.workflow.coordinator", sentinel)
        sys.modules["agent_actions.workflow.coordinator"] = MagicMock()
        try:
            if "agent_actions.llm.realtime.config" in sys.modules:
                importlib.reload(sys.modules["agent_actions.llm.realtime.config"])
            from agent_actions.llm.realtime.config import ConfigManager

            mgr = ConfigManager.__new__(ConfigManager)
            return mgr.find_agent_name
        finally:
            if old is sentinel:
                sys.modules.pop("agent_actions.workflow.coordinator", None)
            else:
                sys.modules["agent_actions.workflow.coordinator"] = old

    def test_raises_on_empty_config(self):
        from agent_actions.errors import ConfigurationError

        find_agent_name = self._get_find_agent_name()
        with pytest.raises(ConfigurationError, match="empty"):
            find_agent_name({})

    def test_returns_name_from_named_config(self):
        find_agent_name = self._get_find_agent_name()
        result = find_agent_name({"name": "MyAgent", "actions": []})
        assert result == "MyAgent"

    def test_returns_first_key_from_dict_config(self):
        find_agent_name = self._get_find_agent_name()
        result = find_agent_name({"AgentName": {"key": "value"}})
        assert result == "AgentName"


class TestJsonlBlankLineSkipping:
    """Commit 2-D: JSONL loader should skip blank lines."""

    def test_skips_blank_lines_in_jsonl(self, tmp_path):
        from agent_actions.llm.batch.infrastructure.batch_data_loader import (
            BatchDataLoader,
        )

        jsonl_file = tmp_path / "test.jsonl"
        jsonl_file.write_text('{"id": 1}\n\n{"id": 2}\n\n')

        loader = BatchDataLoader()
        data = loader.load_data(str(jsonl_file))

        assert len(data) == 2
        assert data[0]["id"] == 1
        assert data[1]["id"] == 2


# ── 2-E: VendorType google/gemini alias ──


class TestVendorTypeGoogleGeminiAlias:
    """Commit 2-E: GOOGLE should alias to GEMINI."""

    def test_google_equals_gemini(self):
        from agent_actions.llm.config.vendor import VendorType

        assert VendorType.GOOGLE.value == VendorType.GEMINI.value
        assert VendorType.GOOGLE.value == "gemini"

    def test_google_config_uses_gemini_vendor_type(self):
        from agent_actions.llm.config.vendor import GeminiConfig, GoogleConfig

        assert GoogleConfig is GeminiConfig


# ── 2-F: SubmissionResult dataclass ──


class TestSubmissionResult:
    """Commit 2-F: SubmissionResult replaces Union[str, Dict]."""

    def test_batch_id_result(self):
        from agent_actions.llm.batch.core.batch_models import SubmissionResult

        result = SubmissionResult(batch_id="batch_123")
        assert result.is_submitted
        assert not result.is_passthrough
        assert result.batch_id == "batch_123"

    def test_passthrough_result(self):
        from agent_actions.llm.batch.core.batch_models import SubmissionResult

        result = SubmissionResult(passthrough={"type": "tombstone", "data": []})
        assert not result.is_submitted
        assert result.is_passthrough
        assert result.passthrough["type"] == "tombstone"

    def test_empty_result(self):
        from agent_actions.llm.batch.core.batch_models import SubmissionResult

        result = SubmissionResult()
        assert not result.is_submitted
        assert not result.is_passthrough
