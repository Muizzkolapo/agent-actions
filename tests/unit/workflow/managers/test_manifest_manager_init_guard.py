"""ManifestManager raises RuntimeError, not AssertionError, when its manifest is not loaded."""

import threading

import pytest


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
