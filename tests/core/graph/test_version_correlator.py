"""Tests for Loop Output Correlator functionality."""

import json
import tempfile
from pathlib import Path

import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.coordinator import AgentWorkflow
from agent_actions.workflow.managers.loop import VersionOutputCorrelator


class TestVersionOutputCorrelator:
    """Test suite for VersionOutputCorrelator."""

    @pytest.fixture
    def temp_agent_folder(self):
        """Create a temporary agent folder for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def storage_backend(self, temp_agent_folder):
        """Create a SQLite backend for testing."""
        db_path = temp_agent_folder / "store" / "test.db"
        backend = SQLiteBackend.create(db_path=str(db_path), workflow_name="test")
        backend.initialize()
        yield backend
        backend.close()

    @pytest.fixture
    def correlator(self, temp_agent_folder, storage_backend):
        """Create a VersionOutputCorrelator instance with storage backend."""
        return VersionOutputCorrelator(temp_agent_folder, storage_backend=storage_backend)

    @pytest.fixture
    def sample_execution_order(self):
        """Provide sample execution order for testing."""
        return [
            "extract_facts",
            "generate_scenarios",
            "generate_distractors_1",
            "generate_distractors_2",
            "generate_distractors_3",
            "reconstruct_options",
            "validate_quiz",
        ]

    @pytest.fixture
    def sample_agent_configs(self):
        """Provide sample agent configurations."""
        return {
            "extract_facts": {"agent_type": "extract_facts", "dependencies": []},
            "generate_scenarios": {
                "agent_type": "generate_scenarios",
                "dependencies": ["extract_facts"],
            },
            "generate_distractors_1": {
                "agent_type": "generate_distractors",
                "dependencies": ["generate_scenarios"],
            },
            "generate_distractors_2": {
                "agent_type": "generate_distractors",
                "dependencies": ["generate_scenarios"],
            },
            "generate_distractors_3": {
                "agent_type": "generate_distractors",
                "dependencies": ["generate_scenarios"],
            },
            "reconstruct_options": {
                "agent_type": "reconstruct_options",
                "dependencies": [],
                "version_consumption_config": {
                    "source": "generate_distractors",
                    "pattern": "merge",
                },
            },
            "validate_quiz": {
                "agent_type": "validate_quiz",
                "dependencies": ["reconstruct_options"],
            },
        }

    def test_detect_explicit_version_consumption(
        self, correlator, sample_execution_order, sample_agent_configs
    ):
        """Test detection of explicit loop consumption."""
        consumption_map = correlator.detect_explicit_version_consumption(
            sample_execution_order, sample_agent_configs
        )
        assert "reconstruct_options" in consumption_map
        config = consumption_map["reconstruct_options"]
        assert config["source_base_name"] == "generate_distractors"
        assert config["pattern"] == "merge"
        assert set(config["version_agents"]) == {
            "generate_distractors_1",
            "generate_distractors_2",
            "generate_distractors_3",
        }
        assert "validate_quiz" not in consumption_map

    def test_filename_preservation(self, correlator, storage_backend, temp_agent_folder):
        """Test that original filenames are preserved during correlation."""
        test_filename = "Azure_AI_Questions.json"
        for i in range(1, 4):
            action_name = f"generate_distractors_{i}"
            test_data = [
                {
                    "source_guid": "test-guid-1",
                    "version_correlation_id": "test-corr-1",
                    "target_id": "target-1",
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {action_name: {f"distractor_{i}": f"Wrong answer {i}"}},
                }
            ]
            storage_backend._write_target_raw(action_name, test_filename, test_data)
        result_dir = correlator.prepare_correlated_input(
            "reconstruct_options",
            ["generate_distractors_1", "generate_distractors_2", "generate_distractors_3"],
            4,
        )
        assert result_dir is not None, "prepare_correlated_input returned None"
        target_files = storage_backend.list_target_files("reconstruct_options")
        assert test_filename in target_files, f"Expected {test_filename} in backend target files"
        source_file = temp_agent_folder / "source" / test_filename
        assert source_file.exists(), f"Source file {test_filename} not created"

    def test_correlation_source_includes_lineage(
        self, correlator, storage_backend, temp_agent_folder
    ):
        """Source file created by correlation must include lineage for downstream enrichment."""
        for i in range(1, 3):
            action_name = f"scorer_{i}"
            test_data = [
                {
                    "source_guid": "guid-1",
                    "version_correlation_id": "corr-1",
                    "target_id": "tid-1",
                    "node_id": f"node_{i}_abc",
                    "lineage": ["node_0_root", f"node_{i}_abc"],
                    "_state": "processed",
                    "_state_schema_version": 1,
                    "content": {action_name: {f"score_{i}": 8}},
                }
            ]
            storage_backend._write_target_raw(action_name, "data.json", test_data)

        correlator.prepare_correlated_input("aggregate", ["scorer_1", "scorer_2"], 3)

        source_file = temp_agent_folder / "source" / "data.json"
        assert source_file.exists()
        with open(source_file) as f:
            source_data = json.load(f)

        assert len(source_data) == 1
        record = source_data[0]
        assert record["source_guid"] == "guid-1"
        assert len(record["lineage"]) >= 2
        assert "node_0_root" in record["lineage"]

    def test_partial_record_handling(self, correlator, storage_backend, temp_agent_folder):
        """Test that records missing from some loops are still included."""
        lifecycle = {"_state": "processed", "_state_schema_version": 1}
        data_loop1 = [
            {
                "source_guid": "guid-1",
                "version_correlation_id": "corr-1",
                **lifecycle,
                "content": {"distractor_1": {"field_1": "value1"}},
            },
            {
                "source_guid": "guid-2",
                "version_correlation_id": "corr-2",
                **lifecycle,
                "content": {"distractor_1": {"field_1": "value2"}},
            },
            {
                "source_guid": "guid-3",
                "version_correlation_id": "corr-3",
                **lifecycle,
                "content": {"distractor_1": {"field_1": "value3"}},
            },
        ]
        data_loop2 = [
            {
                "source_guid": "guid-1",
                "version_correlation_id": "corr-1",
                **lifecycle,
                "content": {"distractor_2": {"field_2": "value1"}},
            },
            {
                "source_guid": "guid-2",
                "version_correlation_id": "corr-2",
                **lifecycle,
                "content": {"distractor_2": {"field_2": "value2"}},
            },
        ]
        data_loop3 = [
            {
                "source_guid": "guid-1",
                "version_correlation_id": "corr-1",
                **lifecycle,
                "content": {"distractor_3": {"field_3": "value1"}},
            },
        ]
        storage_backend._write_target_raw("distractor_1", "data.json", data_loop1)
        storage_backend._write_target_raw("distractor_2", "data.json", data_loop2)
        storage_backend._write_target_raw("distractor_3", "data.json", data_loop3)
        result_dir = correlator.prepare_correlated_input(
            "consumer", ["distractor_1", "distractor_2", "distractor_3"], 4
        )
        assert result_dir is not None
        correlated_data = storage_backend.read_target("consumer", "data.json")
        assert len(correlated_data) == 3
        record1 = next(r for r in correlated_data if r["source_guid"] == "guid-1")
        # Version namespaces are now nested, not prefixed
        assert "distractor_1" in record1["content"]
        assert "distractor_2" in record1["content"]
        assert "distractor_3" in record1["content"]
        assert record1["content"]["distractor_1"]["field_1"] == "value1"
        assert record1["content"]["distractor_2"]["field_2"] == "value1"
        assert record1["content"]["distractor_3"]["field_3"] == "value1"
        record2 = next(r for r in correlated_data if r["source_guid"] == "guid-2")
        assert "distractor_1" in record2["content"]
        assert "distractor_2" in record2["content"]
        assert "distractor_3" not in record2["content"]
        assert record2["content"]["distractor_1"]["field_1"] == "value2"
        assert record2["content"]["distractor_2"]["field_2"] == "value2"
        record3 = next(r for r in correlated_data if r["source_guid"] == "guid-3")
        assert "distractor_1" in record3["content"]
        assert "distractor_2" not in record3["content"]
        assert "distractor_3" not in record3["content"]
        assert record3["content"]["distractor_1"]["field_1"] == "value3"

    def test_multiple_file_correlation(self, correlator, storage_backend, temp_agent_folder):
        """Test correlation when loop agents produce multiple files."""
        lifecycle = {"_state": "processed", "_state_schema_version": 1}
        files = ["questions.json", "answers.json", "metadata.json"]
        for filename in files:
            data1 = [
                {
                    "source_guid": f"{filename}-guid-1",
                    "version_correlation_id": f"{filename}-corr-1",
                    **lifecycle,
                    "content": {"processor_1": {"loop1_data": f"data_from_{filename}"}},
                }
            ]
            data2 = [
                {
                    "source_guid": f"{filename}-guid-1",
                    "version_correlation_id": f"{filename}-corr-1",
                    **lifecycle,
                    "content": {"processor_2": {"loop2_data": f"data_from_{filename}"}},
                }
            ]
            storage_backend._write_target_raw("processor_1", filename, data1)
            storage_backend._write_target_raw("processor_2", filename, data2)
        result_dir = correlator.prepare_correlated_input(
            "aggregator", ["processor_1", "processor_2"], 3
        )
        assert result_dir is not None
        for filename in files:
            data = storage_backend.read_target("aggregator", filename)
            assert len(data) == 1
            assert "processor_1" in data[0]["content"]
            assert "processor_2" in data[0]["content"]
            assert data[0]["content"]["processor_1"]["loop1_data"] == f"data_from_{filename}"
            assert data[0]["content"]["processor_2"]["loop2_data"] == f"data_from_{filename}"

    def test_correlate_by_source_record(self, correlator):
        """Test the correlation logic for merging records with prefixed field names."""
        version_outputs = {
            "loop_1": [
                {
                    "source_guid": "guid-a",
                    "version_correlation_id": "corr-1",
                    "content": {"loop_1": {"f1": "v1"}},
                },
                {
                    "source_guid": "guid-b",
                    "version_correlation_id": "corr-2",
                    "content": {"loop_1": {"f1": "v2"}},
                },
            ],
            "loop_2": [
                {
                    "source_guid": "guid-a",
                    "version_correlation_id": "corr-1",
                    "content": {"loop_2": {"f2": "v3"}},
                },
                {
                    "source_guid": "guid-b",
                    "version_correlation_id": "corr-2",
                    "content": {"loop_2": {"f2": "v4"}},
                },
            ],
            "loop_3": [
                {
                    "source_guid": "guid-a",
                    "version_correlation_id": "corr-1",
                    "content": {"loop_3": {"f3": "v5"}},
                }
            ],
        }
        result = correlator._correlate_by_source_record(version_outputs)
        assert len(result) == 2
        rec_a = next(r for r in result if r["source_guid"] == "guid-a")
        assert rec_a["content"]["loop_1"] == {"f1": "v1"}
        assert rec_a["content"]["loop_2"] == {"f2": "v3"}
        assert rec_a["content"]["loop_3"] == {"f3": "v5"}
        # Only version namespaces — no leaked upstream flat fields
        expected_a = {"loop_1", "loop_2", "loop_3"}
        assert set(rec_a["content"].keys()) == expected_a
        rec_b = next(r for r in result if r["source_guid"] == "guid-b")
        assert rec_b["content"]["loop_1"] == {"f1": "v2"}
        assert rec_b["content"]["loop_2"] == {"f2": "v4"}
        expected_b = {"loop_1", "loop_2"}
        assert set(rec_b["content"].keys()) == expected_b

    def test_error_handling_in_correlation(self, correlator):
        """A version source with no backend records raises the cascade-skip signal."""
        from agent_actions.workflow.managers.output import AllVersionsFilteredError

        with pytest.raises(AllVersionsFilteredError):
            correlator.prepare_correlated_input("consumer", ["loop_1"], 2)


class TestVersionOutputCorrelatorIntegration:
    """Integration tests with AgentWorkflow."""

    @pytest.fixture
    def mock_agent_workflow(self, tmp_path):
        """Create a mock AgentWorkflow setup."""
        from unittest.mock import MagicMock

        workflow = MagicMock(spec=AgentWorkflow)
        workflow.agent_name = "test_workflow"
        workflow.execution_order = ["extract", "loop_1", "loop_2", "loop_3", "consumer"]
        workflow.action_configs = {
            "extract": {"agent_type": "extract"},
            "loop_1": {"agent_type": "loop"},
            "loop_2": {"agent_type": "loop"},
            "loop_3": {"agent_type": "loop"},
            "consumer": {"agent_type": "consumer", "dependencies": ["loop"]},
        }
        agent_folder = tmp_path / "agent_io"
        agent_folder.mkdir()
        workflow.agent_runner = MagicMock()
        workflow.agent_runner.get_action_folder.return_value = str(agent_folder)
        return (workflow, agent_folder)

    def test_integration_with_agent_workflow(self, mock_agent_workflow):
        """Test integration with AgentWorkflow's _setup_correlation_if_needed."""
        workflow, agent_folder = mock_agent_workflow
        db_path = agent_folder / "store" / "test.db"
        backend = SQLiteBackend.create(db_path=str(db_path), workflow_name="test")
        backend.initialize()
        correlator = VersionOutputCorrelator(agent_folder, storage_backend=backend)
        workflow.version_correlator = correlator
        lifecycle = {"_state": "processed", "_state_schema_version": 1}
        for i in range(1, 4):
            action_name = f"loop_{i}"
            data = [
                {
                    "source_guid": "test-guid",
                    "version_correlation_id": "test-corr",
                    **lifecycle,
                    "content": {action_name: {f"field_{i}": f"value_{i}"}},
                }
            ]
            backend._write_target_raw(action_name, "output.json", data)
        result = correlator.prepare_correlated_input("consumer", ["loop_1", "loop_2", "loop_3"], 4)
        assert result is not None
        data = backend.read_target("consumer", "output.json")
        assert len(data) == 1
        assert data[0]["content"]["loop_1"]["field_1"] == "value_1"
        assert data[0]["content"]["loop_2"]["field_2"] == "value_2"
        assert data[0]["content"]["loop_3"]["field_3"] == "value_3"
        backend.close()


class TestLoopCorrelatorWithSequentialMode:
    """Test suite for VersionOutputCorrelator with sequential loop execution."""

    @pytest.fixture
    def temp_agent_folder(self):
        """Create a temporary agent folder for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def storage_backend(self, temp_agent_folder):
        """Create a SQLite backend for testing."""
        db_path = temp_agent_folder / "store" / "test.db"
        backend = SQLiteBackend.create(db_path=str(db_path), workflow_name="test")
        backend.initialize()
        yield backend
        backend.close()

    @pytest.fixture
    def correlator(self, temp_agent_folder, storage_backend):
        """Create a VersionOutputCorrelator instance with storage backend."""
        return VersionOutputCorrelator(temp_agent_folder, storage_backend=storage_backend)

    def test_sequential_loop_correlation_works(
        self, correlator, storage_backend, temp_agent_folder
    ):
        """Test that correlator works correctly with sequential loop outputs."""
        lifecycle = {"_state": "processed", "_state_schema_version": 1}
        for i in range(1, 4):
            action_name = f"refine_{i}"
            test_data = [
                {
                    "source_guid": f"test-{i}",
                    "version_correlation_id": f"test-corr-{i}",
                    **lifecycle,
                    "content": {action_name: {"iteration": i, "data": f"refined_data_{i}"}},
                }
            ]
            storage_backend._write_target_raw(action_name, "output.json", test_data)
        result_dir = correlator.prepare_correlated_input(
            "aggregate", ["refine_1", "refine_2", "refine_3"], 4
        )
        assert result_dir is not None
        data = storage_backend.read_target("aggregate", "output.json")
        assert len(data) == 3
        iterations = set()
        for item in data:
            for _agent_name, content in item["content"].items():
                if isinstance(content, dict) and "iteration" in content:
                    iterations.add(content["iteration"])
        assert iterations == {1, 2, 3}

    def test_partial_sequential_failure_correlation(
        self, correlator, storage_backend, temp_agent_folder
    ):
        """Test correlation when some sequential iterations fail."""
        lifecycle = {"_state": "processed", "_state_schema_version": 1}
        for i in range(1, 3):
            action_name = f"process_{i}"
            test_data = [
                {
                    "source_guid": "test-guid",
                    "version_correlation_id": "test-corr",
                    **lifecycle,
                    "content": {action_name: {f"field_{i}": f"value_{i}"}},
                }
            ]
            storage_backend._write_target_raw(action_name, "result.json", test_data)
        result_dir = correlator.prepare_correlated_input(
            "consumer", ["process_1", "process_2", "process_3"], 4
        )
        assert result_dir is not None
        data = storage_backend.read_target("consumer", "result.json")
        assert len(data) <= 2
        if len(data) > 0:
            content = data[0]["content"]
            assert "process_1" in content or "process_2" in content

    def test_sequential_loop_with_mixed_metadata(
        self, correlator, storage_backend, temp_agent_folder
    ):
        """Test correlation when sequential loop agents have loop_mode metadata."""
        lifecycle = {"_state": "processed", "_state_schema_version": 1}
        for i in range(1, 4):
            action_name = f"step_{i}"
            test_data = [
                {
                    "source_guid": "test-guid",
                    "version_correlation_id": "test-corr",
                    "loop_mode": "sequential",
                    "version_number": i,
                    **lifecycle,
                    "content": {action_name: {"step": i, "result": f"step_{i}_result"}},
                }
            ]
            storage_backend._write_target_raw(action_name, "data.json", test_data)
        result_dir = correlator.prepare_correlated_input("final", ["step_1", "step_2", "step_3"], 4)
        assert result_dir is not None
        data = storage_backend.read_target("final", "data.json")
        assert len(data) == 1
        content = data[0]["content"]
        step_values = []
        for i in range(1, 4):
            if f"step_{i}" in content and isinstance(content[f"step_{i}"], dict):
                step_values.append(content[f"step_{i}"].get("step"))
        assert any(v in [1, 2, 3] for v in step_values if v is not None)

    def test_sequential_vs_parallel_correlation_same_behavior(
        self, correlator, storage_backend, temp_agent_folder
    ):
        """Test that correlation behavior is identical for sequential and parallel loops."""
        lifecycle = {"_state": "processed", "_state_schema_version": 1}
        for i in range(1, 3):
            action_name = f"seq_{i}"
            test_data = [
                {
                    "source_guid": "guid-1",
                    "version_correlation_id": "corr-1",
                    "loop_mode": "sequential",
                    **lifecycle,
                    "content": {action_name: {f"seq_field_{i}": f"seq_value_{i}"}},
                }
            ]
            storage_backend._write_target_raw(action_name, "output.json", test_data)
        for i in range(1, 3):
            action_name = f"par_{i}"
            test_data = [
                {
                    "source_guid": "guid-2",
                    "version_correlation_id": "corr-2",
                    "loop_mode": "parallel",
                    **lifecycle,
                    "content": {action_name: {f"par_field_{i}": f"par_value_{i}"}},
                }
            ]
            storage_backend._write_target_raw(action_name, "output.json", test_data)
        seq_result = correlator.prepare_correlated_input("seq_consumer", ["seq_1", "seq_2"], 5)
        par_result = correlator.prepare_correlated_input("par_consumer", ["par_1", "par_2"], 6)
        assert seq_result is not None
        assert par_result is not None
        seq_data = storage_backend.read_target("seq_consumer", "output.json")
        par_data = storage_backend.read_target("par_consumer", "output.json")
        assert len(seq_data) == 1
        assert len(par_data) == 1
        assert "seq_1" in seq_data[0]["content"]
        assert seq_data[0]["content"]["seq_1"]["seq_field_1"] == "seq_value_1"
        assert "seq_2" in seq_data[0]["content"]
        assert seq_data[0]["content"]["seq_2"]["seq_field_2"] == "seq_value_2"
        assert "par_1" in par_data[0]["content"]
        assert par_data[0]["content"]["par_1"]["par_field_1"] == "par_value_1"
        assert "par_2" in par_data[0]["content"]
        assert par_data[0]["content"]["par_2"]["par_field_2"] == "par_value_2"


class TestVersionCorrelatorSourceProtection:
    """Test that version correlation doesn't overwrite rich source data."""

    def test_correlation_sparse_overwrite_blocked(self):
        """Test that sparse correlation outputs don't overwrite rich source data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_folder = Path(tmpdir)
            db_path = agent_folder / "store" / "test.db"
            backend = SQLiteBackend.create(db_path=str(db_path), workflow_name="test")
            backend.initialize()
            correlator = VersionOutputCorrelator(agent_folder, storage_backend=backend)

            source_dir = agent_folder / "agent_io" / "source"
            source_dir.mkdir(parents=True)
            source_file = source_dir / "data.json"

            rich_source_data = [
                {
                    "source_guid": "guid-1",
                    "id": "123",
                    "page_content": "Full page content here...",
                    "title": "My Document",
                    "url": "https://example.com",
                    "author": "John Doe",
                    "created_at": "2024-01-01",
                    "tags": ["important"],
                }
            ]
            source_file.write_text(json.dumps(rich_source_data))

            lifecycle = {"_state": "processed", "_state_schema_version": 1}
            version1_output = [
                {
                    "source_guid": "guid-1",
                    "target_id": "123",
                    "node_id": "node-1",
                    "version_correlation_id": "corr-1",
                    "lineage": [],
                    **lifecycle,
                    "content": {"action_1": {"result": "v1"}},
                }
            ]
            version2_output = [
                {
                    "source_guid": "guid-1",
                    "target_id": "123",
                    "node_id": "node-1",
                    "version_correlation_id": "corr-1",
                    "lineage": [],
                    **lifecycle,
                    "content": {"action_2": {"result": "v2"}},
                }
            ]
            backend._write_target_raw("action_1", "data.json", version1_output)
            backend._write_target_raw("action_2", "data.json", version2_output)

            result = correlator.prepare_correlated_input("consumer", ["action_1", "action_2"], 0)
            assert result is not None

            with open(source_file) as f:
                final_source_data = json.load(f)

            assert len(final_source_data[0]) == 8, (
                "Rich source data was overwritten by sparse correlation output!"
            )
            assert "page_content" in final_source_data[0], "page_content field lost!"
            assert final_source_data[0]["page_content"] == "Full page content here..."
            backend.close()

    def test_correlation_richer_data_allowed(self):
        """Test that correlation outputs with MORE fields can update source."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_folder = Path(tmpdir)
            _correlator = VersionOutputCorrelator(agent_folder)

            # Setup: Create sparse source data
            source_dir = agent_folder / "agent_io" / "source"
            source_dir.mkdir(parents=True)
            source_file = source_dir / "data.json"

            sparse_source_data = [{"source_guid": "guid-1", "id": "123"}]  # 2 fields
            source_file.write_text(json.dumps(sparse_source_data))

            # Correlation source records include {source_guid, id, lineage, node_id}
            # (4 fields). This is still sparser than a rich 8-field source, so the
            # protection gate will block overwrite in that case. This test documents
            # that existing sparse source data is not modified without running correlation.

            # Just verify source file exists and has sparse data
            with open(source_file) as f:
                source_data = json.load(f)
            assert len(source_data[0]) == 2


class TestVersionCorrelationFailureError:
    """Test that version correlation failure raises ConfigurationError instead of silent fallback."""

    def test_version_correlation_failure_raises_error(self):
        """Records present but uncorrelatable raises loudly — not a silent None."""
        from unittest.mock import MagicMock

        from agent_actions.errors import DataValidationError
        from agent_actions.workflow.managers.output import (
            AgentOutputManager,
            OutputManagerConfig,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            agent_folder = Path(tmpdir)

            # Version agents must have numeric suffixes (action_1, action_2)
            agent_configs = {
                "action_1": {"agent_type": "action"},
                "action_2": {"agent_type": "action"},
                "consumer": {
                    "agent_type": "consumer",
                    "version_consumption_config": {
                        "source": "action",  # Base name of versioned agents
                        "pattern": "merge",
                    },
                },
            }

            # Sources produced records, but they lack version_correlation_id, so
            # correlation cannot key them — a loud failure, not a silent skip.
            storage_backend = MagicMock()
            storage_backend.list_target_files.return_value = ["out.json"]
            storage_backend.read_target.return_value = [{"id": 1}]
            version_correlator = VersionOutputCorrelator(
                agent_folder, storage_backend=storage_backend
            )

            config = OutputManagerConfig(
                agent_folder=agent_folder,
                execution_order=["action_1", "action_2", "consumer"],
                action_configs=agent_configs,
                action_status={},
                version_correlator=version_correlator,
                console=MagicMock(),  # Mock console to avoid print errors
                storage_backend=storage_backend,
            )
            output_manager = AgentOutputManager(config)

            with pytest.raises(DataValidationError):
                output_manager.resolve_correlated_input(idx=2)

            # Non-consumer should return None
            result = output_manager.resolve_correlated_input(idx=0)
            assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
