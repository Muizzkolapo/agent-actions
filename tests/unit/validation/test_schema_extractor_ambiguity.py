"""An ambiguous schema reference degrades static analysis, never crashes it.

``SchemaExtractor`` runs inside ``agac docs``'s catalog generation, which
must skip ambiguous names rather than die; ``agac inspect``'s hard failure
comes earlier, from the config render path.
"""

from __future__ import annotations

import yaml

from agent_actions.validation.static_analyzer.schema_extractor import SchemaExtractor


def _project_with_ambiguous_schema(tmp_path):
    (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
    for wf in ("wf_a", "wf_b"):
        path = tmp_path / "agent_workflow" / wf / "schema" / "dup.yml"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump({"name": f"{wf}_copy", "fields": [{"id": "f1", "type": "string"}]}, f)
    return SchemaExtractor(project_root=tmp_path, tool_schemas={})


def test_llm_action_with_ambiguous_schema_name_degrades(tmp_path):
    extractor = _project_with_ambiguous_schema(tmp_path)
    output = extractor.extract_schema({"schema_name": "dup"})
    assert output.is_dynamic is True
    assert "ambiguous" in (output.load_error or "")


def test_llm_action_with_ambiguous_schema_string_degrades(tmp_path):
    extractor = _project_with_ambiguous_schema(tmp_path)
    output = extractor.extract_schema({"schema": "dup"})
    assert output.is_dynamic is True
    assert "ambiguous" in (output.load_error or "")


def test_tool_action_with_ambiguous_schema_string_degrades(tmp_path):
    extractor = _project_with_ambiguous_schema(tmp_path)
    output = extractor.extract_schema({"kind": "tool", "schema": "dup"})
    assert output.is_dynamic is True
    assert output.json_schema is None


def test_tool_action_with_ambiguous_schema_name_degrades(tmp_path):
    extractor = _project_with_ambiguous_schema(tmp_path)
    output = extractor.extract_schema({"kind": "tool", "schema_name": "dup"})
    assert output.is_schemaless is True
    assert output.json_schema is None
