"""
Tests for concurrent file writes in batch_service.py.

These tests verify that file locking prevents race conditions when multiple
processes write to the same source file simultaneously.
"""

import json
import multiprocessing
import tempfile
import time
from pathlib import Path

import pytest

from agent_actions.llm_invocation.batch.batch_service import BatchService


def write_source_data(service, src_text, file_path, base_dir, output_dir, process_id):
    """Helper function to write source data from a separate process."""
    try:
        # Add a small random delay to increase chance of race conditions
        time.sleep(process_id * 0.01)
        service._save_task_source(src_text, file_path, base_dir, output_dir)
        return f"Process {process_id} completed successfully"
    except Exception as e:
        return f"Process {process_id} failed: {str(e)}"


class TestBatchServiceConcurrent:
    """Test concurrent writes to source files with file locking."""

    @pytest.fixture
    def temp_dirs(self):
        """Create temporary directories for testing."""
        with tempfile.TemporaryDirectory() as base_dir:
            base_path = Path(base_dir)
            input_dir = base_path / 'input'
            output_dir = base_path / 'output'
            source_dir = base_path / 'source'

            input_dir.mkdir()
            output_dir.mkdir()
            source_dir.mkdir()

            yield {
                'base': base_path,
                'input': input_dir,
                'output': output_dir,
                'source': source_dir
            }

    @pytest.fixture
    def batch_service(self):
        """Create a BatchService instance for testing."""
        return BatchService()

    def test_concurrent_writes_no_data_loss(self, batch_service, temp_dirs):
        """Test that concurrent writes don't lose data."""
        # Create test file
        test_file = temp_dirs['input'] / 'test.json'
        test_file.write_text('{}')

        # Prepare test data - 10 processes writing different items
        num_processes = 10
        processes = []

        for i in range(num_processes):
            src_text = [{
                'source_guid': f'guid_{i}',
                'content': f'Content from process {i}',
                'process_id': i
            }]

            p = multiprocessing.Process(
                target=write_source_data,
                args=(batch_service, src_text, str(test_file), str(temp_dirs['input']), str(temp_dirs['output']), i)
            )
            processes.append(p)

        # Start all processes at roughly the same time
        for p in processes:
            p.start()

        # Wait for all to complete
        for p in processes:
            p.join(timeout=10)  # 10 second timeout

        # Verify all data was written
        output_file = temp_dirs['source'] / 'test.json'
        assert output_file.exists(), "Output source file should exist"

        with open(output_file, 'r') as f:
            saved_data = json.load(f)

        # Should have exactly 10 items (one from each process)
        assert len(saved_data) == num_processes, f"Expected {num_processes} items, got {len(saved_data)}"

        # Verify all guids are present (no data loss)
        saved_guids = {item['source_guid'] for item in saved_data}
        expected_guids = {f'guid_{i}' for i in range(num_processes)}
        assert saved_guids == expected_guids, "All source_guids should be present (no data loss)"

    def test_concurrent_writes_duplicate_prevention(self, batch_service, temp_dirs):
        """Test that concurrent writes with same guid don't create duplicates."""
        test_file = temp_dirs['input'] / 'test.json'
        test_file.write_text('{}')

        # 5 processes trying to write the same guid
        num_processes = 5
        processes = []

        for i in range(num_processes):
            src_text = [{
                'source_guid': 'same_guid',  # Same guid for all
                'content': f'Content from process {i}',
                'process_id': i
            }]

            p = multiprocessing.Process(
                target=write_source_data,
                args=(batch_service, src_text, str(test_file), str(temp_dirs['input']), str(temp_dirs['output']), i)
            )
            processes.append(p)

        for p in processes:
            p.start()

        for p in processes:
            p.join(timeout=10)

        # Verify only 1 item exists (deduplication worked)
        output_file = temp_dirs['source'] / 'test.json'
        with open(output_file, 'r') as f:
            saved_data = json.load(f)

        assert len(saved_data) == 1, "Should only have 1 item (deduplication across concurrent writes)"
        assert saved_data[0]['source_guid'] == 'same_guid'

    def test_file_locking_prevents_corruption(self, batch_service, temp_dirs):
        """Test that file locking prevents JSON corruption from concurrent writes."""
        test_file = temp_dirs['input'] / 'test.json'
        test_file.write_text('{}')

        # Many processes writing simultaneously
        num_processes = 20
        processes = []

        for i in range(num_processes):
            src_text = [{
                'source_guid': f'guid_{i}',
                'content': 'x' * 1000,  # Larger content to increase chance of corruption
                'index': i
            }]

            p = multiprocessing.Process(
                target=write_source_data,
                args=(batch_service, src_text, str(test_file), str(temp_dirs['input']), str(temp_dirs['output']), i)
            )
            processes.append(p)

        for p in processes:
            p.start()

        for p in processes:
            p.join(timeout=15)

        # Verify file is valid JSON (not corrupted)
        output_file = temp_dirs['source'] / 'test.json'
        try:
            with open(output_file, 'r') as f:
                saved_data = json.load(f)

            # File should be valid JSON with all items
            assert isinstance(saved_data, list), "Data should be a list"
            assert len(saved_data) == num_processes, "All items should be present"
        except json.JSONDecodeError as e:
            pytest.fail(f"File corrupted due to race condition: {e}")

    def test_handles_concurrent_new_file_creation(self, batch_service, temp_dirs):
        """Test that multiple processes can safely create the same new file."""
        # Don't create the file - let processes create it concurrently
        test_file = temp_dirs['input'] / 'new_file.json'

        num_processes = 5
        processes = []

        for i in range(num_processes):
            src_text = [{
                'source_guid': f'guid_{i}',
                'content': f'Content {i}'
            }]

            p = multiprocessing.Process(
                target=write_source_data,
                args=(batch_service, src_text, str(test_file), str(temp_dirs['input']), str(temp_dirs['output']), i)
            )
            processes.append(p)

        for p in processes:
            p.start()

        for p in processes:
            p.join(timeout=10)

        # Verify file was created and has all items
        output_file = temp_dirs['source'] / 'new_file.json'
        assert output_file.exists(), "File should be created"

        with open(output_file, 'r') as f:
            saved_data = json.load(f)

        assert len(saved_data) == num_processes, "All processes should have written their data"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
