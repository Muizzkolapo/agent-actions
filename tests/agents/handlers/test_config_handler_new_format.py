"""
Test suite for ConfigManager new format integration.

This test suite consolidates all tests related to the new action-based workflow format,
including config hierarchy, plan parsing, chunking, and project-level configuration.
"""

import pytest
import tempfile
import yaml
from pathlib import Path
from unittest.mock import Mock, patch
from typing import Dict, Any

from agent_actions.agents.handlers.config_handler import ConfigManager
from agent_actions.core.exceptions import ConfigurationError, ConfigValidationError


class TestNewFormatConfigHandlerIntegration:
    """Test ConfigManager with new action-based format."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def basic_new_format_workflow(self):
        """Basic new format workflow configuration."""
        return {
            "name": "test_workflow",
            "description": "Test workflow in new format",
            "version": "2.0.0",
            "defaults": {
                "model_vendor": "openai",
                'api_key': 'TEST_API_KEY',
                "model_name": "gpt-4"
            },
            "actions": [
                {
                    "name": "extract_data",
                    "intent": "Extract structured data from content",
                    "kind": "llm",
                    "reads": ["content"],
                    "writes": ["extracted_data"],
                    "prompt": "Extract data from the content"
                },
                {
                    "name": "process_data",
                    "intent": "Process extracted data",
                    "kind": "llm",
                    "reads": ["extracted_data"],
                    "writes": ["processed_data"],
                    "prompt": "Process the extracted data"
                }
            ],
            "plan": [
                "extract_data",
                "process_data <- extract_data"
            ]
        }

    @pytest.fixture
    def project_config(self):
        """Project-level configuration (agent_actions.yml)."""
        return {
            "default_agent_config": {
                "model_name": "gpt-4-project-default",
                "model_vendor": "openai",
                "api_key": "TEST_API_KEY",
                "chunk_config": {
                    "chunk_size": 800,
                    "chunk_overlap": 150
                },
                "is_operational": True,
                "run_mode": "online",
                "json_mode": False,
                "granularity": "record",
                "few_shot": 2
            },
            "tool_path": "project_tools/"
        }

    @pytest.fixture
    def hierarchy_test_workflow(self):
        """Workflow for testing configuration hierarchy."""
        return {
            "name": "test_project_hierarchy",
            "description": "Test workflow with project config integration",
            "version": "2.0.0",
            "defaults": {
                "model_name": "gpt-4o-mini-workflow",
                "model_vendor": "openai",
                "api_key": "TEST_API_KEY",
                "json_mode": True,
                "granularity": "file"
            },
            "actions": [
                {
                    "name": "action_with_project_inheritance",
                    "intent": "Action inheriting from project + workflow defaults",
                    "kind": "llm",
                    "reads": ["content"],
                    "writes": ["extracted_data"],
                    "prompt": "Extract using hierarchy: project < workflow < action"
                },
                {
                    "name": "action_with_overrides",
                    "intent": "Action overriding all levels",
                    "kind": "llm",
                    "model_name": "claude-3-sonnet",
                    "model_vendor": "anthropic",
                    "api_key": "TEST_API_KEY",
                    "json_mode": False,
                    "few_shot": 5,
                    "reads": ["extracted_data"],
                    "writes": ["processed_data"],
                    "prompt": "Process with action-level overrides"
                }
            ],
            "plan": [
                "action_with_project_inheritance",
                "action_with_overrides <- action_with_project_inheritance"
            ]
        }

    def create_test_files(self, temp_dir: Path, workflow: Dict[str, Any], project: Dict[str, Any] = None):
        """Helper to create test configuration files."""
        # Create workflow file
        workflow_file = temp_dir / "test_workflow.yml"
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f)

        # Create project config file if provided
        if project:
            project_file = temp_dir / "agent_actions.yml"
            with open(project_file, 'w') as f:
                yaml.dump(project, f)

        return str(workflow_file), str(project_file) if project else str(workflow_file)

    def test_basic_new_format_loading(self, temp_dir, basic_new_format_workflow):
        """Test basic loading of new format workflow."""
        workflow_path, default_path = self.create_test_files(
            temp_dir, basic_new_format_workflow, basic_new_format_workflow
        )

        config_manager = ConfigManager(workflow_path, default_path)
        config_manager.load_configs()

        assert config_manager.user_config is not None
        assert config_manager.user_config["name"] == "test_workflow"
        assert "actions" in config_manager.user_config
        assert len(config_manager.user_config["actions"]) == 2

    def test_new_format_agent_conversion(self, temp_dir, basic_new_format_workflow):
        """Test conversion from new format actions to agent format."""
        workflow_path, default_path = self.create_test_files(
            temp_dir, basic_new_format_workflow, basic_new_format_workflow
        )

        config_manager = ConfigManager(workflow_path, default_path)
        config_manager.load_configs()

        user_agents = config_manager.get_user_agents()

        assert len(user_agents) == 2

        # Check first agent
        extract_agent = next((a for a in user_agents if a['agent_type'] == 'extract_data'), None)
        assert extract_agent is not None
        assert extract_agent['name'] == 'extract_data'
        assert extract_agent['model_vendor'] == 'openai'  # Default
        assert extract_agent['model_name'] == 'gpt-4'  # Default
        assert extract_agent['dependencies'] == []

        # Check second agent with dependency
        process_agent = next((a for a in user_agents if a['agent_type'] == 'process_data'), None)
        assert process_agent is not None
        assert process_agent['name'] == 'process_data'
        assert process_agent['dependencies'] == ['extract_data']

    def test_plan_parsing_with_dependencies(self, temp_dir):
        """Test plan parsing extracts dependencies correctly."""
        workflow = {
            "name": "dependency_test",
            "description": "Test dependency parsing",
            "version": "2.0.0",
            "defaults": {
                "model_vendor": "openai",
                "model_name": "gpt-4",
                "api_key": "TEST_API_KEY"
            },
            "actions": [
                {
                    "name": "step1",
                    "intent": "First step",
                    "kind": "llm",
                    "reads": ["input"],
                    "writes": ["step1_output"],
                    "prompt": "Process step 1"
                },
                {
                    "name": "step2",
                    "intent": "Second step",
                    "kind": "llm",
                    "reads": ["step1_output"],
                    "writes": ["step2_output"],
                    "prompt": "Process step 2"
                },
                {
                    "name": "step3",
                    "intent": "Third step",
                    "kind": "llm",
                    "reads": ["step1_output", "step2_output"],
                    "writes": ["final_output"],
                    "prompt": "Process step 3"
                }
            ],
            "plan": [
                "step1",
                "step2 <- step1",
                "step3 <- step1, step2"
            ]
        }

        workflow_path, default_path = self.create_test_files(temp_dir, workflow, workflow)

        config_manager = ConfigManager(workflow_path, default_path)
        config_manager.load_configs()

        user_agents = config_manager.get_user_agents()

        assert len(user_agents) == 3

        # Check dependencies
        step1_agent = next((a for a in user_agents if a['agent_type'] == 'step1'), None)
        assert step1_agent['dependencies'] == []

        step2_agent = next((a for a in user_agents if a['agent_type'] == 'step2'), None)
        assert step2_agent['dependencies'] == ['step1']

        step3_agent = next((a for a in user_agents if a['agent_type'] == 'step3'), None)
        assert set(step3_agent['dependencies']) == {'step1', 'step2'}

    def test_plan_filters_actions_correctly(self, temp_dir):
        """Test that only actions mentioned in plan are included."""
        workflow = {
            "name": "filter_test",
            "description": "Test action filtering",
            "version": "2.0.0",
            "defaults": {
                "model_vendor": "openai",
                "model_name": "gpt-4",
                "api_key": "TEST_API_KEY"
            },
            "actions": [
                {
                    "name": "included_action",
                    "intent": "This action is in the plan",
                    "kind": "llm",
                    "reads": ["input"],
                    "writes": ["output"],
                    "prompt": "Process data"
                },
                {
                    "name": "excluded_action",
                    "intent": "This action is NOT in the plan",
                    "kind": "llm",
                    "reads": ["input"],
                    "writes": ["output"],
                    "prompt": "Process data"
                }
            ],
            "plan": [
                "included_action"
            ]
        }

        workflow_path, default_path = self.create_test_files(temp_dir, workflow, workflow)

        config_manager = ConfigManager(workflow_path, default_path)
        config_manager.load_configs()

        user_agents = config_manager.get_user_agents()

        # Should only include the action mentioned in plan
        assert len(user_agents) == 1
        assert user_agents[0]['agent_type'] == 'included_action'

    def test_chunking_configuration_support(self, temp_dir):
        """Test that chunking configuration is properly supported."""
        workflow = {
            "name": "chunking_test",
            "description": "Test chunking config support",
            "version": "2.0.0",
            "defaults": {
                "model_vendor": "openai",
                "model_name": "gpt-4",
                "api_key": "TEST_API_KEY",
                "chunk_config": {
                    "chunk_size": 1000,
                    "chunk_overlap": 200
                }
            },
            "actions": [
                {
                    "name": "chunked_action",
                    "intent": "Action with chunking config",
                    "kind": "llm",
                    "chunk_config": {
                        "chunk_size": 500,
                        "chunk_overlap": 100
                    },
                    "reads": ["content"],
                    "writes": ["processed"],
                    "prompt": "Process with chunking"
                }
            ],
            "plan": ["chunked_action"]
        }

        workflow_path, default_path = self.create_test_files(temp_dir, workflow, workflow)

        config_manager = ConfigManager(workflow_path, default_path)
        config_manager.load_configs()

        user_agents = config_manager.get_user_agents()

        assert len(user_agents) == 1
        agent = user_agents[0]

        # Should have action-level chunk config (overrides default)
        assert 'chunk_config' in agent
        assert agent['chunk_config']['chunk_size'] == 500
        assert agent['chunk_config']['chunk_overlap'] == 100

    def test_comprehensive_defaults_application(self, temp_dir):
        """Test that all default fields are properly applied."""
        workflow = {
            "name": "defaults_test",
            "description": "Test comprehensive defaults",
            "version": "2.0.0",
            "defaults": {
                "model_name": "gpt-4-default",
                "model_vendor": "openai",
                "api_key": "TEST_API_KEY",
                "json_mode": True,
                "granularity": "file",
                "run_mode": "offline",
                "few_shot": 3
            },
            "actions": [
                {
                    "name": "test_action",
                    "intent": "Action with defaults",
                    "kind": "llm",
                    "reads": ["input"],
                    "writes": ["output"],
                    "prompt": "Process data"
                }
            ],
            "plan": ["test_action"]
        }

        workflow_path, default_path = self.create_test_files(temp_dir, workflow, workflow)

        config_manager = ConfigManager(workflow_path, default_path)
        config_manager.load_configs()

        user_agents = config_manager.get_user_agents()

        assert len(user_agents) == 1
        agent = user_agents[0]

        # Check all defaults are applied
        assert agent['model_name'] == 'gpt-4-default'
        assert agent['model_vendor'] == 'openai'
        assert agent['json_mode'] is True
        assert agent['granularity'] == 'File'
        assert agent['run_mode'] == 'offline'
        assert agent['use_few_shot_samples'] == 3

    def test_project_config_hierarchy(self, temp_dir, hierarchy_test_workflow, project_config):
        """Test 3-level configuration hierarchy: project → workflow → action."""
        # Create actual project config file in temp directory
        project_file = temp_dir / "agent_actions.yml"
        with open(project_file, 'w') as f:
            yaml.dump(project_config, f)

        workflow_path, default_path = self.create_test_files(
            temp_dir, hierarchy_test_workflow, hierarchy_test_workflow
        )

        # Mock both the path manager and load_project_config functions
        with patch('agent_actions.core.context.path_manager.PathManager.get_project_root', return_value=str(temp_dir)), \
             patch('agent_actions.agents.handlers.config_handler.load_project_config', return_value=project_config):

            config_manager = ConfigManager(workflow_path, default_path)
            config_manager.load_configs()

            user_agents = config_manager.get_user_agents()

            assert len(user_agents) == 2

            # Test project → workflow → action inheritance
            inheritance_agent = next((a for a in user_agents if a['agent_type'] == 'action_with_project_inheritance'), None)
            assert inheritance_agent is not None

            # Should inherit from workflow defaults (overrides project)
            assert inheritance_agent['model_name'] == 'gpt-4o-mini-workflow'  # Workflow override
            assert inheritance_agent['json_mode'] is True                     # Workflow override
            assert inheritance_agent['granularity'] == 'File'                 # Workflow override

            # Should inherit from project defaults (not overridden by workflow)
            assert inheritance_agent['model_vendor'] == 'openai'              # Project default
            assert inheritance_agent['use_few_shot_samples'] == 2             # Project default

            # Check chunk config exists and has project default values
            assert 'chunk_config' in inheritance_agent
            chunk_config = inheritance_agent['chunk_config']
            if isinstance(chunk_config, dict) and 'chunk_size' in chunk_config:
                assert chunk_config['chunk_size'] == 800                      # Project default

            # Test action-level overrides
            override_agent = next((a for a in user_agents if a['agent_type'] == 'action_with_overrides'), None)
            assert override_agent is not None

            # Should use action-level overrides
            assert override_agent['model_name'] == 'claude-3-sonnet'          # Action override
            assert override_agent['model_vendor'] == 'anthropic'              # Action override
            assert override_agent['json_mode'] is False                       # Action override
            assert override_agent['use_few_shot_samples'] == 5                # Action override

    def test_tool_actions_handling(self, temp_dir):
        """Test handling of tool-type actions (kind: tool)."""
        # Create templates directory to avoid FileNotFoundError
        templates_dir = temp_dir / "templates"
        templates_dir.mkdir(exist_ok=True)

        workflow = {
            "name": "tool_test",
            "description": "Test tool action handling",
            "version": "2.0.0",
            "actions": [
                {
                    "name": "tool_action",
                    "intent": "Tool-based action",
                    "kind": "tool",
                    "impl": "custom_tool",
                    "reads": ["input"],
                    "writes": ["output"]
                }
            ],
            "plan": ["tool_action"]
        }

        workflow_path, default_path = self.create_test_files(temp_dir, workflow, workflow)

        with patch('pathlib.Path.cwd', return_value=temp_dir):
            config_manager = ConfigManager(workflow_path, default_path)
            config_manager.load_configs()

            user_agents = config_manager.get_user_agents()

        assert len(user_agents) == 1
        agent = user_agents[0]

        # Should set tool-specific properties
        assert agent['model_vendor'] == 'tool'
        assert agent['model_name'] == 'custom_tool'

    def test_tool_action_batch_mode_override(self, temp_dir):
        """Test that tool actions with batch defaults get overridden to online mode."""
        # Create templates directory to avoid FileNotFoundError
        templates_dir = temp_dir / "templates"
        templates_dir.mkdir(exist_ok=True)

        workflow = {
            "name": "tool_batch_test",
            "description": "Test tool action with batch mode defaults",
            "version": "2.0.0",
            "defaults": {
                "model_vendor": "openai",
                'api_key': 'TEST_API_KEY',
                "model_name": "gpt-4",
                "run_mode": "batch"  # Default to batch mode
            },
            "actions": [
                {
                    "name": "tool_action",
                    "intent": "Tool-based action",
                    "kind": "tool",
                    "impl": "custom_tool",
                    "reads": ["input"],
                    "writes": ["output"]
                }
            ],
            "plan": ["tool_action"]
        }

        workflow_path, default_path = self.create_test_files(temp_dir, workflow, workflow)

        with patch('pathlib.Path.cwd', return_value=temp_dir):
            config_manager = ConfigManager(workflow_path, default_path)
            config_manager.load_configs()

            user_agents = config_manager.get_user_agents()

        assert len(user_agents) == 1
        agent = user_agents[0]

        # Tool action should have run_mode overridden to 'online' even with batch defaults
        assert agent['model_vendor'] == 'tool'
        assert agent['model_name'] == 'custom_tool'
        assert agent['run_mode'] == 'online', "Tool actions should override batch mode to online"

    def test_tool_action_explicit_batch_mode_raises_error(self, temp_dir):
        """Test that explicitly setting batch mode on a tool action raises an error."""
        # Create templates directory to avoid FileNotFoundError
        templates_dir = temp_dir / "templates"
        templates_dir.mkdir(exist_ok=True)

        workflow = {
            "name": "tool_batch_error_test",
            "description": "Test tool action with explicit batch mode",
            "version": "2.0.0",
            "actions": [
                {
                    "name": "tool_action",
                    "intent": "Tool-based action",
                    "kind": "tool",
                    "impl": "custom_tool",
                    "run_mode": "batch",  # Explicitly set batch mode on tool action
                    "reads": ["input"],
                    "writes": ["output"]
                }
            ],
            "plan": ["tool_action"]
        }

        workflow_path, default_path = self.create_test_files(temp_dir, workflow, workflow)

        with patch('pathlib.Path.cwd', return_value=temp_dir):
            config_manager = ConfigManager(workflow_path, default_path)
            config_manager.load_configs()

            # Should raise ConfigurationError when trying to get user agents
            with pytest.raises(ConfigurationError) as exc_info:
                config_manager.get_user_agents()

        error_message = str(exc_info.value)
        assert "Tool actions do not support batch processing" in error_message
        # Context info is now in the error message
        assert "kind=tool" in error_message or "kind='tool'" in error_message
        assert "run_mode=batch" in error_message or "run_mode='batch'" in error_message

    def test_schema_handling(self, temp_dir):
        """Test handling of output schemas in actions."""
        workflow = {
            "name": "schema_test",
            "description": "Test schema handling",
            "version": "2.0.0",
            "defaults": {
                "model_vendor": "openai",
                "model_name": "gpt-4",
                "api_key": "TEST_API_KEY"
            },
            "actions": [
                {
                    "name": "schema_action",
                    "intent": "Action with output schema",
                    "kind": "llm",
                    "schema": "test_schema.json",
                    "reads": ["input"],
                    "writes": ["output"],
                    "prompt": "Extract with schema"
                }
            ],
            "plan": ["schema_action"]
        }

        workflow_path, default_path = self.create_test_files(temp_dir, workflow, workflow)

        config_manager = ConfigManager(workflow_path, default_path)
        config_manager.load_configs()

        user_agents = config_manager.get_user_agents()

        assert len(user_agents) == 1
        agent = user_agents[0]

        # Should have schema name
        assert 'schema_name' in agent
        assert agent['schema_name'] == 'test_schema.json'

    def test_error_handling_invalid_yaml(self, temp_dir):
        """Test error handling with invalid YAML."""
        # Create invalid YAML file
        workflow_file = temp_dir / "invalid.yml"
        workflow_file.write_text("invalid: yaml: content: [")

        config_manager = ConfigManager(str(workflow_file), str(workflow_file))

        with pytest.raises(ConfigurationError, match="Error rendering or loading user config"):
            config_manager.load_configs()

    def test_error_handling_missing_file(self):
        """Test error handling with missing configuration file."""
        config_manager = ConfigManager("/nonexistent/file.yml", "/nonexistent/default.yml")

        with pytest.raises(ConfigurationError):
            config_manager.load_configs()

    def test_backward_compatibility_check(self, temp_dir, basic_new_format_workflow):
        """Test that new format is correctly identified and processed."""
        workflow_path, default_path = self.create_test_files(
            temp_dir, basic_new_format_workflow, basic_new_format_workflow
        )

        config_manager = ConfigManager(workflow_path, default_path)
        config_manager.load_configs()

        # Should identify as new format (has 'name' and 'actions' keys)
        assert 'name' in config_manager.user_config
        assert 'actions' in config_manager.user_config

        # Should process as new format
        user_agents = config_manager.get_user_agents()
        assert len(user_agents) > 0

        # All agents should have required fields
        for agent in user_agents:
            assert 'agent_type' in agent
            assert 'name' in agent
            assert 'model_vendor' in agent
            assert 'model_name' in agent
            assert 'dependencies' in agent

    def test_execution_order_determination(self, temp_dir, basic_new_format_workflow):
        """Test execution order determination based on dependencies."""
        workflow_path, default_path = self.create_test_files(
            temp_dir, basic_new_format_workflow, basic_new_format_workflow
        )

        config_manager = ConfigManager(workflow_path, default_path)
        config_manager.load_configs()

        user_agents = config_manager.get_user_agents()
        config_manager.merge_agent_configs(user_agents)
        config_manager.determine_execution_order(user_agents)

        # Should have execution order based on dependencies
        assert len(config_manager.execution_order) == 2

        # extract_data should come before process_data (since process_data depends on extract_data)
        extract_index = config_manager.execution_order.index('extract_data')
        process_index = config_manager.execution_order.index('process_data')
        assert extract_index < process_index


class TestNewFormatFeatureIntegration:
    """Integration tests for new format features."""

    def test_end_to_end_new_format_processing(self, tmp_path):
        """Test complete end-to-end processing of new format workflow."""
        # Create comprehensive new format workflow
        workflow = {
            "name": "e2e_test",
            "description": "End-to-end test workflow",
            "version": "2.0.0",
            "defaults": {
                "model_name": "gpt-4",
                "model_vendor": "openai",
                "api_key": "TEST_API_KEY",
                "json_mode": False,
                "granularity": "record"
            },
            "actions": [
                {
                    "name": "extract",
                    "intent": "Extract data from content",
                    "kind": "llm",
                    "json_mode": True,  # Override default
                    "reads": ["raw_content"],
                    "writes": ["structured_data"],
                    "prompt": "Extract structured data"
                },
                {
                    "name": "validate",
                    "intent": "Validate extracted data",
                    "kind": "llm",
                    "granularity": "file",  # Override default
                    "reads": ["structured_data"],
                    "writes": ["validated_data"],
                    "prompt": "Validate the data"
                },
                {
                    "name": "transform",
                    "intent": "Transform validated data",
                    "kind": "llm",
                    "reads": ["validated_data"],
                    "writes": ["final_output"],
                    "prompt": "Transform the data"
                }
            ],
            "plan": [
                "extract",
                "validate <- extract",
                "transform <- validate"
            ]
        }

        # Create files
        workflow_file = tmp_path / "e2e_workflow.yml"
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f)

        # Process workflow
        config_manager = ConfigManager(str(workflow_file), str(workflow_file))
        config_manager.load_configs()

        # Get agents and process
        user_agents = config_manager.get_user_agents()
        config_manager.merge_agent_configs(user_agents)
        config_manager.determine_execution_order(user_agents)

        # Verify complete processing
        assert len(user_agents) == 3
        assert len(config_manager.execution_order) == 3

        # Verify configuration hierarchy worked
        extract_agent = next(a for a in user_agents if a['agent_type'] == 'extract')
        assert extract_agent['json_mode'] is True  # Override applied
        assert extract_agent['granularity'] == 'Record'  # Default applied

        validate_agent = next(a for a in user_agents if a['agent_type'] == 'validate')
        assert validate_agent['granularity'] == 'File'  # Override applied
        assert validate_agent['json_mode'] is False  # Default applied

        # Verify execution order respects dependencies
        extract_pos = config_manager.execution_order.index('extract')
        validate_pos = config_manager.execution_order.index('validate')
        transform_pos = config_manager.execution_order.index('transform')

        assert extract_pos < validate_pos < transform_pos

    def test_standard_field_names_all_present(self, tmp_path):
        """Test model_vendor/model_name are recognized as valid field names."""
        workflow = {
            "name": "test",
            "version": "1.0",
            "description": "Test standard field names",
            "defaults": {
                "model_vendor": "openai",
                "model_name": "gpt-4",
                "api_key": "DEFAULT_KEY"
            },
            "actions": [{
                "name": "test_action",
                "intent": "Test",
                "kind": "llm",
                "reads": [],
                "writes": [],
                "prompt": "test"
            }],
            "plan": ["test_action"]
        }

        workflow_file = tmp_path / "test.yml"
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f)

        config_manager = ConfigManager(str(workflow_file), str(workflow_file))
        config_manager.load_configs()
        user_agents = config_manager.get_user_agents()

        # Should use model_vendor/model_name from defaults
        test_agent = next(a for a in user_agents if a['agent_type'] == 'test_action')
        assert test_agent['model_vendor'] == 'openai'
        assert test_agent['model_name'] == 'gpt-4'
        assert test_agent['api_key'] == 'DEFAULT_KEY'

    def test_standard_field_names_at_workflow_level(self, tmp_path):
        """Test model_vendor/model_name work at workflow defaults level."""
        workflow = {
            "name": "test",
            "version": "1.0",
            "description": "Test workflow defaults",
            "defaults": {
                "model_vendor": "anthropic",
                "model_name": "claude-3-5-sonnet",
                "api_key": "WORKFLOW_KEY"
            },
            "actions": [{
                "name": "test_action",
                "intent": "Test",
                "kind": "llm",
                "reads": [],
                "writes": [],
                "prompt": "test"
            }],
            "plan": ["test_action"]
        }

        workflow_file = tmp_path / "test.yml"
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f)

        config_manager = ConfigManager(str(workflow_file), str(workflow_file))
        config_manager.load_configs()
        user_agents = config_manager.get_user_agents()

        # Should inherit from workflow defaults
        test_agent = next(a for a in user_agents if a['agent_type'] == 'test_action')
        assert test_agent['model_vendor'] == 'anthropic'
        assert test_agent['model_name'] == 'claude-3-5-sonnet'
        assert test_agent['api_key'] == 'WORKFLOW_KEY'

    def test_standard_field_names_at_action_level(self, tmp_path):
        """Test model_vendor/model_name work at action level."""
        workflow = {
            "name": "test",
            "version": "1.0",
            "description": "Test action-level config",
            "actions": [{
                "name": "test_action",
                "intent": "Test",
                "kind": "llm",
                "model_vendor": "openai",
                "model_name": "gpt-4o-mini",
                "api_key": "ACTION_KEY",
                "reads": [],
                "writes": [],
                "prompt": "test"
            }],
            "plan": ["test_action"]
        }

        workflow_file = tmp_path / "test.yml"
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f)

        config_manager = ConfigManager(str(workflow_file), str(workflow_file))
        config_manager.load_configs()
        user_agents = config_manager.get_user_agents()

        # Should use action-level values
        test_agent = next(a for a in user_agents if a['agent_type'] == 'test_action')
        assert test_agent['model_vendor'] == 'openai'
        assert test_agent['model_name'] == 'gpt-4o-mini'
        assert test_agent['api_key'] == 'ACTION_KEY'

    def test_standard_field_names_hierarchy_precedence(self, tmp_path):
        """Test precedence: action > workflow for model_vendor/model_name."""
        workflow = {
            "name": "test",
            "version": "1.0",
            "description": "Test hierarchy precedence",
            "defaults": {
                "model_vendor": "anthropic",
                "model_name": "claude-3-5-sonnet",
                "api_key": "WORKFLOW_KEY"
            },
            "actions": [{
                "name": "test_action",
                "intent": "Test",
                "kind": "llm",
                "model_vendor": "openai",  # Overrides workflow
                "model_name": "gpt-4o-mini",  # Overrides workflow
                "reads": [],
                "writes": [],
                "prompt": "test"
            }],
            "plan": ["test_action"]
        }

        workflow_file = tmp_path / "test.yml"
        with open(workflow_file, 'w') as f:
            yaml.dump(workflow, f)

        config_manager = ConfigManager(str(workflow_file), str(workflow_file))
        config_manager.load_configs()
        user_agents = config_manager.get_user_agents()

        # Action should win (highest precedence)
        test_agent = next(a for a in user_agents if a['agent_type'] == 'test_action')
        assert test_agent['model_vendor'] == 'openai'
        assert test_agent['model_name'] == 'gpt-4o-mini'
        assert test_agent['api_key'] == 'WORKFLOW_KEY'  # Inherited from workflow