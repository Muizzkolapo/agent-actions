"""BatchRegistryManager raises RuntimeError, not AssertionError, when its cache fails to load."""

import pytest


class TestBatchRegistryManagerCacheGuard:
    """BatchRegistryManager raises RuntimeError when cache is None after load."""

    def test_save_with_poisoned_cache(self, tmp_path):
        from unittest.mock import MagicMock

        from agent_actions.llm.batch.core.batch_models import BatchJobEntry
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

        mgr = BatchRegistryManager(MagicMock(), "test_action")
        # Force _load_registry to return None (simulating a corrupted state)
        mgr._load_registry = lambda: None  # type: ignore[assignment]

        entry = BatchJobEntry(
            batch_id="b1", status="pending", timestamp="2026-01-01T00:00:00", provider="test"
        )
        with pytest.raises(RuntimeError, match="Cache initialization failed"):
            mgr.save_batch_job("test.json", entry)
