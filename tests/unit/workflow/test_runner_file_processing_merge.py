"""Regression tests for process_merged_files tempfile-based merging.

Verifies that upstream files are NOT mutated during merge processing
(the old code wrote merged data to the upstream file and restored
it in a finally block, which was unsafe on SIGKILL).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.workflow.runner_file_processing import process_merged_files


def _make_params(upstream_dirs, output_dir, action_config=None):
    """Create a minimal FileProcessParams-like object."""
    params = MagicMock()
    params.upstream_data_dirs = upstream_dirs
    params.output_directory = str(output_dir)
    params.action_config = action_config or {}
    params.action_name = "test_action"
    params.strategy = MagicMock()
    params.idx = 0
    return params


class TestProcessMergedFilesDoesNotMutateUpstream:
    """Upstream files must remain untouched after processing."""

    def test_upstream_file_unchanged_after_merge(self, tmp_path):
        """Upstream file content should be identical before and after merge."""
        # Set up two upstream dirs with overlapping file
        upstream_a = tmp_path / "upstream_a"
        upstream_b = tmp_path / "upstream_b"
        output = tmp_path / "output"
        for d in [upstream_a, upstream_b, output]:
            d.mkdir()

        original_a = [{"id": 1, "value": "from_a"}]
        original_b = [{"id": 2, "value": "from_b"}]
        (upstream_a / "data.json").write_text(json.dumps(original_a))
        (upstream_b / "data.json").write_text(json.dumps(original_b))

        runner = MagicMock()
        runner._collect_files_from_upstream.return_value = {
            Path("data.json"): [upstream_a / "data.json", upstream_b / "data.json"],
        }
        runner._process_single_file = MagicMock()

        params = _make_params([str(upstream_a), str(upstream_b)], output)

        process_merged_files(runner, params)

        # Upstream files must be unchanged
        assert json.loads((upstream_a / "data.json").read_text()) == original_a
        assert json.loads((upstream_b / "data.json").read_text()) == original_b

    def test_upstream_file_unchanged_even_on_processing_error(self, tmp_path):
        """Even if _process_single_file raises, upstream files must not be corrupted."""
        upstream_a = tmp_path / "upstream_a"
        upstream_b = tmp_path / "upstream_b"
        output = tmp_path / "output"
        for d in [upstream_a, upstream_b, output]:
            d.mkdir()

        original_a = [{"id": 1}]
        original_b = [{"id": 2}]
        (upstream_a / "data.json").write_text(json.dumps(original_a))
        (upstream_b / "data.json").write_text(json.dumps(original_b))

        runner = MagicMock()
        runner._collect_files_from_upstream.return_value = {
            Path("data.json"): [upstream_a / "data.json", upstream_b / "data.json"],
        }
        runner._process_single_file.side_effect = RuntimeError("processing failed")

        params = _make_params([str(upstream_a), str(upstream_b)], output)

        with pytest.raises(RuntimeError, match="processing failed"):
            process_merged_files(runner, params)

        # Upstream files must still be unchanged
        assert json.loads((upstream_a / "data.json").read_text()) == original_a
        assert json.loads((upstream_b / "data.json").read_text()) == original_b

    def test_tempfile_cleaned_up_after_processing(self, tmp_path):
        """No stale temp files should remain in upstream dir after processing."""
        upstream_a = tmp_path / "upstream_a"
        upstream_b = tmp_path / "upstream_b"
        output = tmp_path / "output"
        for d in [upstream_a, upstream_b, output]:
            d.mkdir()

        (upstream_a / "data.json").write_text(json.dumps([{"id": 1}]))
        (upstream_b / "data.json").write_text(json.dumps([{"id": 2}]))

        runner = MagicMock()
        runner._collect_files_from_upstream.return_value = {
            Path("data.json"): [upstream_a / "data.json", upstream_b / "data.json"],
        }
        runner._process_single_file = MagicMock()

        params = _make_params([str(upstream_a), str(upstream_b)], output)

        process_merged_files(runner, params)

        # No stale temp files should remain in upstream dir
        remaining = list(upstream_a.glob("tmp*"))
        assert remaining == [], f"Temp files not cleaned up: {remaining}"

    def test_tempfile_cleaned_up_even_on_error(self, tmp_path):
        """Temp files must not leak when _process_single_file raises."""
        upstream_a = tmp_path / "upstream_a"
        upstream_b = tmp_path / "upstream_b"
        output = tmp_path / "output"
        for d in [upstream_a, upstream_b, output]:
            d.mkdir()

        (upstream_a / "data.json").write_text(json.dumps([{"id": 1}]))
        (upstream_b / "data.json").write_text(json.dumps([{"id": 2}]))

        runner = MagicMock()
        runner._collect_files_from_upstream.return_value = {
            Path("data.json"): [upstream_a / "data.json", upstream_b / "data.json"],
        }
        runner._process_single_file.side_effect = RuntimeError("boom")

        params = _make_params([str(upstream_a), str(upstream_b)], output)

        with pytest.raises(RuntimeError, match="boom"):
            process_merged_files(runner, params)

        remaining = list(upstream_a.glob("tmp*"))
        assert remaining == [], f"Temp files leaked on error: {remaining}"

    def test_output_filename_preserves_relative_path(self, tmp_path):
        """The output file must use the original relative path, not a random temp name."""
        upstream_a = tmp_path / "upstream_a"
        upstream_b = tmp_path / "upstream_b"
        output = tmp_path / "output"
        for d in [upstream_a, upstream_b, output]:
            d.mkdir()

        (upstream_a / "data.json").write_text(json.dumps([{"id": 1}]))
        (upstream_b / "data.json").write_text(json.dumps([{"id": 2}]))

        runner = MagicMock()
        runner._collect_files_from_upstream.return_value = {
            Path("data.json"): [upstream_a / "data.json", upstream_b / "data.json"],
        }
        runner._process_single_file = MagicMock()

        params = _make_params([str(upstream_a), str(upstream_b)], output)

        process_merged_files(runner, params)

        # Verify _process_single_file was called with the correct relative path
        call_args = runner._process_single_file.call_args
        locations = call_args[0][0].locations
        relative = locations.item.relative_to(locations.input_path)
        assert relative == Path("data.json"), (
            f"Output filename should be 'data.json', got '{relative}'"
        )
