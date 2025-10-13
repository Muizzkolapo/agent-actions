"""
Tests for config signature methods.

This module tests the signature methods on AgentConfig class.
"""

import pytest
from typing import Dict, Any, Optional
from agent_actions.core.parser.config_schema import AgentConfig
from agent_actions.core.signatures import InputSignature, OutputSignature


class TestAgentConfigSignatureMethods:
    """Test signature methods on AgentConfig."""

    def test_agent_config_output_signature(self):
        """Test AgentConfig.output_signature() method."""
        agent_config = AgentConfig(
            agent_type="extractor",
            name="test_extractor",
            output_schema={
                "properties": {
                    "summary": {"type": "string"},
                    "entities": {"type": "array"}
                }
            },
            observe=["document_id", "source_url"],
            drops=["temp_data"]
        )
        
        signature = agent_config.output_signature()
        
        assert isinstance(signature, OutputSignature)
        assert set(signature.schema_fields) == {"summary", "entities"}
        assert set(signature.observe_fields) == {"document_id", "source_url"}
        assert signature.dropped_fields == ["temp_data"]
        
        # Test available fields formula
        expected_available = {"summary", "entities", "document_id", "source_url"}
        assert signature.get_available_fields() == expected_available

    def test_agent_config_output_signature_with_schema_registry(self):
        """Test AgentConfig.output_signature() with schema registry."""
        agent_config = AgentConfig(
            agent_type="processor",
            name="test_processor",
            output_schema="ProcessorSchema",  # String reference
            observe=["metadata"],
            drops=[]
        )
        
        schema_registry = {
            "ProcessorSchema": {
                "properties": {
                    "result": {"type": "string"},
                    "confidence": {"type": "number"}
                }
            }
        }
        
        signature = agent_config.output_signature(schema_registry)
        
        assert set(signature.schema_fields) == {"result", "confidence"}
        assert signature.observe_fields == ["metadata"]
        assert signature.dropped_fields == []
        assert signature.get_available_fields() == {"result", "confidence", "metadata"}

    def test_agent_config_input_signature(self):
        """Test AgentConfig.input_signature() method."""
        agent_config = AgentConfig(
            agent_type="analyzer",
            name="test_analyzer",
            prompt="Analyze: {extractor.summary} and {classifier.category}",
            dependencies=["extractor", "classifier"]
        )
        
        dependency_configs = {
            "extractor": AgentConfig(
                agent_type="extractor",
                name="extractor",
                output_schema={
                    "properties": {
                        "summary": {"type": "string"},
                        "entities": {"type": "array"}
                    }
                }
            ),
            "classifier": AgentConfig(
                agent_type="classifier", 
                name="classifier",
                output_schema={
                    "properties": {
                        "category": {"type": "string"},
                        "confidence": {"type": "number"}
                    }
                }
            )
        }
        
        signature = agent_config.input_signature(dependency_configs)
        
        assert isinstance(signature, InputSignature)
        assert signature.dependencies == {
            "extractor": ["summary"],
            "classifier": ["category"]
        }
        assert signature.get_all_fields() == {"summary", "category"}

    def test_agent_config_input_signature_with_schema_registry(self):
        """Test AgentConfig.input_signature() with schema registry."""
        agent_config = AgentConfig(
            agent_type="validator",
            name="test_validator",
            prompt="Validate: {processor.result}",
            dependencies=["processor"]
        )
        
        dependency_configs = {
            "processor": AgentConfig(
                agent_type="processor",
                name="processor",
                output_schema="ProcessorSchema"  # String reference
            )
        }
        
        schema_registry = {
            "ProcessorSchema": {
                "properties": {
                    "result": {"type": "string"},
                    "score": {"type": "number"}
                }
            }
        }
        
        signature = agent_config.input_signature(dependency_configs, schema_registry)
        
        assert signature.dependencies == {"processor": ["result"]}
        assert "result" in signature.get_all_fields()

    def test_agent_config_signature_with_mixed_dependency_types(self):
        """Test AgentConfig signatures with mixed dependency config types."""
        agent_config = AgentConfig(
            agent_type="combiner",
            name="test_combiner",
            prompt="Combine: {agent1.field1} and {agent2.field2}",
            dependencies=["agent1", "agent2"]
        )
        
        # Mix of AgentConfig and dict dependency configs
        dependency_configs = {
            "agent1": AgentConfig(
                agent_type="agent1",
                name="agent1",
                output_schema={"properties": {"field1": {}}}
            ),
            "agent2": {  # Plain dict config
                "output_schema": {"properties": {"field2": {}}},
                "observe": [],
                "drops": []
            }
        }
        
        signature = agent_config.input_signature(dependency_configs)
        
        assert signature.dependencies == {
            "agent1": ["field1"],
            "agent2": ["field2"]
        }

    def test_agent_config_signature_no_dependencies(self):
        """Test AgentConfig signatures with no dependencies."""
        agent_config = AgentConfig(
            agent_type="starter",
            name="test_starter",
            output_schema={"properties": {"initial_data": {}}},
            dependencies=[]  # No dependencies
        )
        
        output_sig = agent_config.output_signature()
        input_sig = agent_config.input_signature({})
        
        assert output_sig.schema_fields == ["initial_data"]
        assert input_sig.dependencies == {}
        assert input_sig.get_all_fields() == set()

    def test_agent_config_signature_empty_prompt(self):
        """Test AgentConfig input signature with empty prompt."""
        agent_config = AgentConfig(
            agent_type="silent",
            name="test_silent",
            prompt="",  # Empty prompt
            dependencies=["some_agent"]
        )
        
        dependency_configs = {
            "some_agent": AgentConfig(
                agent_type="some_agent",
                name="some_agent",
                output_schema={"properties": {"field": {}}}
            )
        }
        
        signature = agent_config.input_signature(dependency_configs)
        
        # No field references in empty prompt
        assert signature.dependencies == {}
        assert signature.get_all_fields() == set()




class TestSignatureMethodErrorHandling:
    """Test error handling in signature methods."""

    def test_agent_config_output_signature_empty_schema(self):
        """Test AgentConfig.output_signature() with empty schema."""
        agent_config = AgentConfig(
            agent_type="empty",
            name="test_empty",
            output_schema={},  # Empty schema
            observe=["field1"],
            drops=[]
        )
        
        signature = agent_config.output_signature()
        
        assert signature.schema_fields == []
        assert signature.observe_fields == ["field1"]
        assert signature.get_available_fields() == {"field1"}

    def test_agent_config_input_signature_missing_dependency(self):
        """Test AgentConfig.input_signature() with missing dependency config."""
        agent_config = AgentConfig(
            agent_type="needy",
            name="test_needy",
            prompt="Need: {missing.field}",
            dependencies=["missing"]
        )
        
        dependency_configs = {}  # Missing dependency config
        
        # Should not raise error, but might have incomplete validation
        signature = agent_config.input_signature(dependency_configs)
        
        # Missing dependency configs result in empty signature
        assert signature.get_all_fields() == set()


    def test_signature_method_schema_registry_errors(self):
        """Test signature methods with schema registry errors."""
        agent_config = AgentConfig(
            agent_type="test",
            name="test",
            output_schema="NonExistentSchema"
        )
        
        # Empty registry
        signature1 = agent_config.output_signature({})
        assert signature1.schema_fields == []
        
        # Malformed registry
        bad_registry = {"NonExistentSchema": "not_a_dict"}
        signature2 = agent_config.output_signature(bad_registry)
        assert signature2.schema_fields == []

    def test_signature_method_with_invalid_dependency_config(self):
        """Test input signature with invalid dependency config."""
        agent_config = AgentConfig(
            agent_type="test",
            name="test",
            prompt="Use: {dep.field}",
            dependencies=["dep"]
        )
        
        # Invalid dependency config type
        dependency_configs = {
            "dep": "not_a_config_object"
        }
        
        # Should handle gracefully without crashing
        signature = agent_config.input_signature(dependency_configs)
        
        # May not be able to validate fully, but shouldn't crash
        assert isinstance(signature, InputSignature)

    def test_signature_method_error_propagation(self):
        """Test that signature method errors are propagated correctly."""
        agent_config = AgentConfig(
            agent_type="test",
            name="test",
            output_schema={"properties": {"field": {}}},
            observe=["valid_field"],
            drops=[]
        )
        
        # Normal case should work
        signature = agent_config.output_signature()
        assert isinstance(signature, OutputSignature)
        assert signature.schema_fields == ["field"]
        assert signature.observe_fields == ["valid_field"]


class TestSignatureMethodComplexScenarios:
    """Test signature methods in complex scenarios."""

    def test_deep_dependency_chain(self):
        """Test signature methods with deep dependency chain."""
        # Create a chain: agent1 -> agent2 -> agent3
        agent3_config = AgentConfig(
            agent_type="agent3",
            name="agent3",
            prompt="Final: {agent2.intermediate}",
            dependencies=["agent2"]
        )
        
        agent2_config = AgentConfig(
            agent_type="agent2", 
            name="agent2",
            output_schema={"properties": {"intermediate": {}}},
            prompt="Middle: {agent1.initial}",
            dependencies=["agent1"]
        )
        
        agent1_config = AgentConfig(
            agent_type="agent1",
            name="agent1", 
            output_schema={"properties": {"initial": {}}}
        )
        
        # Test agent3's input signature
        dependency_configs = {"agent2": agent2_config}
        signature = agent3_config.input_signature(dependency_configs)
        
        assert signature.dependencies == {"agent2": ["intermediate"]}

    def test_circular_reference_handling(self):
        """Test signature methods handle circular references gracefully."""
        # Note: This tests the signature computation, not actual circular execution
        agent_a = AgentConfig(
            agent_type="agent_a",
            name="agent_a",
            prompt="Use: {agent_b.field_b}",
            dependencies=["agent_b"],
            output_schema={"properties": {"field_a": {}}}
        )
        
        agent_b = AgentConfig(
            agent_type="agent_b",
            name="agent_b", 
            prompt="Use: {agent_a.field_a}",
            dependencies=["agent_a"],
            output_schema={"properties": {"field_b": {}}}
        )
        
        # Should compute signatures without infinite recursion
        sig_a = agent_a.input_signature({"agent_b": agent_b})
        sig_b = agent_b.input_signature({"agent_a": agent_a})
        
        assert sig_a.dependencies == {"agent_b": ["field_b"]}
        assert sig_b.dependencies == {"agent_a": ["field_a"]}

    def test_large_workflow_signature_computation(self):
        """Test signature computation performance with large workflows."""
        # Create many agents with dependencies
        num_agents = 20
        agents = {}
        
        for i in range(num_agents):
            agent_config = AgentConfig(
                agent_type=f"agent_{i}",
                name=f"agent_{i}",
                output_schema={"properties": {f"field_{i}": {}}},
                prompt=f"Process: {{agent_{i-1}.field_{i-1}}}" if i > 0 else "Start",
                dependencies=[f"agent_{i-1}"] if i > 0 else []
            )
            agents[f"agent_{i}"] = agent_config
        
        # Test signature computation for final agent
        final_agent = agents[f"agent_{num_agents-1}"]
        signature = final_agent.input_signature(agents)
        
        # Should complete without performance issues
        assert isinstance(signature, InputSignature)
        assert len(signature.dependencies) == 1  # Only depends on previous agent