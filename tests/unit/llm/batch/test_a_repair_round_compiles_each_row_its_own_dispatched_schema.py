"""A batch repair round compiles each row's dispatched schema again, from that row.

The tool reads the record it is handed, so a call with no record context fails that
row: every row arriving with its own schema shows each call had its record.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator

TOOL = """\
import json


def pick_schema(context_json):
    page_id = json.loads(context_json)["source"]["page_id"]
    return "topic_answer" if page_id == "p1" else "verdict_answer"
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "agent_actions.yml").write_text("required_by_default: true\nschema_path: schema\n")
    (tmp_path / "schema").mkdir()
    for name, field in (("topic_answer", "topic"), ("verdict_answer", "verdict")):
        (tmp_path / "schema" / f"{name}.yml").write_text(
            f"name: {name}\nfields:\n  - id: {field}\n    type: string\n"
        )
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "pick_schema.py").write_text(TOOL)
    return tmp_path


def _sent_tasks(project: Path, attempt: int, feedback_by_id: dict[str, str] | None) -> list[dict]:
    agent_config = {
        "agent_type": "label_page",
        "action_name": "label_page",
        "model_vendor": "openai",
        "model_name": "gpt-4o",
        "json_mode": True,
        "granularity": "record",
        "schema": "dispatch_task('pick_schema')",
        "schema_options": ["topic_answer", "verdict_answer"],
        "tool_path": [str(project / "tools")],
        "_project_root": str(project),
        "context_scope": {"observe": ["source.page_id"]},
    }
    data = [
        {"target_id": f"t{i}", "source_guid": f"sg{i}", "content": {"page_id": f"p{i}"}}
        for i in (1, 2)
    ]
    provider = MagicMock()
    provider.prepare_tasks.return_value = []
    preparator = BatchTaskPreparator(action_indices={}, dependency_configs={})
    with patch(
        "agent_actions.prompt.formatter.PromptFormatter.get_raw_prompt", return_value="Label it."
    ):
        preparator.prepare_tasks(
            agent_config=agent_config,
            data=data,
            provider=provider,
            output_directory=str(project / "out"),
            attempt=attempt,
            feedback_by_id=feedback_by_id,
        )
    return provider.prepare_tasks.call_args.args[0]


def _fields_by_target(tasks: list[dict]) -> dict[str, list[str]]:
    def fields(schema) -> list[str]:
        found = json.loads(json.dumps(schema))
        while isinstance(found, dict) and "properties" not in found:
            found = found.get("schema") or found.get("json_schema") or {}
        return sorted(found.get("properties", {}))

    return {task["target_id"]: fields(task["compiled_schema"]) for task in tasks}


def test_a_first_round_sends_each_row_its_own_schema(project):
    tasks = _sent_tasks(project, attempt=0, feedback_by_id=None)

    assert _fields_by_target(tasks) == {"t1": ["topic"], "t2": ["verdict"]}


def test_a_repair_round_compiles_each_row_its_own_schema_again(project):
    tasks = _sent_tasks(project, attempt=1, feedback_by_id={"t1": "fix it", "t2": "fix it"})

    assert _fields_by_target(tasks) == {"t1": ["topic"], "t2": ["verdict"]}
    assert all(task["prompt"].endswith("fix it") for task in tasks)
