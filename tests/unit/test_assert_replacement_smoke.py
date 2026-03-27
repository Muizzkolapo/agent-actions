"""Smoke tests for production assert → explicit check replacements.

Verifies that method-ordering invariants raise RuntimeError (not AssertionError)
when preconditions are violated.
"""

import threading

import pytest

from agent_actions.config.manager import ConfigManager


class TestConfigManagerSequencingGuards:
    """ConfigManager methods raise RuntimeError when called out of order."""

    def _make_manager(self, tmp_path):
        cfg = tmp_path / "test.yml"
        cfg.write_text("test:\n  - kind: llm\n")
        default = tmp_path / "default.yml"
        default.write_text("{}")
        return ConfigManager(str(cfg), str(default), project_root=tmp_path)

    def test_validate_agent_name_before_load(self, tmp_path):
        cm = self._make_manager(tmp_path)
        with pytest.raises(RuntimeError, match="load_configs.*must be called"):
            cm.validate_agent_name()

    def test_check_child_pipeline_before_load(self, tmp_path):
        cm = self._make_manager(tmp_path)
        with pytest.raises(RuntimeError, match="load_configs.*must be called"):
            cm.check_child_pipeline()

    def test_get_user_agents_before_load(self, tmp_path):
        cm = self._make_manager(tmp_path)
        with pytest.raises(RuntimeError, match="load_configs.*must be called"):
            cm.get_user_agents()


class TestBatchRegistryManagerCacheGuard:
    """BatchRegistryManager raises RuntimeError when cache is None after load."""

    def test_save_with_poisoned_cache(self, tmp_path):
        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

        mgr = BatchRegistryManager(tmp_path / "registry.json")
        # Force cache to None after init (simulating a corrupted state)
        mgr._cache = None
        mgr._ensure_cache_loaded = lambda: None  # no-op to keep cache None

        entry = BatchJobEntry(
            batch_id="b1", status="pending", timestamp="2026-01-01T00:00:00", provider="test"
        )
        with pytest.raises(RuntimeError, match="_cache is None"):
            mgr.save_batch_job("test.json", entry)


class TestManifestManagerInitGuard:
    """ManifestManager raises RuntimeError when _manifest is None."""

    def test_mark_action_started_before_init(self, tmp_path):
        from unittest.mock import PropertyMock, patch

        from agent_actions.workflow.managers.manifest import ManifestManager

        mgr = ManifestManager(tmp_path / "manifest.json")
        mgr._lock = threading.Lock()

        # The manifest property lazily loads, so we mock it to return actions
        # while keeping _manifest as None to hit the guard
        with patch.object(type(mgr), "manifest", new_callable=PropertyMock) as mock_manifest:
            mock_manifest.return_value = {"actions": {"extract": {"status": "pending"}}}
            mgr._manifest = None

            with pytest.raises(RuntimeError, match="_manifest is None"):
                mgr.mark_action_started("extract")
