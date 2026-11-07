"""A schema's `minimum`, `maximum`, `minLength` and `maxLength` reach the compiled schema.

The schema file accepts these keys and the docs show them, so the provider must be sent
them too. Each schema here is read from a YAML file through `SchemaLoader`, the loader
expansion uses, in both forms a schema file can take, and compiled for every vendor.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.output.response.loader import SchemaLoader
from agent_actions.output.response.vendor_compilation import compile_unified_schema

FIELDS_FORM = """\
name: scored
fields:
  - id: score
    type: integer
    minimum: 1
    maximum: 4
  - id: label
    type: string
    minLength: 2
    maxLength: 12
    pattern: "^[a-z]+$"
  - id: tier
    type: string
    enum: [gold, silver]
"""

PROPERTIES_FORM = """\
name: scored
type: object
properties:
  score: {type: integer, minimum: 1, maximum: 4}
  label: {type: string, minLength: 2, maxLength: 12, pattern: "^[a-z]+$"}
  tier: {type: string, enum: [gold, silver]}
"""

VENDORS = [
    "openai",
    "anthropic",
    "gemini",
    "groq",
    "cohere",
    "ollama_local",
    "ollama_cloud",
    "agac-provider",
    "llamafile",
]


def _loaded(tmp_path: Path, text: str) -> dict:
    (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "scored.yml").write_text(text)
    SchemaLoader.discover_schema_files(tmp_path)
    return SchemaLoader.load_schema("scored", project_root=tmp_path)


def _properties(compiled) -> dict:
    if isinstance(compiled, list):
        return compiled[0]["input_schema"]["properties"]
    if "schema" in compiled:
        return compiled["schema"]["properties"]
    return compiled["properties"]


@pytest.mark.parametrize("form", [FIELDS_FORM, PROPERTIES_FORM], ids=["fields", "properties"])
@pytest.mark.parametrize("vendor", VENDORS)
def test_numeric_and_length_bounds_reach_every_vendor(tmp_path, form, vendor):
    props = _properties(compile_unified_schema(_loaded(tmp_path, form), vendor))

    assert props["score"]["minimum"] == 1
    assert props["score"]["maximum"] == 4
    assert props["label"]["minLength"] == 2
    assert props["label"]["maxLength"] == 12


@pytest.mark.parametrize("form", [FIELDS_FORM, PROPERTIES_FORM], ids=["fields", "properties"])
def test_pattern_and_enum_still_arrive(tmp_path, form):
    props = _properties(compile_unified_schema(_loaded(tmp_path, form), "openai"))

    assert props["label"]["pattern"] == "^[a-z]+$"
    assert props["tier"]["enum"] == ["gold", "silver"]


def test_a_field_without_bounds_gets_none(tmp_path):
    props = _properties(compile_unified_schema(_loaded(tmp_path, FIELDS_FORM), "openai"))

    assert not {"minimum", "maximum", "minLength", "maxLength"} & set(props["tier"])


def test_the_openai_shape_is_exactly_the_type_and_its_bounds():
    unified = {
        "name": "s",
        "fields": [{"id": "score", "type": "integer", "minimum": 1, "maximum": 4}],
    }

    compiled = compile_unified_schema(unified, "openai")

    assert compiled["schema"]["properties"]["score"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 4,
    }
