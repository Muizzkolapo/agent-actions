"""Unit tests for type conversion module.

Tests the conversion of TypedDict, Pydantic, and dataclass types
to the unified schema format.
"""

import dataclasses
import pytest
from typing import Dict, List, Optional, TypedDict

from agent_actions.utilities.udf_management.type_conversion import (
    derive_schema_from_type,
    detect_type_category,
    is_typeddict,
    TypeCategory,
    HAS_PYDANTIC,
)


# =============================================================================
# Type Detection Tests
# =============================================================================

class TestTypeDetection:
    """Tests for type detection logic."""

    def test_typeddict_detected(self):
        """TypedDict should be detected as TYPEDDICT."""
        class MyTypedDict(TypedDict):
            name: str

        assert detect_type_category(MyTypedDict) == TypeCategory.TYPEDDICT
        assert is_typeddict(MyTypedDict)

    def test_dataclass_detected(self):
        """Dataclass should be detected as DATACLASS."""
        @dataclasses.dataclass
        class MyDataclass:
            name: str

        assert detect_type_category(MyDataclass) == TypeCategory.DATACLASS
        assert not is_typeddict(MyDataclass)

    @pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
    def test_pydantic_detected(self):
        """Pydantic model should be detected as PYDANTIC."""
        from pydantic import BaseModel

        class MyPydantic(BaseModel):
            name: str

        assert detect_type_category(MyPydantic) == TypeCategory.PYDANTIC
        assert not is_typeddict(MyPydantic)

    def test_unsupported_type(self):
        """Plain class should be detected as UNSUPPORTED."""
        class PlainClass:
            name: str

        assert detect_type_category(PlainClass) == TypeCategory.UNSUPPORTED

    def test_primitive_unsupported(self):
        """Primitive types should be UNSUPPORTED."""
        assert detect_type_category(str) == TypeCategory.UNSUPPORTED
        assert detect_type_category(int) == TypeCategory.UNSUPPORTED
        assert detect_type_category(dict) == TypeCategory.UNSUPPORTED


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

        assert schema['name'] == 'Input'
        assert len(schema['fields']) == 2

        fields = {f['id']: f for f in schema['fields']}
        assert fields['name']['type'] == 'string'
        assert fields['name']['required'] is True
        assert fields['age']['type'] == 'integer'  # int -> integer, not number
        assert fields['age']['required'] is True

    def test_int_maps_to_integer(self):
        """int should map to 'integer', not 'number'."""
        class Input(TypedDict):
            count: int
            price: float

        schema = derive_schema_from_type(Input)
        fields = {f['id']: f for f in schema['fields']}

        assert fields['count']['type'] == 'integer'
        assert fields['price']['type'] == 'number'

    def test_optional_field(self):
        """Optional[T] should mark field as not required."""
        class Input(TypedDict):
            required_field: str
            optional_field: Optional[str]

        schema = derive_schema_from_type(Input)
        fields = {f['id']: f for f in schema['fields']}

        assert fields['required_field']['required'] is True
        assert fields['optional_field']['required'] is False

    def test_total_false(self):
        """TypedDict with total=False should have optional fields."""
        class Input(TypedDict, total=False):
            optional: str

        schema = derive_schema_from_type(Input)
        assert schema['fields'][0]['required'] is False

    def test_list_field(self):
        """List[T] should produce array type with items."""
        class Input(TypedDict):
            items: List[str]

        schema = derive_schema_from_type(Input)
        field = schema['fields'][0]

        assert field['type'] == 'array'
        assert field['items']['type'] == 'string'

    def test_list_of_integers(self):
        """List[int] should have items type 'integer'."""
        class Input(TypedDict):
            numbers: List[int]

        schema = derive_schema_from_type(Input)
        field = schema['fields'][0]

        assert field['items']['type'] == 'integer'

    def test_dict_field(self):
        """Dict[str, V] should produce object with additionalProperties."""
        class Input(TypedDict):
            metadata: Dict[str, int]

        schema = derive_schema_from_type(Input)
        field = schema['fields'][0]

        assert field['type'] == 'object'
        assert field['additionalProperties']['type'] == 'integer'

    def test_nested_typeddict(self):
        """Nested TypedDict should produce nested object."""
        class Inner(TypedDict):
            value: int

        class Outer(TypedDict):
            inner: Inner

        schema = derive_schema_from_type(Outer)
        field = schema['fields'][0]

        assert field['type'] == 'object'
        assert 'properties' in field
        assert 'value' in field['properties']

    def test_list_of_typeddict(self):
        """List[TypedDict] should produce array of objects."""
        class Item(TypedDict):
            id: int
            name: str

        class Container(TypedDict):
            items: List[Item]

        schema = derive_schema_from_type(Container)
        field = schema['fields'][0]

        assert field['type'] == 'array'
        assert field['items']['type'] == 'object'
        assert 'properties' in field['items']


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
        fields = {f['id']: f for f in schema['fields']}

        assert fields['name']['required'] is True
        assert fields['count']['required'] is False

    def test_factory_default(self):
        """Field with default_factory should not be required."""
        @dataclasses.dataclass
        class Input:
            items: List[str] = dataclasses.field(default_factory=list)

        schema = derive_schema_from_type(Input)
        assert schema['fields'][0]['required'] is False

    def test_optional_dataclass_field(self):
        """Optional field in dataclass should not be required."""
        @dataclasses.dataclass
        class Input:
            maybe: Optional[str] = None

        schema = derive_schema_from_type(Input)
        assert schema['fields'][0]['required'] is False

    def test_nested_dataclass(self):
        """Nested dataclass should produce nested object."""
        @dataclasses.dataclass
        class Inner:
            value: int

        @dataclasses.dataclass
        class Outer:
            inner: Inner

        schema = derive_schema_from_type(Outer)
        field = schema['fields'][0]

        assert field['type'] == 'object'
        assert 'properties' in field


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
        fields = {f['id']: f for f in schema['fields']}

        assert fields['name']['required'] is True
        assert fields['count']['required'] is False

    def test_optional_pydantic_field(self):
        """Optional field in Pydantic should not be required."""
        from pydantic import BaseModel

        class Input(BaseModel):
            maybe: Optional[str] = None

        schema = derive_schema_from_type(Input)
        assert schema['fields'][0]['required'] is False

    def test_list_pydantic_field(self):
        """List field in Pydantic should produce array."""
        from pydantic import BaseModel

        class Input(BaseModel):
            items: List[str]

        schema = derive_schema_from_type(Input)
        field = schema['fields'][0]

        assert field['type'] == 'array'
        assert 'items' in field


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Tests for error handling in type conversion."""

    def test_unsupported_type_raises(self):
        """Unsupported type should raise ConfigurationError."""
        from agent_actions.errors import ConfigurationError

        with pytest.raises(ConfigurationError) as exc_info:
            derive_schema_from_type(str)

        assert "Unsupported type hint" in str(exc_info.value)

    def test_plain_class_raises(self):
        """Plain class should raise ConfigurationError."""
        from agent_actions.errors import ConfigurationError

        class NotASchema:
            pass

        with pytest.raises(ConfigurationError):
            derive_schema_from_type(NotASchema)
