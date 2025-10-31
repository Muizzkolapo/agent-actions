"""Integration tests for historical node field referencing ({action_name.field})."""
import pytest
import json
import tempfile
from pathlib import Path
from agent_actions.prompt_generation.data_generator import DataGenerator
from agent_actions.preprocessing.historical_node_loader import HistoricalNodeDataLoader
from agent_actions.orchestration.node_mapper import NodeMappingService


class TestHistoricalNodeFieldReferencing:
    """Integration tests for {action_name.field} referencing."""

    @pytest.fixture
    def temp_target_dir(self):
        """Create a temporary target directory structure with test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir) / "target"

            # Create node_0_fact_extractor directory with test data
            node_0_dir = target_dir / "node_0_fact_extractor"
            node_0_dir.mkdir(parents=True)

            node_0_data = [
                {
                    "source_guid": "test-guid-123",
                    "node_id": "node_0_abc123",
                    "content": {
                        "candidate_facts_list": [
                            {
                                "fact": "Azure AutoML supports distributed training",
                                "quote": "Automated ML provides distributed training",
                                "technical_level": "implementation"
                            }
                        ]
                    }
                }
            ]

            with open(node_0_dir / "test_file.json", "w") as f:
                json.dump(node_0_data, f)

            # Create node_1_flatten_facts directory with test data
            node_1_dir = target_dir / "node_1_flatten_facts"
            node_1_dir.mkdir(parents=True)

            node_1_data = [
                {
                    "source_guid": "test-guid-123",
                    "node_id": "node_1_def456",
                    "content": {
                        "fact": "Azure AutoML supports distributed training",
                        "quote": "Automated ML provides distributed training",
                        "technical_level": "implementation"
                    },
                    "lineage": ["node_0_abc123", "node_1_def456"]
                }
            ]

            with open(node_1_dir / "test_file.json", "w") as f:
                json.dump(node_1_data, f)

            # Create node_2_cluster_list directory (current processing location)
            node_2_dir = target_dir / "node_2_cluster_list"
            node_2_dir.mkdir(parents=True)

            yield tmpdir

    def test_historical_node_data_loading(self, temp_target_dir):
        """Test loading historical node data from target files."""
        # Setup
        lineage = ["node_0_abc123", "node_1_def456"]
        source_guid = "test-guid-123"
        file_path = str(Path(temp_target_dir) / "target" / "node_2_cluster_list" / "test_file.json")
        agent_indices = {
            "fact_extractor": 0,
            "flatten_facts": 1,
            "cluster_list": 2
        }

        # Execute - Load data from node_0_fact_extractor
        result = HistoricalNodeDataLoader.load_historical_node_data(
            action_name="fact_extractor",
            lineage=lineage,
            source_guid=source_guid,
            file_path=file_path,
            agent_indices=agent_indices
        )

        # Assert
        assert result is not None
        assert "candidate_facts_list" in result
        assert len(result["candidate_facts_list"]) == 1
        assert result["candidate_facts_list"][0]["fact"] == "Azure AutoML supports distributed training"

    def test_build_field_context_with_historical_data(self, temp_target_dir):
        """Test that _build_namespaced_field_context loads historical data."""
        # Setup agent configs
        agent_config = {
            "dependencies": ["fact_extractor", "flatten_facts"],
            "prompt": "Test prompt with {fact_extractor.candidate_facts_list}"
        }

        dependency_configs = {
            "fact_extractor": {
                "output": ["candidate_facts_list"]
            },
            "flatten_facts": {
                "output": ["fact", "quote", "technical_level"]
            }
        }

        agent_indices = {
            "fact_extractor": 0,
            "flatten_facts": 1,
            "cluster_list": 2
        }

        # Create DataGenerator
        generator = DataGenerator(
            agent_config=agent_config,
            agent_name="cluster_list",
            dependency_configs=dependency_configs,
            agent_indices=agent_indices
        )

        # Setup current item with lineage
        current_item = {
            "source_guid": "test-guid-123",
            "lineage": ["node_0_abc123", "node_1_def456"],
            "content": {
                "fact": "Azure AutoML supports distributed training",
                "quote": "Automated ML provides distributed training"
            }
        }

        file_path = str(Path(temp_target_dir) / "target" / "node_2_cluster_list" / "test_file.json")

        # Execute
        field_context = generator._build_namespaced_field_context(
            contents=current_item["content"],
            source_content={"page_content": "Original source text"},
            current_item=current_item,
            file_path=file_path
        )

        # Assert
        assert "source" in field_context
        assert "fact_extractor" in field_context
        assert "candidate_facts_list" in field_context["fact_extractor"]
        assert len(field_context["fact_extractor"]["candidate_facts_list"]) == 1

        # Also check that flatten_facts data is present (from flat contents)
        assert "flatten_facts" in field_context
        assert field_context["flatten_facts"]["fact"] == "Azure AutoML supports distributed training"

    def test_full_prompt_formatting_with_historical_references(self, temp_target_dir):
        """Test complete prompt formatting with {action_name.field} references."""
        # Setup
        agent_config = {
            "dependencies": ["fact_extractor", "flatten_facts"],
            "prompt": """Create clusters from:
Current fact: {flatten_facts.fact}
Original extraction: {fact_extractor.candidate_facts_list}
Source: {source.page_content}"""
        }

        dependency_configs = {
            "fact_extractor": {
                "output": ["candidate_facts_list"]
            },
            "flatten_facts": {
                "output": ["fact", "quote", "technical_level"]
            }
        }

        agent_indices = {
            "fact_extractor": 0,
            "flatten_facts": 1,
            "cluster_list": 2
        }

        generator = DataGenerator(
            agent_config=agent_config,
            agent_name="cluster_list",
            dependency_configs=dependency_configs,
            agent_indices=agent_indices
        )

        current_item = {
            "source_guid": "test-guid-123",
            "lineage": ["node_0_abc123", "node_1_def456"],
            "content": {
                "fact": "Azure AutoML supports distributed training",
                "quote": "Automated ML provides distributed training"
            }
        }

        source_content = {"page_content": "Original Azure documentation"}
        file_path = str(Path(temp_target_dir) / "target" / "node_2_cluster_list" / "test_file.json")

        # Execute
        formatted_prompt, contents, llm_context, passthrough_fields = generator._format_prompt(
            contents=current_item["content"],
            source_content=source_content,
            current_item=current_item,
            file_path=file_path
        )

        # Assert
        assert "Azure AutoML supports distributed training" in formatted_prompt
        assert "Original Azure documentation" in formatted_prompt
        assert "candidate_facts_list" not in formatted_prompt  # Should be replaced
        assert "fact_extractor" not in formatted_prompt  # Should be replaced

    def test_node_mapping_service_integration(self):
        """Test NodeMappingService builds correct indices."""
        agent_configs = {
            "fact_extractor": {"idx": 0, "agent_type": "fact_extractor"},
            "flatten_facts": {"idx": 1, "agent_type": "flatten_facts"},
            "cluster_list": {"idx": 2, "agent_type": "cluster_list", "dependencies": ["fact_extractor", "flatten_facts"]}
        }

        agent_indices = NodeMappingService.build_agent_index_map(agent_configs)

        assert agent_indices == {
            "fact_extractor": 0,
            "flatten_facts": 1,
            "cluster_list": 2
        }

    def test_loading_multiple_dependencies(self, temp_target_dir):
        """Test loading data from multiple historical nodes."""
        lineage = ["node_0_abc123", "node_1_def456"]
        source_guid = "test-guid-123"
        file_path = str(Path(temp_target_dir) / "target" / "node_2_cluster_list" / "test_file.json")
        agent_indices = {
            "fact_extractor": 0,
            "flatten_facts": 1,
            "cluster_list": 2
        }

        # Load from node_0
        result_0 = HistoricalNodeDataLoader.load_historical_node_data(
            action_name="fact_extractor",
            lineage=lineage,
            source_guid=source_guid,
            file_path=file_path,
            agent_indices=agent_indices
        )

        # Load from node_1
        result_1 = HistoricalNodeDataLoader.load_historical_node_data(
            action_name="flatten_facts",
            lineage=lineage,
            source_guid=source_guid,
            file_path=file_path,
            agent_indices=agent_indices
        )

        # Assert both loaded successfully
        assert result_0 is not None
        assert result_1 is not None
        assert "candidate_facts_list" in result_0
        assert "fact" in result_1

    def test_graceful_handling_of_missing_historical_data(self):
        """Test that missing historical data doesn't break processing."""
        generator = DataGenerator(
            agent_config={"dependencies": ["fact_extractor"], "prompt": "Test {fact_extractor.field}"},
            agent_name="cluster_list",
            dependency_configs={"fact_extractor": {"output": ["field"]}},
            agent_indices={"fact_extractor": 0, "cluster_list": 1}
        )

        current_item = {
            "source_guid": "test-guid-123",
            "lineage": ["node_0_abc123"],
            "content": {}
        }

        # This should not raise an exception even though file doesn't exist
        field_context = generator._build_namespaced_field_context(
            contents={},
            current_item=current_item,
            file_path="/nonexistent/path/file.json"
        )

        # Should return context without the historical data
        assert isinstance(field_context, dict)
