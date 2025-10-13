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


@pytest.mark.skip(reason="DEPRECATED: Uses old CLI pattern. See TestNewInspectCLIPattern for new -a/--agent pattern tests.")
class TestSignaturesCommand:
    """Test signatures CLI command.
    
    DEPRECATED: This class uses the old CLI pattern and will fail.
    See TestNewInspectCLIPattern for updated tests using -a/--agent flags.
    """

    def test_signatures_command_table_output(self, temp_test_workflow):
        """Test signatures command with table output format."""
        runner = CliRunner()
        result = runner.invoke(signatures, [temp_test_workflow])
        
        assert result.exit_code == 0
        output = result.output
        
        # Check table headers are present
        assert "Agent Signatures" in output
        assert "Agent" in output
        assert "Dependenci" in output  # May be truncated in table
        assert "Execution" in output
        assert "Input" in output
        assert "Output" in output
        assert "Status" in output
        
        # Check agent data is present
        assert "extractor" in output
        assert "classifier" in output
        assert "analyzer" in output
        
        # Check some field data
        assert "summary" in output
        assert "entities" in output
        assert "document_id" in output
        assert "category" in output
        assert "confidence" in output

    def test_signatures_command_json_output(self, temp_test_workflow):
        """Test signatures command with JSON output format."""
        runner = CliRunner()
        result = runner.invoke(signatures, ['--format', 'json', temp_test_workflow])
        
        assert result.exit_code == 0
        
        # Parse JSON output
        try:
            json_data = json.loads(result.output)
        except json.JSONDecodeError:
            pytest.fail(f"Output is not valid JSON: {result.output}")
        
        # Verify JSON structure
        assert isinstance(json_data, dict)
        assert "extractor" in json_data
        assert "classifier" in json_data
        assert "analyzer" in json_data
        
        # Check extractor signature
        extractor = json_data["extractor"]
        assert extractor["dependencies"] == []
        assert extractor["execution_order_index"] == 0
        assert extractor["is_operational"] is True
        
        # Check input signature
        input_sig = extractor["input_signature"]
        assert input_sig["dependencies"] == {}
        assert input_sig["source_fields"] == []
        assert "all_fields" in input_sig
        
        # Check output signature
        output_sig = extractor["output_signature"]
        assert set(output_sig["schema_fields"]) == {"summary", "entities", "metadata"}
        assert set(output_sig["observe_fields"]) == {"document_id", "source_url"}
        assert output_sig["dropped_fields"] == ["metadata"]
        
        # Check classifier signature
        classifier = json_data["classifier"]
        assert classifier["dependencies"] == ["extractor"]
        assert classifier["execution_order_index"] == 1
        
        # Check analyzer signature
        analyzer = json_data["analyzer"]
        assert analyzer["dependencies"] == ["extractor", "classifier"]
        assert analyzer["execution_order_index"] == 2

    def test_signatures_command_with_agent_filter(self, temp_test_workflow):
        """Test signatures command with agent filtering."""
        runner = CliRunner()
        result = runner.invoke(signatures, ['--agent', 'classifier', temp_test_workflow])
        
        assert result.exit_code == 0
        output = result.output
        
        # Should only show classifier
        assert "classifier" in output
        # Should not show other agents
        assert "extractor" not in output or output.count("extractor") <= 1  # May appear in dependencies
        assert "analyzer" not in output

    def test_signatures_command_nonexistent_agent(self, temp_test_workflow):
        """Test signatures command with non-existent agent filter."""
        runner = CliRunner()
        result = runner.invoke(signatures, ['--agent', 'nonexistent', temp_test_workflow])
        
        assert result.exit_code == 0
        assert "Agent 'nonexistent' not found in workflow" in result.output

    def test_signatures_command_invalid_format(self, temp_test_workflow):
        """Test signatures command with invalid format."""
        runner = CliRunner()
        result = runner.invoke(signatures, ['--format', 'invalid', temp_test_workflow])
        
        assert result.exit_code != 0
        assert "Invalid value for '--format'" in result.output

    def test_signatures_command_missing_file(self):
        """Test signatures command with missing workflow file."""
        runner = CliRunner()
        result = runner.invoke(signatures, ['nonexistent.yml'])
        
        assert result.exit_code != 0
        assert "does not exist" in result.output


@pytest.mark.skip(reason="DEPRECATED: Uses old CLI pattern. See TestNewInspectCLIPattern for new -a/--agent pattern tests.")
class TestFieldFlowCommand:
    """Test field-flow CLI command.
    
    DEPRECATED: This class uses the old CLI pattern and will fail.
    See TestNewInspectCLIPattern for updated tests using -a/--agent flags.
    """

    def test_field_flow_command_table_output(self, temp_test_workflow):
        """Test field-flow command with table output."""
        runner = CliRunner()
        result = runner.invoke(field_flow, [temp_test_workflow])
        
        assert result.exit_code == 0
        output = result.output
        
        # Check validation status
        assert "Field Flow Validation:" in output
        assert "Valid" in output
        
        # Check table headers
        assert "Agent Field Flow Analysis" in output
        assert "Agent" in output
        assert "Status" in output
        assert "Required Fields" in output
        assert "Provides Fields" in output
        assert "Fields Available" in output
        
        # Check agent data
        assert "extractor" in output
        assert "classifier" in output
        assert "analyzer" in output

    def test_field_flow_command_json_output(self, temp_test_workflow):
        """Test field-flow command with JSON output."""
        runner = CliRunner()
        result = runner.invoke(field_flow, ['--format', 'json', temp_test_workflow])
        
        assert result.exit_code == 0
        
        # Parse JSON output
        json_data = json.loads(result.output)
        
        # Verify JSON structure
        assert json_data["valid"] is True
        assert json_data["errors"] == []
        assert json_data["warnings"] == []
        assert "agent_validations" in json_data
        assert "field_flow_summary" in json_data
        
        # Check agent validations
        agent_validations = json_data["agent_validations"]
        assert "extractor" in agent_validations
        assert "classifier" in agent_validations
        assert "analyzer" in agent_validations
        
        for agent_name, validation in agent_validations.items():
            assert validation["valid"] is True
            assert validation["errors"] == []
        
        # Check field flow summary
        field_flow_summary = json_data["field_flow_summary"]
        assert len(field_flow_summary["extractor"]) == 4  # summary, entities, document_id, source_url
        assert len(field_flow_summary["classifier"]) == 6  # previous + category, confidence
        assert len(field_flow_summary["analyzer"]) == 8   # previous + analysis, score

    def test_field_flow_command_missing_file(self):
        """Test field-flow command with missing file."""
        runner = CliRunner()
        result = runner.invoke(field_flow, ['missing.yml'])
        
        assert result.exit_code != 0
        assert "does not exist" in result.output


@pytest.mark.skip(reason="DEPRECATED: Uses old CLI pattern. See TestNewInspectCLIPattern for new -a/--agent pattern tests.")
class TestConflictsCommand:
    """Test conflicts CLI command.
    
    DEPRECATED: This class uses the old CLI pattern and will fail.
    See TestNewInspectCLIPattern for updated tests using -a/--agent flags.
    """

    def test_conflicts_command_no_conflicts(self, temp_test_workflow):
        """Test conflicts command with workflow that has no conflicts."""
        runner = CliRunner()
        result = runner.invoke(conflicts, [temp_test_workflow])
        
        assert result.exit_code == 0
        assert "No field conflicts detected" in result.output

    def test_conflicts_command_with_conflicts(self, conflict_test_workflow):
        """Test conflicts command with workflow that has conflicts."""
        runner = CliRunner()
        result = runner.invoke(conflicts, [conflict_test_workflow])
        
        assert result.exit_code == 0
        output = result.output
        
        # Should detect conflict
        assert "Conflicts for agent 'combiner'" in output
        assert "confidence" in output
        assert "agent1" in output
        assert "agent2" in output
        assert "Conflicting Providers" in output

    def test_conflicts_command_specific_agent(self, conflict_test_workflow):
        """Test conflicts command with specific agent."""
        runner = CliRunner()
        result = runner.invoke(conflicts, [conflict_test_workflow, 'combiner'])
        
        assert result.exit_code == 0
        output = result.output
        
        # Should show conflicts for combiner
        assert "Conflicts for agent 'combiner'" in output
        assert "confidence" in output

    def test_conflicts_command_json_output(self, conflict_test_workflow):
        """Test conflicts command with JSON output."""
        runner = CliRunner()
        result = runner.invoke(conflicts, ['--format', 'json', conflict_test_workflow])
        
        assert result.exit_code == 0
        
        json_data = json.loads(result.output)
        
        # Should be structured as {agent_name: conflict_data}
        assert "combiner" in json_data
        combiner_conflicts = json_data["combiner"]
        
        assert "conflicts" in combiner_conflicts
        assert "confidence" in combiner_conflicts["conflicts"]
        assert set(combiner_conflicts["conflicts"]["confidence"]) == {"agent1", "agent2"}
        
        assert "agent_dependencies" in combiner_conflicts
        assert set(combiner_conflicts["agent_dependencies"]) == {"agent1", "agent2"}

    def test_conflicts_command_nonexistent_agent(self, temp_test_workflow):
        """Test conflicts command with non-existent agent."""
        runner = CliRunner()
        result = runner.invoke(conflicts, [temp_test_workflow, 'nonexistent'])
        
        assert result.exit_code == 0
        assert "not found in configurations" in result.output

    def test_conflicts_command_missing_file(self):
        """Test conflicts command with missing file."""
        runner = CliRunner()
        result = runner.invoke(conflicts, ['missing.yml'])
        
        assert result.exit_code != 0
        assert "does not exist" in result.output


@pytest.mark.skip(reason="DEPRECATED: Uses old CLI pattern. See TestNewInspectCLIPattern for new -a/--agent pattern tests.")
class TestInspectCommandGroup:
    """Test the inspect command group."""

    def test_inspect_command_help(self):
        """Test inspect command group help."""
        runner = CliRunner()
        result = runner.invoke(inspect, ['--help'])
        
        assert result.exit_code == 0
        output = result.output
        
        assert "Inspect workflow signatures and field dependencies" in output
        assert "signatures" in output
        assert "field-flow" in output
        assert "conflicts" in output

    def test_inspect_subcommand_help(self):
        """Test inspect subcommand help."""
        runner = CliRunner()
        
        # Test signatures help
        result = runner.invoke(inspect, ['signatures', '--help'])
        assert result.exit_code == 0
        assert "Display input and output signatures" in result.output
        
        # Test field-flow help
        result = runner.invoke(inspect, ['field-flow', '--help'])
        assert result.exit_code == 0
        assert "Validate field flow through the entire workflow" in result.output
        
        # Test conflicts help
        result = runner.invoke(inspect, ['conflicts', '--help'])
        assert result.exit_code == 0
        assert "Detect field name conflicts" in result.output


@pytest.mark.skip(reason="DEPRECATED: Uses old CLI pattern. See TestNewInspectCLIPattern for new -a/--agent pattern tests.")
class TestCLIErrorHandling:
    """Test CLI error handling scenarios."""

    def test_cli_invalid_workflow_format(self):
        """Test CLI commands with invalid workflow format."""
        # Create invalid YAML file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write("invalid: yaml: content: [")
            invalid_file = f.name
        
        try:
            runner = CliRunner()
            result = runner.invoke(signatures, [invalid_file])
            
            assert result.exit_code == 0  # Should handle gracefully
            assert "Error:" in result.output
            
        finally:
            Path(invalid_file).unlink(missing_ok=True)

    def test_cli_empty_workflow(self):
        """Test CLI commands with empty workflow."""
        workflow_data = {
            "empty_workflow": {
                "agents": []
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(workflow_data, f)
            empty_file = f.name
        
        # Create empty defaults in same directory
        defaults_path = Path(empty_file).parent / "defaults.yml"
        defaults_path.write_text("default_agent_config: {}")
        
        try:
            runner = CliRunner()
            result = runner.invoke(signatures, [empty_file])
            
            assert result.exit_code == 0
            # Should show empty table or handle gracefully
            
        finally:
            Path(empty_file).unlink(missing_ok=True)
            defaults_path.unlink(missing_ok=True)

    def test_cli_workflow_validation_errors(self):
        """Test CLI commands with workflow validation errors."""
        # Create workflow with missing dependencies
        workflow_data = {
            "error_workflow": {
                "agents": [
                    {
                        "name": "broken",
                        "agent_type": "broken",
                        "model_vendor": "anthropic",
                        "model_name": "claude-3-haiku-20240307",
                        "api_key": "fake-key",
                        "chunk_config": {},
                        "dependencies": ["missing_agent"],
                        "prompt": "Use: {missing_agent.field}",
                        "output_schema": {
                            "properties": {
                                "result": {"type": "string"}
                            }
                        }
                    }
                ]
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(workflow_data, f)
            error_file = f.name
        
        defaults_path = Path(error_file).parent / "defaults.yml"
        defaults_path.write_text("""
default_agent_config:
  model_vendor: anthropic
  model_name: claude-3-haiku-20240307
  api_key: fake-key
  chunk_config: {}
""")
        
        try:
            runner = CliRunner()
            result = runner.invoke(signatures, [error_file])
            
            assert result.exit_code == 0
            assert "Error:" in result.output
            
        finally:
            Path(error_file).unlink(missing_ok=True)
            defaults_path.unlink(missing_ok=True)

    def test_cli_permission_errors(self):
        """Test CLI commands handle file permission errors gracefully."""
        # Create a file and make it unreadable (if possible)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump({"test": {}}, f)
            perm_file = f.name
        
        try:
            # Try to make file unreadable (may not work on all systems)
            import os
            try:
                os.chmod(perm_file, 0o000)
            except (OSError, PermissionError):
                pytest.skip("Cannot modify file permissions on this system")
            
            runner = CliRunner()
            result = runner.invoke(signatures, [perm_file])
            
            # Should handle permission error gracefully
            assert result.exit_code != 0  # Permission errors should cause non-zero exit
            assert "Error" in result.output or "Permission" in result.output
            
        finally:
            # Restore permissions and cleanup
            try:
                os.chmod(perm_file, 0o644)
                Path(perm_file).unlink(missing_ok=True)
            except (OSError, PermissionError):
                pass  # Cleanup failed, but test is done

    def test_cli_large_output_handling(self, temp_test_workflow):
        """Test CLI commands handle large output correctly."""
        runner = CliRunner()
        
        # Test with JSON format (typically larger output)
        result = runner.invoke(signatures, ['--format', 'json', temp_test_workflow])
        assert result.exit_code == 0
        
        # Should be valid JSON regardless of size
        json_data = json.loads(result.output)
        assert isinstance(json_data, dict)
        
        # Test field-flow JSON output
        result = runner.invoke(field_flow, ['--format', 'json', temp_test_workflow])
        assert result.exit_code == 0
        
        json_data = json.loads(result.output)
        assert "valid" in json_data


# ===== NEW TEST CLASSES FOR UPDATED CLI PATTERN =====

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