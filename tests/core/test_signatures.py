"""
Tests for signature data structures.

This module tests the core signature data structures: FieldInfo, FieldSource,
InputSignature, and OutputSignature classes.
"""

import pytest
import json
from typing import Dict, List, Set
from agent_actions.core.signatures import (
    FieldInfo,
    FieldSource,
    InputSignature,
    OutputSignature
)


class TestFieldInfo:
    """Test FieldInfo data structure."""

    def test_field_info_creation_and_serialization(self):
        """Test FieldInfo creation and Pydantic serialization."""
        field_info = FieldInfo(
            name="summary",
            source=FieldSource.SCHEMA
        )
        
        assert field_info.name == "summary"
        assert field_info.source == FieldSource.SCHEMA
        
        # Test serialization
        field_dict = field_info.model_dump()
        assert field_dict == {
            "name": "summary",
            "source": "schema"
        }
        
        # Test deserialization
        field_from_dict = FieldInfo.model_validate(field_dict)
        assert field_from_dict.name == "summary"
        assert field_from_dict.source == FieldSource.SCHEMA

    def test_field_info_json_serialization(self):
        """Test JSON serialization and deserialization."""
        field_info = FieldInfo(
            name="entities",
            source=FieldSource.OBSERVE
        )
        
        # Serialize to JSON
        json_str = field_info.model_dump_json()
        parsed = json.loads(json_str)
        
        assert parsed["name"] == "entities"
        assert parsed["source"] == "observe"
        
        # Deserialize from JSON
        field_from_json = FieldInfo.model_validate_json(json_str)
        assert field_from_json.name == "entities"
        assert field_from_json.source == FieldSource.OBSERVE

    def test_field_source_enum_values(self):
        """Test FieldSource enum has expected values."""
        assert FieldSource.SCHEMA == "schema"
        assert FieldSource.OBSERVE == "observe"
        assert FieldSource.SOURCE == "source"
        assert FieldSource.LOOP == "loop"
        assert FieldSource.WORKFLOW == "workflow"
        
        # Test all enum values can be used
        for source in FieldSource:
            field_info = FieldInfo(name="test", source=source)
            assert field_info.source == source


class TestInputSignature:
    """Test InputSignature data structure."""

    def test_input_signature_field_aggregation(self):
        """Test get_all_fields() aggregates from all sources."""
        input_sig = InputSignature(
            dependencies={
                "extractor": ["summary", "entities"],
                "classifier": ["category"]
            },
            source_fields=["page_content", "title"],
            loop_fields=["index", "total"],
            workflow_fields=["run_id", "version"]
        )
        
        all_fields = input_sig.get_all_fields()
        expected_fields = {
            "summary", "entities", "category",  # dependencies
            "page_content", "title",            # source
            "index", "total",                   # loop
            "run_id", "version"                 # workflow
        }
        
        assert all_fields == expected_fields

    def test_input_signature_empty_fields(self):
        """Test InputSignature with empty field collections."""
        input_sig = InputSignature()
        
        assert input_sig.dependencies == {}
        assert input_sig.source_fields == []
        assert input_sig.loop_fields == []
        assert input_sig.workflow_fields == []
        assert input_sig.get_all_fields() == set()

    def test_input_signature_duplicate_fields(self):
        """Test field aggregation handles duplicates correctly."""
        input_sig = InputSignature(
            dependencies={
                "agent1": ["field1", "field2"],
                "agent2": ["field2", "field3"]  # field2 appears twice
            },
            source_fields=["field1", "field4"],  # field1 appears in deps too
            loop_fields=["field3"],              # field3 appears in deps too
            workflow_fields=["field5"]
        )
        
        all_fields = input_sig.get_all_fields()
        expected_fields = {"field1", "field2", "field3", "field4", "field5"}
        
        assert all_fields == expected_fields
        assert len(all_fields) == 5  # No duplicates

    def test_input_signature_serialization(self):
        """Test InputSignature Pydantic serialization."""
        input_sig = InputSignature(
            dependencies={"extractor": ["summary"]},
            source_fields=["content"],
            loop_fields=["index"],
            workflow_fields=["run_id"]
        )
        
        # Test model_dump
        sig_dict = input_sig.model_dump()
        expected = {
            "dependencies": {"extractor": ["summary"]},
            "source_fields": ["content"],
            "loop_fields": ["index"],
            "workflow_fields": ["run_id"]
        }
        assert sig_dict == expected
        
        # Test round-trip
        sig_from_dict = InputSignature.model_validate(sig_dict)
        assert sig_from_dict.dependencies == input_sig.dependencies
        assert sig_from_dict.source_fields == input_sig.source_fields
        assert sig_from_dict.loop_fields == input_sig.loop_fields
        assert sig_from_dict.workflow_fields == input_sig.workflow_fields


class TestOutputSignature:
    """Test OutputSignature data structure."""

    def test_output_signature_available_fields(self):
        """Test get_available_fields() implements correct formula."""
        output_sig = OutputSignature(
            schema_fields=["summary", "entities", "metadata"],
            observe_fields=["document_id", "source_url"],
            dropped_fields=["metadata", "source_url"]  # metadata from schema, source_url from observe
        )
        
        available_fields = output_sig.get_available_fields()
        # Formula: (schema_fields + observe_fields) - dropped_fields
        # = (summary, entities, metadata) + (document_id, source_url) - (metadata, source_url)
        # = summary, entities, document_id
        expected_fields = {"summary", "entities", "document_id"}
        
        assert available_fields == expected_fields

    def test_output_signature_no_drops(self):
        """Test OutputSignature when no fields are dropped."""
        output_sig = OutputSignature(
            schema_fields=["analysis", "score"],
            observe_fields=["input_id"],
            dropped_fields=[]
        )
        
        available_fields = output_sig.get_available_fields()
        expected_fields = {"analysis", "score", "input_id"}
        
        assert available_fields == expected_fields

    def test_output_signature_empty_schema(self):
        """Test OutputSignature with empty schema fields."""
        output_sig = OutputSignature(
            schema_fields=[],
            observe_fields=["field1", "field2"],
            dropped_fields=["field1"]
        )
        
        available_fields = output_sig.get_available_fields()
        expected_fields = {"field2"}
        
        assert available_fields == expected_fields

    def test_output_signature_all_fields_dropped(self):
        """Test OutputSignature when all fields are dropped."""
        output_sig = OutputSignature(
            schema_fields=["field1", "field2"],
            observe_fields=["field3"],
            dropped_fields=["field1", "field2", "field3"]
        )
        
        available_fields = output_sig.get_available_fields()
        assert available_fields == set()

    def test_output_signature_serialization(self):
        """Test OutputSignature Pydantic serialization."""
        output_sig = OutputSignature(
            schema_fields=["summary"],
            observe_fields=["document_id"],
            dropped_fields=["metadata"]
        )
        
        # Test model_dump
        sig_dict = output_sig.model_dump()
        expected = {
            "schema_fields": ["summary"],
            "observe_fields": ["document_id"],
            "dropped_fields": ["metadata"]
        }
        assert sig_dict == expected
        
        # Test round-trip
        sig_from_dict = OutputSignature.model_validate(sig_dict)
        assert sig_from_dict.schema_fields == output_sig.schema_fields
        assert sig_from_dict.observe_fields == output_sig.observe_fields
        assert sig_from_dict.dropped_fields == output_sig.dropped_fields


class TestSignatureValidationEdgeCases:
    """Test edge cases and validation scenarios."""

    def test_input_signature_with_none_values(self):
        """Test InputSignature handles None values gracefully."""
        # Pydantic should convert None to default values
        with pytest.raises((TypeError, ValueError)):
            # This should fail because dependencies is required and can't be None
            InputSignature(dependencies=None)

    def test_output_signature_with_none_values(self):
        """Test OutputSignature handles None values gracefully."""
        with pytest.raises((TypeError, ValueError)):
            # This should fail because schema_fields is required
            OutputSignature(schema_fields=None)

    def test_field_info_invalid_source(self):
        """Test FieldInfo validation with invalid source."""
        with pytest.raises(ValueError):
            FieldInfo(name="test", source="invalid_source")

    def test_signature_json_compatibility(self):
        """Test signatures can be serialized to/from JSON."""
        input_sig = InputSignature(
            dependencies={"agent1": ["field1"]},
            source_fields=["field2"]
        )
        output_sig = OutputSignature(
            schema_fields=["field3"],
            observe_fields=["field4"],
            dropped_fields=[]
        )
        
        # Test JSON serialization
        input_json = input_sig.model_dump_json()
        output_json = output_sig.model_dump_json()
        
        # Test JSON deserialization
        input_from_json = InputSignature.model_validate_json(input_json)
        output_from_json = OutputSignature.model_validate_json(output_json)
        
        assert input_from_json.dependencies == input_sig.dependencies
        assert output_from_json.schema_fields == output_sig.schema_fields

    def test_signature_empty_strings_and_lists(self):
        """Test signatures handle empty strings and lists correctly."""
        input_sig = InputSignature(
            dependencies={},
            source_fields=[],
            loop_fields=[],
            workflow_fields=[]
        )
        
        output_sig = OutputSignature(
            schema_fields=[],
            observe_fields=[],
            dropped_fields=[]
        )
        
        assert input_sig.get_all_fields() == set()
        assert output_sig.get_available_fields() == set()

    def test_signature_large_field_collections(self):
        """Test signatures handle large numbers of fields efficiently."""
        # Create large field collections
        large_deps = {f"agent_{i}": [f"field_{i}_{j}" for j in range(10)] for i in range(10)}
        large_source = [f"source_{i}" for i in range(50)]
        large_schema = [f"schema_{i}" for i in range(100)]
        
        input_sig = InputSignature(
            dependencies=large_deps,
            source_fields=large_source
        )
        
        output_sig = OutputSignature(
            schema_fields=large_schema,
            observe_fields=[],
            dropped_fields=[]
        )
        
        # Should handle large collections without issues
        input_fields = input_sig.get_all_fields()
        output_fields = output_sig.get_available_fields()
        
        assert len(input_fields) == 150  # 100 dep fields + 50 source fields
        assert len(output_fields) == 100  # 100 schema fields