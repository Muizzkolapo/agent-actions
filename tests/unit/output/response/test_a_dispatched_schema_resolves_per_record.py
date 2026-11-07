"""What a `schema: dispatch_task('fn')` resolves to for one record, and what then reads it.

The function returns one name from the action's `schema_options`. Each test removes one
step and fails: loading the chosen file, the project's required_by_default on it, the
record-level failure type, and the model call and output check that read the record's
schema.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.errors.processing import SchemaDispatchError
from agent_actions.output.response.context_data import _dispatched_schema, _load_inline_schema
from agent_actions.processing.helpers import (
    _choose_dispatched_schema,
    _validate_llm_output_schema,
    run_dynamic_agent,
)

DISPATCH = "dispatch_task('pick_schema')"
OPTIONS = ["topic_answer", "page_label"]


def _project(root: Path, tool_body: str, required_by_default: bool = True) -> Path:
    (root / "agent_actions.yml").write_text(
        f"required_by_default: {str(required_by_default).lower()}\nschema_path: schema\n"
    )
    (root / "schema").mkdir()
    for name, field in (("topic_answer", "topic"), ("page_label", "label")):
        (root / "schema" / f"{name}.yml").write_text(
            f"name: {name}\nfields:\n  - id: {field}\n    type: string\n"
        )
    tools = root / "tools"
    tools.mkdir()
    (tools / "pick_schema.py").write_text(f"def pick_schema(context_json):\n    {tool_body}\n")
    return tools


def _config(root: Path) -> dict:
    return {
        "name": "a",
        "schema": DISPATCH,
        "schema_options": OPTIONS,
        "model_vendor": "openai",
        "_project_root": str(root),
    }


def _resolve(root: Path, tools: Path) -> dict:
    schema, _ = _load_inline_schema(
        DISPATCH, str(tools), "{}", _config(root), {}, project_root=root
    )
    return schema


def test_a_chosen_name_loads_that_schema_file(tmp_path):
    _project(tmp_path, "return 'page_label'")

    loaded = _dispatched_schema("pick_schema", "page_label", OPTIONS, tmp_path)

    assert [field["id"] for field in loaded["fields"]] == ["label"]


def test_a_listed_name_with_no_file_fails_the_record(tmp_path):
    _project(tmp_path, "return 'no_such_schema'")

    with pytest.raises(SchemaDispatchError, match="returned the schema name 'no_such_schema'"):
        _dispatched_schema("pick_schema", "no_such_schema", ["no_such_schema"], tmp_path)


@pytest.mark.parametrize("required_by_default", [True, False])
def test_a_chosen_schema_follows_the_project_required_by_default(tmp_path, required_by_default):
    tools = _project(tmp_path, "return 'topic_answer'", required_by_default)

    assert _resolve(tmp_path, tools)["required_by_default"] is required_by_default


def test_a_function_that_raises_fails_the_record_not_the_action(tmp_path):
    tools = _project(tmp_path, "raise KeyError('page_id')")

    with pytest.raises(SchemaDispatchError, match="failed for this record") as failed:
        _resolve(tmp_path, tools)

    assert not isinstance(failed.value, ConfigurationError)


def test_the_output_check_reads_the_schema_the_record_was_given(tmp_path, caplog):
    tools = _project(tmp_path, "return 'topic_answer'")

    record_config, _ = _choose_dispatched_schema(_config(tmp_path), {"source": {}}, str(tools))
    with caplog.at_level(logging.WARNING):
        _validate_llm_output_schema([{"verdict": "wrong shape"}], record_config, "a")

    assert [field["id"] for field in record_config["schema"]["fields"]] == ["topic"]
    assert any("Schema validation warning for 'a'" in r.getMessage() for r in caplog.records)


def test_the_action_config_alone_gives_the_output_check_nothing_to_read(tmp_path, caplog):
    """The control: the action's own config holds only the dispatch string."""
    with caplog.at_level(logging.WARNING):
        _validate_llm_output_schema([{"verdict": "wrong shape"}], _config(tmp_path), "a")

    assert not any("Schema validation warning" in r.getMessage() for r in caplog.records)


def test_a_record_run_sends_and_checks_the_schema_it_was_given(tmp_path, caplog):
    """Through run_dynamic_agent: the model call gets the record's schema, and so does the check."""
    tools = _project(tmp_path, "return 'topic_answer'")
    sent: list[dict] = []

    def fake_call(config, *args, **kwargs):
        sent.append(config)
        return [{"verdict": "wrong shape"}]

    with (
        patch("agent_actions.llm.realtime.builder.create_dynamic_agent", side_effect=fake_call),
        caplog.at_level(logging.WARNING),
    ):
        run_dynamic_agent(_config(tmp_path), "a", {"source": {}}, "prompt", tools_path=str(tools))

    (config,) = sent
    assert [field["id"] for field in config["schema"]["fields"]] == ["topic"]
    assert any("Schema validation warning for 'a'" in r.getMessage() for r in caplog.records)
