"""Unit tests for type conversion module.

Tests the conversion of TypedDict, Pydantic, and dataclass types
to the unified schema format.
"""

import dataclasses
import pytest
from typing import Dict, List, Optional, TypedDict

from agent_actions.utils.udf_management.type_conversion import (
    derive_schema_from_type,
    is_typeddict,
    clear_schema_cache,
    HAS_PYDANTIC,
)
from agent_actions.errors import ConfigurationError


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear schema cache before and after each test."""
    clear_schema_cache()
    yield
    clear_schema_cache()


# =============================================================================
# Type Detection Tests
# =============================================================================


class TestTypeDetection:
    """Tests for type detection logic."""

    def test_typeddict_detected(self):
        """TypedDict should be detected and converted."""

        class MyTypedDict(TypedDict):
            name: str

        assert is_typeddict(MyTypedDict)
        schema = derive_schema_from_type(MyTypedDict)
        assert schema["name"] == "MyTypedDict"

    def test_dataclass_detected(self):
        """Dataclass should be detected and converted."""

        @dataclasses.dataclass
        class MyDataclass:
            name: str

        assert not is_typeddict(MyDataclass)
        schema = derive_schema_from_type(MyDataclass)
        assert schema["name"] == "MyDataclass"

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_pydantic_detected(self):
        """Pydantic model should be detected and converted."""
        from pydantic import BaseModel

        class MyPydantic(BaseModel):
            name: str

        assert not is_typeddict(MyPydantic)
        schema = derive_schema_from_type(MyPydantic)
        assert schema["name"] == "MyPydantic"

    def test_unsupported_type_raises(self):
        """Plain class should raise ConfigurationError."""

        class PlainClass:
            name: str

        with pytest.raises(ConfigurationError) as exc_info:
            derive_schema_from_type(PlainClass)
        assert "Unsupported type hint" in str(exc_info.value)

    def test_primitive_type_raises(self):
        """Primitive types should raise ConfigurationError."""
        with pytest.raises(ConfigurationError):
            derive_schema_from_type(str)
        with pytest.raises(ConfigurationError):
            derive_schema_from_type(int)


# =============================================================================
# TypedDict Conversion Tests
# =============================================================================


class TestTypedDictConversion:
    """Tests for TypedDict to unified schema conversion."""

    def test_simple_typeddict(self):
        """Simple TypedDict with string and int fields."""

        class Input(TypedDict):
            name: str
            age: int

        schema = derive_schema_from_type(Input)

        assert schema["name"] == "Input"
        assert len(schema["fields"]) == 2

        fields = {f["id"]: f for f in schema["fields"]}
        assert fields["name"]["type"] == "string"
        assert fields["name"]["required"] is True
        assert fields["age"]["type"] == "integer"  # int -> integer, not number
        assert fields["age"]["required"] is True

    def test_int_maps_to_integer(self):
        """int should map to 'integer', not 'number'."""

        class Input(TypedDict):
            count: int
            price: float

        schema = derive_schema_from_type(Input)
        fields = {f["id"]: f for f in schema["fields"]}

        assert fields["count"]["type"] == "integer"
        assert fields["price"]["type"] == "number"

    def test_optional_field(self):
        """Optional[T] should mark field as not required."""

        class Input(TypedDict):
            required_field: str
            optional_field: Optional[str]

        schema = derive_schema_from_type(Input)
        fields = {f["id"]: f for f in schema["fields"]}

        assert fields["required_field"]["required"] is True
        assert fields["optional_field"]["required"] is False

    def test_total_false(self):
        """TypedDict with total=False should have optional fields."""

        class Input(TypedDict, total=False):
            optional: str

        schema = derive_schema_from_type(Input)
        assert schema["fields"][0]["required"] is False

    def test_list_field(self):
        """List[T] should produce array type with items."""

        class Input(TypedDict):
            items: List[str]

        schema = derive_schema_from_type(Input)
        field = schema["fields"][0]

        assert field["type"] == "array"
        assert field["items"]["type"] == "string"

    def test_list_of_integers(self):
        """List[int] should have items type 'integer'."""

        class Input(TypedDict):
            numbers: List[int]

        schema = derive_schema_from_type(Input)
        field = schema["fields"][0]

        assert field["items"]["type"] == "integer"

    def test_dict_field(self):
        """Dict[str, V] should produce object with additionalProperties."""

        class Input(TypedDict):
            metadata: Dict[str, int]

        schema = derive_schema_from_type(Input)
        field = schema["fields"][0]

        assert field["type"] == "object"
        assert field["additionalProperties"]["type"] == "integer"

    def test_nested_typeddict(self):
        """Nested TypedDict should produce nested object."""

        class Inner(TypedDict):
            value: int

        class Outer(TypedDict):
            inner: Inner

        schema = derive_schema_from_type(Outer)
        field = schema["fields"][0]

        assert field["type"] == "object"
        assert "properties" in field
        assert "value" in field["properties"]

    def test_list_of_typeddict(self):
        """List[TypedDict] should produce array of objects."""

        class Item(TypedDict):
            id: int
            name: str

        class Container(TypedDict):
            items: List[Item]

        schema = derive_schema_from_type(Container)
        field = schema["fields"][0]

        assert field["type"] == "array"
        assert field["items"]["type"] == "object"
        assert "properties" in field["items"]


# =============================================================================
# Dataclass Conversion Tests
# =============================================================================


class TestDataclassConversion:
    """Tests for dataclass to unified schema conversion."""

    def test_simple_dataclass(self):
        """Simple dataclass with required and default fields."""

        @dataclasses.dataclass
        class Input:
            name: str
            count: int = 0

        schema = derive_schema_from_type(Input)
        fields = {f["id"]: f for f in schema["fields"]}

        assert fields["name"]["required"] is True
        assert fields["count"]["required"] is False

    def test_factory_default(self):
        """Field with default_factory should not be required."""

        @dataclasses.dataclass
        class Input:
            items: List[str] = dataclasses.field(default_factory=list)

        schema = derive_schema_from_type(Input)
        assert schema["fields"][0]["required"] is False

    def test_optional_dataclass_field(self):
        """Optional field in dataclass should not be required."""

        @dataclasses.dataclass
        class Input:
            maybe: Optional[str] = None

        schema = derive_schema_from_type(Input)
        assert schema["fields"][0]["required"] is False

    def test_nested_dataclass(self):
        """Nested dataclass should produce nested object."""

        @dataclasses.dataclass
        class Inner:
            value: int

        @dataclasses.dataclass
        class Outer:
            inner: Inner

        schema = derive_schema_from_type(Outer)
        field = schema["fields"][0]

        assert field["type"] == "object"
        assert "properties" in field


# =============================================================================
# Pydantic Conversion Tests
# =============================================================================


@pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
class TestPydanticConversion:
    """Tests for Pydantic model to unified schema conversion."""

    def test_simple_pydantic(self):
        """Simple Pydantic model with required and optional fields."""
        from pydantic import BaseModel

        class Input(BaseModel):
            name: str
            count: int = 0

        schema = derive_schema_from_type(Input)
        fields = {f["id"]: f for f in schema["fields"]}

        assert fields["name"]["required"] is True
        assert fields["count"]["required"] is False

    def test_optional_pydantic_field(self):
        """Optional field in Pydantic should not be required."""
        from pydantic import BaseModel

        class Input(BaseModel):
            maybe: Optional[str] = None

        schema = derive_schema_from_type(Input)
        assert schema["fields"][0]["required"] is False

    def test_list_pydantic_field(self):
        """List field in Pydantic should produce array."""
        from pydantic import BaseModel

        class Input(BaseModel):
            items: List[str]

        schema = derive_schema_from_type(Input)
        field = schema["fields"][0]

        assert field["type"] == "array"
        assert "items" in field


# =============================================================================
# Schema Caching Tests
# =============================================================================


class TestSchemaCaching:
    """Tests for schema caching functionality."""

    def test_cache_returns_same_structure(self):
        """Cached result should match fresh derivation."""

        class Input(TypedDict):
            name: str

        schema1 = derive_schema_from_type(Input)
        schema2 = derive_schema_from_type(Input)

        # Should be equal
        assert schema1 == schema2

    def test_cache_returns_copy(self):
        """Cached result should be a copy, not same object."""

        class Input(TypedDict):
            name: str

        schema1 = derive_schema_from_type(Input)
        schema2 = derive_schema_from_type(Input)

        # Should not be the same object (mutation protection)
        assert schema1 is not schema2
        assert schema1["fields"] is not schema2["fields"]

    def test_clear_cache(self):
        """clear_schema_cache should empty the cache."""

        class Input(TypedDict):
            name: str

        derive_schema_from_type(Input)
        clear_schema_cache()
        # Should not raise - just verifying cache was cleared
        derive_schema_from_type(Input)
