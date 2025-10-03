"""
Integration tests for sequential loop execution flow.

These tests validate the end-to-end flow from workflow configuration
through ActionExpander to AgentWorkflow execution structure.
"""

import pytest
import tempfile
from pathlib import Path

from agent_actions.core.parser.action_expander import ActionExpander


class TestSequentialLoopIntegration:
    """Test end-to-end sequential loop integration."""

    def test_sequential_refinement_workflow_structure(self):
        """Test complete sequential refinement workflow configuration."""
        # This is a realistic sequential refinement workflow
        # where each iteration refines the output from the previous one
        workflow_config = {
            "name": "iterative_refiner",
            "description": "Sequential refinement workflow",
            "version": "1.0.0",
            "defaults": {
                "model_vendor": "openai",
                "model_name": "gpt-4o-mini"
            },
            "actions": [
                {
                    "name": "extract",
                    "intent": "Extract initial data",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Extract data from input"
                },
                {
                    "name": "refine",
                    "intent": "Iteratively refine the extracted data",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Refine stage ${stage}: improve based on stage ${stage-1}",
                    "observe": ["refined_output_${stage}"],
                    "loop": {
                        "param": "stage",
                        "range": [1, 3],
                        "mode": "sequential"
                    }
                },
                {
                    "name": "validate",
                    "intent": "Validate final output",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Validate the final refined output"
                }
            ],
            "plan": [
                "extract",
                "refine <- extract",
                "validate <- refine"
            ]
        }

        # Expand to agent configs
        result = ActionExpander.expand_actions_to_agents(workflow_config)
        agents = result["iterative_refiner"]

        # Verify structure
        assert len(agents) == 5  # extract + refine_1,2,3 + validate

        # Find each agent
        extract = next(a for a in agents if a['agent_type'] == 'extract')
        refine_1 = next(a for a in agents if a['agent_type'] == 'refine_1')
        refine_2 = next(a for a in agents if a['agent_type'] == 'refine_2')
        refine_3 = next(a for a in agents if a['agent_type'] == 'refine_3')
        validate = next(a for a in agents if a['agent_type'] == 'validate')

        # Verify dependency chain
        assert extract['dependencies'] == []
        assert refine_1['dependencies'] == ['extract']
        assert refine_2['dependencies'] == ['refine_1']
        assert refine_3['dependencies'] == ['refine_2']
        # Validate depends on all refine iterations (as specified in plan)
        assert set(validate['dependencies']) == {'refine_1', 'refine_2', 'refine_3'}

        # Verify loop metadata
        assert refine_1['is_loop_agent'] is True
        assert refine_1['loop_mode'] == 'sequential'
        assert refine_1['loop_iteration'] == 1

        assert refine_2['is_loop_agent'] is True
        assert refine_2['loop_mode'] == 'sequential'
        assert refine_2['loop_iteration'] == 2

        assert refine_3['is_loop_agent'] is True
        assert refine_3['loop_mode'] == 'sequential'
        assert refine_3['loop_iteration'] == 3

        # Verify template variable expansion in prompts
        assert refine_1['prompt'] == "Refine stage 1: improve based on stage "
        assert refine_2['prompt'] == "Refine stage 2: improve based on stage 1"
        assert refine_3['prompt'] == "Refine stage 3: improve based on stage 2"

        # Verify template variable expansion in observe fields
        assert "refined_output_1" in refine_1['side_collection']
        assert "refined_output_2" in refine_2['side_collection']
        assert "refined_output_3" in refine_3['side_collection']

    def test_mixed_parallel_and_sequential_workflow(self):
        """Test workflow with both parallel and sequential loops."""
        workflow_config = {
            "name": "mixed_workflow",
            "description": "Workflow with both loop types",
            "version": "1.0.0",
            "defaults": {
                "model_vendor": "openai",
                "model_name": "gpt-4o-mini"
            },
            "actions": [
                {
                    "name": "input",
                    "intent": "Load input",
                    "api_key": "OPENAI_API_KEY"
                },
                {
                    "name": "parallel_process",
                    "intent": "Process in parallel",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Process batch ${i}",
                    "loop": {
                        "param": "i",
                        "range": [1, 3],
                        "mode": "parallel"
                    }
                },
                {
                    "name": "sequential_refine",
                    "intent": "Refine sequentially",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Refine iteration ${j}",
                    "loop": {
                        "param": "j",
                        "range": [1, 2],
                        "mode": "sequential"
                    }
                },
                {
                    "name": "output",
                    "intent": "Generate output",
                    "api_key": "OPENAI_API_KEY"
                }
            ],
            "plan": [
                "input",
                "parallel_process <- input",
                "sequential_refine <- parallel_process",
                "output <- sequential_refine"
            ]
        }

        result = ActionExpander.expand_actions_to_agents(workflow_config)
        agents = result["mixed_workflow"]

        # Should have: input + 3 parallel + 2 sequential + output = 7 agents
        assert len(agents) == 7

        # Verify parallel agents
        par_agents = [a for a in agents if a['agent_type'].startswith('parallel_process_')]
        assert len(par_agents) == 3

        # All parallel agents should depend on input
        for agent in par_agents:
            assert agent['dependencies'] == ['input']
            assert agent['loop_mode'] == 'parallel'

        # Verify sequential agents
        seq_agents = [a for a in agents if a['agent_type'].startswith('sequential_refine_')]
        assert len(seq_agents) == 2

        # Sequential agents should form chain
        # First depends on all parallel agents, second depends on first
        assert set(seq_agents[0]['dependencies']) == {'parallel_process_1', 'parallel_process_2', 'parallel_process_3'}
        assert seq_agents[1]['dependencies'] == ['sequential_refine_1']

        # Verify loop modes
        for agent in seq_agents:
            assert agent['loop_mode'] == 'sequential'

    def test_sequential_loop_with_explicit_list_range(self):
        """Test sequential loop with explicit list of values."""
        workflow_config = {
            "name": "explicit_range_workflow",
            "description": "Sequential loop with explicit range",
            "version": "1.0.0",
            "defaults": {
                "model_vendor": "openai",
                "model_name": "gpt-4o-mini"
            },
            "actions": [
                {
                    "name": "process",
                    "intent": "Process with explicit range",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Process level ${level} (previous: ${level-1})",
                    "loop": {
                        "param": "level",
                        "range": [10, 20, 30],  # Explicit list
                        "mode": "sequential"
                    }
                }
            ],
            "plan": ["process"]
        }

        result = ActionExpander.expand_actions_to_agents(workflow_config)
        agents = result["explicit_range_workflow"]

        assert len(agents) == 3

        # Verify agent names use actual range values
        assert agents[0]['agent_type'] == 'process_10'
        assert agents[1]['agent_type'] == 'process_20'
        assert agents[2]['agent_type'] == 'process_30'

        # Note: Without dependencies in plan, even sequential loops have empty dependencies
        # The sequential mode only affects how dependencies are inherited when specified in plan
        # This test mainly verifies template variable expansion with explicit ranges

        # Verify loop metadata
        assert agents[0]['loop_mode'] == 'sequential'
        assert agents[1]['loop_mode'] == 'sequential'
        assert agents[2]['loop_mode'] == 'sequential'

        # Verify template variable expansion uses actual values
        assert agents[0]['prompt'] == "Process level 10 (previous: )"
        assert agents[1]['prompt'] == "Process level 20 (previous: 10)"
        assert agents[2]['prompt'] == "Process level 30 (previous: 20)"

    def test_backward_compatibility_default_to_parallel(self):
        """Test that loops without mode specified default to parallel."""
        workflow_config = {
            "name": "legacy_workflow",
            "description": "Workflow without mode specified",
            "version": "1.0.0",
            "defaults": {
                "model_vendor": "openai",
                "model_name": "gpt-4o-mini"
            },
            "actions": [
                {
                    "name": "input",
                    "intent": "Load input",
                    "api_key": "OPENAI_API_KEY"
                },
                {
                    "name": "process",
                    "intent": "Process data",
                    "api_key": "OPENAI_API_KEY",
                    "loop": {
                        "param": "i",
                        "range": [1, 2]
                        # No mode specified - should default to parallel
                    }
                }
            ],
            "plan": [
                "input",
                "process <- input"
            ]
        }

        result = ActionExpander.expand_actions_to_agents(workflow_config)
        agents = result["legacy_workflow"]

        process_agents = [a for a in agents if a['agent_type'].startswith('process_')]

        # Should default to parallel behavior
        for agent in process_agents:
            assert agent['dependencies'] == ['input']
            assert agent['loop_mode'] == 'parallel'

    def test_complex_sequential_workflow_with_schema_and_drops(self):
        """Test sequential workflow with schema, drops, observe fields."""
        workflow_config = {
            "name": "complex_sequential",
            "description": "Complex sequential workflow",
            "version": "1.0.0",
            "defaults": {
                "model_vendor": "openai",
                "model_name": "gpt-4o-mini",
                "drops": ["temp_metadata"]
            },
            "actions": [
                {
                    "name": "enhance",
                    "intent": "Enhance data sequentially",
                    "api_key": "OPENAI_API_KEY",
                    "prompt": "Enhancement pass ${pass}",
                    "schema": {
                        "pass_number": "integer",
                        "enhanced_field_${pass}": "string",
                        "previous_pass_${pass-1}": "string"
                    },
                    "observe": ["pass_${pass}_output"],
                    "drops": ["debug_${pass}"],
                    "loop": {
                        "param": "pass",
                        "range": [1, 2],
                        "mode": "sequential"
                    }
                }
            ],
            "plan": ["enhance"]
        }

        result = ActionExpander.expand_actions_to_agents(workflow_config)
        agents = result["complex_sequential"]

        assert len(agents) == 2

        # Verify schema template expansion
        schema1 = agents[0]['schema']
        assert schema1['pass_number'] == 'integer'
        assert 'enhanced_field_1' in schema1
        assert 'previous_pass_' in schema1  # Empty for first iteration

        schema2 = agents[1]['schema']
        assert 'enhanced_field_2' in schema2
        assert 'previous_pass_1' in schema2

        # Verify observe field expansion
        assert "pass_1_output" in agents[0]['side_collection']
        assert "pass_2_output" in agents[1]['side_collection']

        # Verify drops field expansion (includes defaults + action-specific)
        assert "temp_metadata" in agents[0]['remove_collection']  # From defaults
        assert "debug_1" in agents[0]['remove_collection']  # From action
        assert "debug_2" in agents[1]['remove_collection']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
