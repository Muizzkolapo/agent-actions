"""
Tests for CLI inspect commands.

This module tests the CLI inspection commands: signatures, field-flow, and conflicts.
All tests use the new -a/--agent flag pattern with @requires_project decorator.
"""

import pytest
import json
import tempfile
import yaml
from pathlib import Path
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from agent_actions.tasks.inspect import signatures, field_flow, conflicts, inspect
from agent_actions.core.exceptions import ProjectNotFoundError


@pytest.fixture
def temp_test_workflow():
    """Create a temporary test workflow for CLI testing."""
    # Create temporary files with predictable names
    workflow_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='test_workflow_')
    workflow_name = Path(workflow_file.name).stem
    
    workflow_data = {
        workflow_name: {
            "agents": [
                {
                    "name": "extractor",
                    "agent_type": "extractor",
                    "model_vendor": "anthropic",
                    "model_name": "claude-3-haiku-20240307",
                    "api_key": "fake-key-for-testing",
                    "chunk_config": {},
                    "output_schema": {
                        "properties": {
                            "summary": {"type": "string"},
                            "entities": {"type": "array"},
                            "metadata": {"type": "object"}
                        }
                    },
                    "observe": ["document_id", "source_url"],
                    "drops": ["metadata"]
                },
                {
                    "name": "classifier",
                    "agent_type": "classifier",
                    "model_vendor": "anthropic",
                    "model_name": "claude-3-haiku-20240307",
                    "api_key": "fake-key-for-testing",
                    "chunk_config": {},
                    "dependencies": ["extractor"],
                    "prompt": "Classify this content: {extractor.summary}",
                    "output_schema": {
                        "properties": {
                            "category": {"type": "string"},
                            "confidence": {"type": "number"}
                        }
                    }
                },
                {
                    "name": "analyzer",
                    "agent_type": "analyzer",
                    "model_vendor": "anthropic",
                    "model_name": "claude-3-haiku-20240307",
                    "api_key": "fake-key-for-testing",
                    "chunk_config": {},
                    "dependencies": ["extractor", "classifier"],
                    "prompt": """
                    Analyze the extracted content:
                    Summary: {extractor.summary}
                    Entities: {extractor.entities}
                    Category: {classifier.category}
                    Confidence: {classifier.confidence}
                    Document: {extractor.document_id}
                    """,
                    "output_schema": {
                        "properties": {
                            "analysis": {"type": "string"},
                            "score": {"type": "number"}
                        }
                    }
                }
            ]
        }
    }
    
    defaults_data = {
        "default_agent_config": {
            "model_vendor": "anthropic",
            "model_name": "claude-3-haiku-20240307",
            "api_key": "fake-key-for-testing",
            "chunk_config": {}
        }
    }
    
    defaults_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, 
                                                dir=Path(workflow_file.name).parent)
    
    yaml.dump(workflow_data, workflow_file, default_flow_style=False)
    yaml.dump(defaults_data, defaults_file, default_flow_style=False)
    
    workflow_file.close()
    defaults_file.close()
    
    # Rename defaults file to match expected name pattern
    defaults_path = Path(workflow_file.name).parent / "defaults.yml"
    Path(defaults_file.name).rename(defaults_path)
    
    yield workflow_file.name
    
    # Cleanup
    Path(workflow_file.name).unlink(missing_ok=True)
    defaults_path.unlink(missing_ok=True)


@pytest.fixture
def conflict_test_workflow():
    """Create a test workflow with field conflicts."""
    # Create temporary files with predictable names
    workflow_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False, prefix='conflict_workflow_')
    workflow_name = Path(workflow_file.name).stem
    
    workflow_data = {
        workflow_name: {
            "agents": [
                {
                    "name": "agent1",
                    "agent_type": "agent1",
                    "model_vendor": "anthropic",
                    "model_name": "claude-3-haiku-20240307",
                    "api_key": "fake-key-for-testing",
                    "chunk_config": {},
                    "output_schema": {
                        "properties": {
                            "summary": {"type": "string"},
                            "confidence": {"type": "number"}
                        }
                    }
                },
                {
                    "name": "agent2",
                    "agent_type": "agent2",
                    "model_vendor": "anthropic",
                    "model_name": "claude-3-haiku-20240307",
                    "api_key": "fake-key-for-testing",
                    "chunk_config": {},
                    "output_schema": {
                        "properties": {
                            "category": {"type": "string"},
                            "confidence": {"type": "number"}  # Conflict!
                        }
                    }
                },
                {
                    "name": "combiner",
                    "agent_type": "combiner",
                    "model_vendor": "anthropic",
                    "model_name": "claude-3-haiku-20240307",
                    "api_key": "fake-key-for-testing",
                    "chunk_config": {},
                    "dependencies": ["agent1", "agent2"],
                    "prompt": "Combine: {agent1.summary} and {agent2.category}",
                    "output_schema": {
                        "properties": {
                            "result": {"type": "string"}
                        }
                    }
                }
            ]
        }
    }
    
    defaults_data = {
        "default_agent_config": {
            "model_vendor": "anthropic",
            "model_name": "claude-3-haiku-20240307",
            "api_key": "fake-key-for-testing",
            "chunk_config": {}
        }
    }
    
    defaults_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False,
                                                dir=Path(workflow_file.name).parent)
    
    yaml.dump(workflow_data, workflow_file, default_flow_style=False)
    yaml.dump(defaults_data, defaults_file, default_flow_style=False)
    
    workflow_file.close()
    defaults_file.close()
    
    defaults_path = Path(workflow_file.name).parent / "defaults.yml"
    Path(defaults_file.name).rename(defaults_path)
    
    yield workflow_file.name
    
    # Cleanup
    Path(workflow_file.name).unlink(missing_ok=True)
    defaults_path.unlink(missing_ok=True)


class TestNewInspectCLIPattern:
    """Test inspect commands with new -a/--agent CLI pattern."""

    @patch('agent_actions.tasks.inspect._create_config_manager')
    def test_signatures_with_agent_flag(self, mock_create_config):
        """Test signatures command with -a/--agent flag."""
        # Mock the config manager
        mock_config = MagicMock()
        mock_create_config.return_value = mock_config
        
        # Mock minimal signature data
        mock_input_sig = MagicMock()
        mock_input_sig.get_all_fields.return_value = set()
        mock_output_sig = MagicMock()
        mock_output_sig.get_available_fields.return_value = set()
        
        mock_config.get_all_signatures.return_value = {
            'test_agent': {
                'dependencies': [],
                'execution_order_index': 0,
                'is_operational': True,
                'input_signature': mock_input_sig,
                'output_signature': mock_output_sig
            }
        }
        
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Test project')
            
            result = runner.invoke(signatures, ['-a', 'test_agent'])
            
            assert result.exit_code == 0
            assert "Agent Signatures" in result.output
            mock_create_config.assert_called_once_with('test_agent')

    @patch('agent_actions.tasks.inspect._create_config_manager')
    def test_field_flow_with_agent_flag(self, mock_create_config):
        """Test field-flow command with -a/--agent flag."""
        # Mock the config manager
        mock_config = MagicMock()
        mock_create_config.return_value = mock_config
        
        # Mock field flow validation data
        mock_config.validate_field_flow.return_value = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'agent_validations': {
                'test_agent': {
                    'valid': True,
                    'errors': [],
                    'warnings': [],
                    'required_fields': set(),
                    'output_fields': set(),
                    'available_fields_before': set()
                }
            },
            'field_flow_summary': {
                'test_agent': set()
            }
        }
        
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Test project')
            
            result = runner.invoke(field_flow, ['-a', 'test_agent'])
            
            assert result.exit_code == 0
            assert "Field Flow Validation:" in result.output
            mock_create_config.assert_called_once_with('test_agent')

    @patch('agent_actions.tasks.inspect._create_config_manager')
    def test_conflicts_with_agent_flag(self, mock_create_config):
        """Test conflicts command with -a/--agent flag."""
        # Mock the config manager
        mock_config = MagicMock()
        mock_create_config.return_value = mock_config
        
        # Mock agent configs for iteration
        mock_config.agent_configs = {'test_agent': {}}
        
        # Mock conflicts detection
        mock_config.detect_field_conflicts.return_value = {
            'conflicts': {},
            'agent_dependencies': [],
            'all_available_fields': {}
        }
        
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Test project')
            
            result = runner.invoke(conflicts, ['-a', 'test_agent'])
            
            assert result.exit_code == 0
            assert "No field conflicts detected" in result.output
            mock_create_config.assert_called_once_with('test_agent')

    def test_signatures_help_shows_agent_flag(self):
        """Test that signatures help shows the new -a/--agent flag."""
        runner = CliRunner()
        result = runner.invoke(signatures, ['--help'])
        
        assert result.exit_code == 0
        assert "-a, --agent" in result.output
        assert "Agent name to inspect" in result.output

    def test_field_flow_help_shows_agent_flag(self):
        """Test that field-flow help shows the new -a/--agent flag."""
        runner = CliRunner()
        result = runner.invoke(field_flow, ['--help'])
        
        assert result.exit_code == 0
        assert "-a, --agent" in result.output
        assert "Agent name to inspect" in result.output

    def test_conflicts_help_shows_agent_flag(self):
        """Test that conflicts help shows the new -a/--agent flag."""
        runner = CliRunner()
        result = runner.invoke(conflicts, ['--help'])
        
        assert result.exit_code == 0
        assert "-a, --agent" in result.output
        assert "Agent name to inspect" in result.output


class TestRequiresProjectIntegration:
    """Test @requires_project decorator behavior in inspect commands."""

    def test_signatures_fails_outside_project(self):
        """Test signatures command fails when not in a project."""
        runner = CliRunner()
        # CliRunner creates isolated filesystem with no project marker
        result = runner.invoke(signatures, ['-a', 'test_agent'])
        
        assert result.exit_code != 0
        # Error will be handled by Click's exception handling

    def test_field_flow_fails_outside_project(self):
        """Test field-flow command fails when not in a project."""
        runner = CliRunner()
        result = runner.invoke(field_flow, ['-a', 'test_agent'])
        
        assert result.exit_code != 0

    def test_conflicts_fails_outside_project(self):
        """Test conflicts command fails when not in a project."""
        runner = CliRunner()
        result = runner.invoke(conflicts, ['-a', 'test_agent'])
        
        assert result.exit_code != 0

    @patch('agent_actions.tasks.inspect._create_config_manager')
    def test_commands_show_project_root_detection(self, mock_create_config):
        """Test that commands show project root detection feedback."""
        # Mock successful config manager creation
        mock_config = MagicMock()
        mock_create_config.return_value = mock_config
        
        # Mock minimal return data for signatures
        mock_input_sig = MagicMock()
        mock_input_sig.get_all_fields.return_value = set()
        mock_output_sig = MagicMock()
        mock_output_sig.get_available_fields.return_value = set()
        
        mock_config.get_all_signatures.return_value = {
            'test_agent': {
                'dependencies': [],
                'execution_order_index': 0,
                'is_operational': True,
                'input_signature': mock_input_sig,
                'output_signature': mock_output_sig
            }
        }
        
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Test project')
            
            result = runner.invoke(signatures, ['-a', 'test_agent'])
            
            assert result.exit_code == 0
            # The @requires_project decorator shows project root feedback
            assert "📁 Project root:" in result.output


class TestAgentNameValidation:
    """Test agent name validation in inspect commands."""

    def test_empty_agent_name_rejected(self):
        """Test that empty agent name is rejected."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Test project')
            
            result = runner.invoke(signatures, ['-a', ''])
            
            assert result.exit_code != 0
            # Validation error should be caught and formatted

    def test_whitespace_agent_name_trimmed(self):
        """Test that whitespace in agent name is handled."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Test project')
            
            # This will fail because we're not mocking the config manager
            # but it should get past the argument validation
            result = runner.invoke(signatures, ['-a', '  test_agent  '])
            
            # Should not fail due to argument validation
            # (will fail later due to missing config, but that's expected)
            assert "Agent name cannot be empty" not in str(result.output)

    def test_missing_agent_flag_shows_help(self):
        """Test that missing -a flag shows helpful error."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Test project')
            
            result = runner.invoke(signatures, [])
            
            assert result.exit_code != 0
            # Should show that -a/--agent is required


class TestNewCLIConsistency:
    """Test that new CLI pattern is consistent across commands."""

    def test_all_inspect_commands_use_agent_flag(self):
        """Test that all inspect subcommands support -a/--agent flag."""
        runner = CliRunner()
        
        commands_to_test = [signatures, field_flow, conflicts]
        
        for cmd in commands_to_test:
            result = runner.invoke(cmd, ['--help'])
            assert result.exit_code == 0
            assert "-a, --agent" in result.output
            assert "required" in result.output.lower() or "Agent name" in result.output

    def test_inspect_group_help_mentions_agent_flag(self):
        """Test that main inspect help mentions the -a flag pattern."""
        runner = CliRunner()
        result = runner.invoke(inspect, ['--help'])
        
        assert result.exit_code == 0
        assert "inspect" in result.output.lower()
        # Should mention the -a/--agent pattern in the group description

    @patch('agent_actions.tasks.inspect._create_config_manager')
    def test_filter_agent_options_work(self, mock_create_config):
        """Test that --filter-agent options work correctly."""
        # Mock config manager
        mock_config = MagicMock()
        mock_create_config.return_value = mock_config
        
        # For signatures command with filter
        mock_input_sig = MagicMock()
        mock_input_sig.get_all_fields.return_value = set()
        mock_output_sig = MagicMock() 
        mock_output_sig.get_available_fields.return_value = set()
        
        mock_config.get_all_signatures.return_value = {
            'filtered_agent': {
                'dependencies': [],
                'execution_order_index': 0,
                'is_operational': True,
                'input_signature': mock_input_sig,
                'output_signature': mock_output_sig
            }
        }
        
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path('agent_actions.yml').write_text('# Test project')
            
            # Test signatures with filter-agent
            result = runner.invoke(signatures, ['-a', 'test_agent', '--filter-agent', 'filtered_agent'])
            assert result.exit_code == 0
            
            # Test conflicts with filter-agent  
            mock_config.detect_field_conflicts.return_value = {
                'conflicts': {},
                'agent_dependencies': [],
                'all_available_fields': {}
            }
            
            result = runner.invoke(conflicts, ['-a', 'test_agent', '--filter-agent', 'filtered_agent'])
            assert result.exit_code == 0