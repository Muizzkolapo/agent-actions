"""J-1: Coverage of generate_typeddict.py — infer_python_type and extract_fields_from_json."""

import importlib.util
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).parents[3]
    / "agent_actions"
    / "skills"
    / "agent-actions-workflow"
    / "scripts"
    / "generate_typeddict.py"
)

if not _SCRIPT_PATH.exists():
    pytest.skip(f"Script not found: {_SCRIPT_PATH}", allow_module_level=True)


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_typeddict", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_module()
infer_python_type = _mod.infer_python_type
extract_fields_from_json = _mod.extract_fields_from_json
generate_typeddict = _mod.generate_typeddict


class TestInferPythonType:
    """infer_python_type maps JSON values to Python type annotations."""

    def test_none_returns_any(self):
        assert infer_python_type(None) == "Any"

    def test_bool_returns_bool(self):
        assert infer_python_type(True) == "bool"
        assert infer_python_type(False) == "bool"

    def test_int_returns_int(self):
        assert infer_python_type(42) == "int"

    def test_float_returns_float(self):
        assert infer_python_type(3.14) == "float"

    def test_str_returns_str(self):
        assert infer_python_type("hello") == "str"

    def test_empty_list_returns_list_any(self):
        assert infer_python_type([]) == "List[Any]"

    def test_homogeneous_list_returns_typed_list(self):
        assert infer_python_type([1, 2, 3]) == "List[int]"

    def test_heterogeneous_list_returns_list_any(self):
        assert infer_python_type([1, "a"]) == "List[Any]"

    def test_empty_dict_returns_dict(self):
        assert infer_python_type({}) == "dict"

    def test_homogeneous_dict_values_returns_typed_dict(self):
        result = infer_python_type({"a": 1, "b": 2})
        assert result == "Dict[str, int]"

    def test_unknown_type_fallback(self):
        # Using an object that's none of the above — falls through to the final return "Any"
        class Custom:
            pass

        result = infer_python_type(Custom())
        assert result == "Any"


class TestExtractFieldsFromJson:
    """extract_fields_from_json extracts field names and Python types from JSON data."""

    def test_flat_dict(self):
        data = {"name": "Alice", "age": 30, "active": True}
        fields = extract_fields_from_json(data)
        assert "name" in fields
        assert "age" in fields
        assert "active" in fields
        assert fields["name"] == "str"
        assert fields["age"] == "int"
        assert fields["active"] == "bool"

    def test_content_wrapper_unwrapped(self):
        """When top-level 'content' key is a dict, fields come from inside."""
        data = {"content": {"question": "What?", "answer": "42"}}
        fields = extract_fields_from_json(data)
        assert "question" in fields
        assert "answer" in fields

    def test_empty_dict_returns_empty(self):
        fields = extract_fields_from_json({})
        assert isinstance(fields, dict)

    def test_metadata_keys_excluded(self):
        """Internal metadata keys like 'target_id' should not appear in output fields."""
        data = {"target_id": "abc", "result": "good"}
        fields = extract_fields_from_json(data)
        assert "target_id" not in fields
        assert "result" in fields


class TestGenerateTypeddict:
    """generate_typeddict produces valid Python TypedDict source."""

    def test_basic_generation(self):
        fields = {"name": "str", "score": "float"}
        result = generate_typeddict(fields, "MyOutput", "step_a", "step_b")
        assert "class MyOutput" in result
        assert "TypedDict" in result
        assert "name" in result
        assert "score" in result

    def test_includes_imports(self):
        fields = {"x": "int"}
        result = generate_typeddict(fields, "Out", "a", "b")
        assert "from typing import" in result

    def test_empty_fields(self):
        result = generate_typeddict({}, "EmptyOut", "a", "b")
        assert "class EmptyOut" in result
