"""Tests for atomic write exception-path (F-6 / I-7): temp-file cleanup on failure.

Both run_results.py and generator.py use mkstemp+os.replace with a BaseException
cleanup block. These tests verify that when the write fails:
  - the temp file is deleted (no orphans left on disk)
  - the original exception propagates unchanged
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.logging.events.handlers.run_results import RunResultsCollector as RunResultsHandler


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
        """If json.dump raises, the .tmp file must be deleted and the error re-raised."""
        handler = self._make_handler(tmp_path)
        (tmp_path / "target").mkdir(parents=True, exist_ok=True)

        original_dump = json.dump

        def boom(*args, **kwargs):
            raise TypeError("unserializable sentinel")

        with patch("agent_actions.logging.events.handlers.run_results.json.dump", boom):
            with pytest.raises(TypeError, match="unserializable sentinel"):
                handler.flush()

        # No orphaned .tmp files should remain in the target dir
        target = tmp_path / "target"
        tmp_files = list(target.glob("*.tmp"))
        assert tmp_files == [], f"Orphaned temp files found: {tmp_files}"

    def test_flush_cleans_up_tmp_on_os_replace_failure(self, tmp_path):
        """If os.replace raises, the .tmp file must be deleted and the error re-raised."""
        handler = self._make_handler(tmp_path)
        (tmp_path / "target").mkdir(parents=True, exist_ok=True)

        def failing_replace(src, dst):
            raise OSError("disk full")

        with patch("agent_actions.logging.events.handlers.run_results.os.replace", failing_replace):
            with pytest.raises(OSError, match="disk full"):
                handler.flush()

        target = tmp_path / "target"
        tmp_files = list(target.glob("*.tmp"))
        assert tmp_files == [], f"Orphaned temp files found: {tmp_files}"
