"""Tests for atomic write exception-path (F-6 / I-7): temp-file cleanup on failure.

run_results.py and generator.py use atomic_json_write (temp file + rename).
These tests verify that when the write fails:
  - the temp file is deleted (no orphans left on disk)
  - the error propagates
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.logging.events.handlers.run_results import (
    RunResultsCollector as RunResultsHandler,
)

# ---------------------------------------------------------------------------
# RunResultsHandler.flush() — atomic write exception path (I-7)
# ---------------------------------------------------------------------------


class TestRunResultsAtomicWrite:
    def _make_handler(self, tmp_path: Path) -> RunResultsHandler:
        return RunResultsHandler(output_dir=tmp_path)

    def test_flush_succeeds_and_writes_file(self, tmp_path):
        """Happy path: flush() creates run_results.json."""
        handler = self._make_handler(tmp_path)
        handler.flush()
        output = tmp_path / "target" / "run_results.json"
        assert output.exists()
        data = json.loads(output.read_text())
        assert "metadata" in data

    def test_flush_cleans_up_tmp_on_write_failure(self, tmp_path):
        """If json.dump raises inside atomic_json_write, temp file is cleaned up."""
        handler = self._make_handler(tmp_path)
        (tmp_path / "target").mkdir(parents=True, exist_ok=True)

        def boom(*args, **kwargs):
            raise TypeError("unserializable sentinel")

        with patch("agent_actions.utils.atomic_write.json.dump", boom):
            with pytest.raises(OSError, match="unserializable sentinel"):
                handler.flush()

        # No orphaned .tmp files should remain in the target dir
        target = tmp_path / "target"
        tmp_files = list(target.glob("*.tmp"))
        assert tmp_files == [], f"Orphaned temp files found: {tmp_files}"

    def test_flush_cleans_up_tmp_on_rename_failure(self, tmp_path):
        """If rename raises inside atomic_json_write, temp file is cleaned up."""
        handler = self._make_handler(tmp_path)
        (tmp_path / "target").mkdir(parents=True, exist_ok=True)

        _orig = Path.replace

        def failing_replace(self_path, target):
            if str(self_path).endswith(".json.tmp"):
                raise OSError("disk full")
            return _orig(self_path, target)

        with patch.object(Path, "replace", failing_replace):
            with pytest.raises(OSError, match="disk full"):
                handler.flush()

        target = tmp_path / "target"
        tmp_files = list(target.glob("*.tmp"))
        assert tmp_files == [], f"Orphaned temp files found: {tmp_files}"
