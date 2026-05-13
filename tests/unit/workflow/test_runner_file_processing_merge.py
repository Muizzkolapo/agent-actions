"""Regression tests for process_merged_files tempfile-based merging.

Verifies that upstream files are NOT mutated during merge processing
(the old code wrote merged data to the upstream file and restored
it in a finally block, which was unsafe on SIGKILL).
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

from agent_actions.workflow.runner_file_processing import (
    process_directory_files,
    process_merged_files,
)


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

        # Error is now caught per-file (no propagation), returns 0 processed
        files_found, files_processed = process_merged_files(runner, params)
        assert files_processed == 0
        assert files_found == 1

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

        # Error is now caught per-file (no propagation)
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


# ---------------------------------------------------------------------------
# File-level error isolation (spec #43 Fix 2)
# ---------------------------------------------------------------------------


class TestProcessDirectoryFilesIsolation:
    """One failing file must not block processing of remaining files."""

    def test_continues_after_single_file_failure(self, tmp_path):
        """3 files, middle one fails → 2 processed, 1 error logged."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        for name in ["a.json", "b.json", "c.json"]:
            (input_dir / name).write_text(json.dumps([{"id": name}]))

        call_count = 0

        def _process(single_params):
            nonlocal call_count
            call_count += 1
            rel = single_params.locations.item.name
            if rel == "b.json":
                raise RuntimeError("record namespace failure on b.json")

        runner = MagicMock()
        runner._should_skip_item.return_value = False
        runner._process_single_file.side_effect = _process

        params = _make_params([str(input_dir)], output_dir)

        files_found, files_processed = process_directory_files(
            runner, input_dir, output_dir, str(input_dir), params, set()
        )

        assert files_processed == 2  # a.json + c.json
        assert files_found == 3  # all 3 seen
        assert call_count == 3  # all 3 attempted

    def test_all_files_succeed_returns_full_count(self, tmp_path):
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()

        for name in ["a.json", "b.json"]:
            (input_dir / name).write_text(json.dumps([{"id": name}]))

        runner = MagicMock()
        runner._should_skip_item.return_value = False
        runner._process_single_file = MagicMock()

        params = _make_params([str(input_dir)], output_dir)

        files_found, files_processed = process_directory_files(
            runner, input_dir, output_dir, str(input_dir), params, set()
        )

        assert files_found == 2
        assert files_processed == 2


class TestProcessMergedFilesIsolation:
    """One failing merged file must not block the rest."""

    def test_continues_after_one_merged_file_fails(self, tmp_path):
        upstream = tmp_path / "upstream"
        output = tmp_path / "output"
        upstream.mkdir()
        output.mkdir()

        (upstream / "good.json").write_text(json.dumps([{"id": 1}]))
        (upstream / "bad.json").write_text(json.dumps([{"id": 2}]))

        def _process(single_params):
            rel = str(single_params.locations.item.relative_to(single_params.locations.input_path))
            if "bad" in rel:
                raise RuntimeError("poisoned record")

        runner = MagicMock()
        runner._collect_files_from_upstream.return_value = {
            Path("good.json"): [upstream / "good.json"],
            Path("bad.json"): [upstream / "bad.json"],
        }
        runner._process_single_file.side_effect = _process

        params = _make_params([str(upstream)], output)

        files_found, files_processed = process_merged_files(runner, params)

        assert files_found == 2
        assert files_processed == 1  # good.json processed, bad.json skipped
        assert runner._process_single_file.call_count == 2
