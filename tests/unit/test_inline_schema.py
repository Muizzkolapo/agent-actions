"""Unit tests for inline schema functionality."""

import pytest
from agent_actions.agents.handlers.schema_handler import SchemaLoader
from agent_actions.core.parser.schema_change import compile_unified_schema


class TestInlineSchema:
    """Test inline schema construction and compilation."""
    
    def test_construct_simple_schema(self):
        """Test constructing a simple inline schema."""
        inline_dict = {
            "name": "string",
            "age": "number",
            "is_active": "boolean"
        }
        
        result = SchemaLoader.construct_schema_from_dict(inline_dict)
        
        assert result["name"] == "InlineSchema"
        assert len(result["fields"]) == 3
        
        # Check each field
        fields_by_id = {f["id"]: f for f in result["fields"]}
        
        assert fields_by_id["name"]["type"] == "string"
        assert fields_by_id["name"]["required"] == False
        
        assert fields_by_id["age"]["type"] == "number"
        assert fields_by_id["age"]["required"] == False
        
        assert fields_by_id["is_active"]["type"] == "boolean"
        assert fields_by_id["is_active"]["required"] == False
    
    def test_construct_schema_with_required_fields(self):
        """Test constructing schema with required fields (! suffix)."""
        inline_dict = {
            "id": "string!",
            "email": "string!",
            "optional_field": "string"
        }
        
        result = SchemaLoader.construct_schema_from_dict(inline_dict)
        
        fields_by_id = {f["id"]: f for f in result["fields"]}
        
        assert fields_by_id["id"]["required"] == True
        assert fields_by_id["email"]["required"] == True
        assert fields_by_id["optional_field"]["required"] == False
    
    def test_construct_schema_with_arrays(self):
        """Test constructing schema with array types."""
        inline_dict = {
            "tags": "array",  # Default to array of strings
            "scores": "array[number]",
            "items": "array[object]"
        }
        
        result = SchemaLoader.construct_schema_from_dict(inline_dict)
        
        fields_by_id = {f["id"]: f for f in result["fields"]}
        
        # Default array should have string items
        assert fields_by_id["tags"]["type"] == "array"
        assert fields_by_id["tags"]["items"]["type"] == "string"
        
        # Typed arrays
        assert fields_by_id["scores"]["type"] == "array"
        assert fields_by_id["scores"]["items"]["type"] == "number"
        
        assert fields_by_id["items"]["type"] == "array"
        assert fields_by_id["items"]["items"]["type"] == "object"
    
    def test_compile_inline_schema_for_openai(self):
        """Test compiling inline schema for OpenAI format."""
        inline_dict = {
            "question": "string!",
            "options": "array[string]",
            "correct_answer": "number!"
        }
        
        unified = SchemaLoader.construct_schema_from_dict(inline_dict)
        compiled = compile_unified_schema(unified, "openai")
        
        assert compiled["name"] == "InlineSchema"
        assert compiled["schema"]["type"] == "object"
        assert compiled["schema"]["additionalProperties"] == False
        
        # Check properties
        props = compiled["schema"]["properties"]
        assert props["question"]["type"] == "string"
        assert props["options"]["type"] == "array"
        assert props["options"]["items"]["type"] == "string"
        assert props["correct_answer"]["type"] == "number"
        
        # Check required fields
        required = compiled["schema"]["required"]
        assert "question" in required
        assert "correct_answer" in required
        assert "options" not in required  # Not marked as required
    
    def test_compile_inline_schema_for_anthropic(self):
        """Test compiling inline schema for Anthropic format."""
        inline_dict = {
            "task": "string!",
            "status": "string"
        }
        
        unified = SchemaLoader.construct_schema_from_dict(inline_dict)
        compiled = compile_unified_schema(unified, "anthropic")
        
        # Anthropic returns a list with one tool
        assert isinstance(compiled, list)
        assert len(compiled) == 1
        
        tool = compiled[0]
        assert tool["name"] == "InlineSchema"
        assert tool["input_schema"]["type"] == "object"
        assert tool["input_schema"]["properties"]["task"]["type"] == "string"
        assert tool["input_schema"]["properties"]["status"]["type"] == "string"
        assert "task" in tool["input_schema"]["required"]
        assert "status" not in tool["input_schema"]["required"]
    
    def test_empty_inline_schema(self):
        """Test handling empty inline schema."""
        inline_dict = {}
        
        result = SchemaLoader.construct_schema_from_dict(inline_dict)
        
        assert result["name"] == "InlineSchema"
        assert result["fields"] == []
    
    def test_all_supported_types(self):
        """Test all supported data types."""
        inline_dict = {
            "str_field": "string",
            "num_field": "number",
            "int_field": "integer",
            "bool_field": "boolean",
            "obj_field": "object",
            "arr_field": "array"
        }
        
        result = SchemaLoader.construct_schema_from_dict(inline_dict)
        
        assert len(result["fields"]) == 6
        
        fields_by_id = {f["id"]: f for f in result["fields"]}
        assert fields_by_id["str_field"]["type"] == "string"
        assert fields_by_id["num_field"]["type"] == "number"
        assert fields_by_id["int_field"]["type"] == "integer"
        assert fields_by_id["bool_field"]["type"] == "boolean"
        assert fields_by_id["obj_field"]["type"] == "object"
        assert fields_by_id["arr_field"]["type"] == "array"
    
    def test_complex_object_in_array(self):
        """Test array with complex object properties."""
        inline_dict = {
            "excerpt": "array[object:{'option': 'string'}]"
        }
        
        result = SchemaLoader.construct_schema_from_dict(inline_dict)
        
        assert len(result["fields"]) == 1
        field = result["fields"][0]
        
        assert field["id"] == "excerpt"
        assert field["type"] == "array" 
        assert field["items"]["type"] == "object"
        assert "properties" in field["items"]
        assert field["items"]["properties"]["option"]["type"] == "string"
    
    def test_complex_object_with_required_fields(self):
        """Test array with complex object containing required fields."""
        inline_dict = {
            "data": "array[object:{'id': 'string!', 'name': 'string', 'score': 'number!'}]"
        }
        
        result = SchemaLoader.construct_schema_from_dict(inline_dict)
        
        field = result["fields"][0]
        items = field["items"]
        
        assert items["type"] == "object"
        assert items["properties"]["id"]["type"] == "string"
        assert items["properties"]["name"]["type"] == "string"
        assert items["properties"]["score"]["type"] == "number"
        assert "required" in items
        assert "id" in items["required"]
        assert "score" in items["required"]
        assert "name" not in items["required"]
    
    def test_excerpt_justification_schema(self):
        """Test the specific ExcerptJustification schema."""
        inline_dict = {
            "excerpt": "array[object:{'option': 'string'}]"
        }
        
        result = SchemaLoader.construct_schema_from_dict(inline_dict)
        
        # Change name to ExcerptJustification for this specific case
        result["name"] = "ExcerptJustification"
        
        assert result["name"] == "ExcerptJustification"
        assert len(result["fields"]) == 1
        
        excerpt_field = result["fields"][0]
        assert excerpt_field["id"] == "excerpt"
        assert excerpt_field["type"] == "array"
        assert excerpt_field["items"]["type"] == "object"
        assert excerpt_field["items"]["properties"]["option"]["type"] == "string"
    
    def test_invalid_object_properties(self):
        """Test handling of invalid object property syntax."""
        inline_dict = {
            "bad_syntax": "array[object:{invalid syntax}]"
        }
        
        result = SchemaLoader.construct_schema_from_dict(inline_dict)
        
        field = result["fields"][0]
        # Should fallback to basic object type when parsing fails
        assert field["items"]["type"] == "object"
        assert "properties" not in field["items"]