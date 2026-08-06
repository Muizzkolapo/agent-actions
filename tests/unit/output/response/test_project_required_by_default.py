"""Project-level ``required_by_default`` in agent_actions.yml.

A project may set ``required_by_default: true`` at the top level of
``agent_actions.yml`` to make flat schema fields required-by-default across
every schema, instead of adding the flag to each schema file. A named schema
loaded through :meth:`SchemaLoader.load_schema` inherits the project setting
unless the schema file declares its own ``required_by_default`` (per-schema
override wins). Explicit per-field markers still take precedence over both.
"""

import textwrap

from agent_actions.output.response.loader import SchemaLoader
from agent_actions.output.response.vendor_compilation import compile_unified_schema
from agent_actions.validation.schema_output_validator import validate_output_against_schema


def _project(tmp_path, *, project_flag: str, schema_body: str) -> None:
    """Write a minimal project: agent_actions.yml + schema/foo.yml."""
    (tmp_path / "agent_actions.yml").write_text(
        textwrap.dedent(
            f"""\
            schema_path: schema
            {project_flag}
            """
        )
    )
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / "foo.yml").write_text(textwrap.dedent(schema_body))


_UNMARKED = """\
    name: foo
    fields:
      - id: a
        type: string
      - id: b
        type: string
"""


def test_project_flag_makes_unmarked_field_required(tmp_path):
    """required_by_default: true in agent_actions.yml → unmarked 'b' is required."""
    _project(tmp_path, project_flag="required_by_default: true", schema_body=_UNMARKED)
    loaded = SchemaLoader.load_schema("foo", project_root=tmp_path)
    report = validate_output_against_schema({"a": "x"}, loaded, "act")
    assert not report.is_compliant
    assert "b" in report.missing_required


def test_no_project_flag_keeps_unmarked_field_optional(tmp_path):
    """Absent flag → v0.2.8 behavior preserved: unmarked 'b' stays optional."""
    _project(tmp_path, project_flag="", schema_body=_UNMARKED)
    loaded = SchemaLoader.load_schema("foo", project_root=tmp_path)
    report = validate_output_against_schema({"a": "x"}, loaded, "act")
    assert report.is_compliant
    assert "b" in report.missing_optional


def test_project_flag_false_keeps_unmarked_field_optional(tmp_path):
    """required_by_default: false is explicit opt-out; unmarked 'b' stays optional."""
    _project(tmp_path, project_flag="required_by_default: false", schema_body=_UNMARKED)
    loaded = SchemaLoader.load_schema("foo", project_root=tmp_path)
    report = validate_output_against_schema({"a": "x"}, loaded, "act")
    assert report.is_compliant
    assert "b" in report.missing_optional


def test_schema_file_override_beats_project_flag(tmp_path):
    """A schema declaring its own required_by_default wins over the project setting."""
    schema_body = """\
        name: foo
        required_by_default: false
        fields:
          - id: a
            type: string
          - id: b
            type: string
    """
    _project(tmp_path, project_flag="required_by_default: true", schema_body=schema_body)
    loaded = SchemaLoader.load_schema("foo", project_root=tmp_path)
    report = validate_output_against_schema({"a": "x"}, loaded, "act")
    assert report.is_compliant
    assert "b" in report.missing_optional


def test_project_flag_reaches_vendor_compiler(tmp_path):
    """The injected flag survives into the compiled vendor schema's required list."""
    _project(tmp_path, project_flag="required_by_default: true", schema_body=_UNMARKED)
    loaded = SchemaLoader.load_schema("foo", project_root=tmp_path)
    compiled = compile_unified_schema(loaded, "openai")
    assert set(compiled["schema"]["required"]) == {"a", "b"}


def test_no_flag_leaves_vendor_compiler_required_empty(tmp_path):
    """Without the project flag, unmarked fields stay out of the compiled required list."""
    _project(tmp_path, project_flag="", schema_body=_UNMARKED)
    loaded = SchemaLoader.load_schema("foo", project_root=tmp_path)
    compiled = compile_unified_schema(loaded, "openai")
    assert compiled["schema"]["required"] == []


def test_optional_field_still_opts_out_under_project_flag(tmp_path):
    """Safety: optional: true keeps a field optional even when the project flag is on."""
    schema_body = """\
        name: foo
        fields:
          - id: a
            type: string
          - id: b
            type: string
            optional: true
    """
    _project(tmp_path, project_flag="required_by_default: true", schema_body=schema_body)
    loaded = SchemaLoader.load_schema("foo", project_root=tmp_path)
    report = validate_output_against_schema({"a": "x"}, loaded, "act")
    assert report.is_compliant
    assert "b" in report.missing_optional
