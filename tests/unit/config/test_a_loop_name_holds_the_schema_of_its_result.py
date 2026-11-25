"""The name of a loop holds the schema of its `result`, with the fields it requires.

The load gave a loop's name, a built-in pick, the schema a join gets (each field of its
sources, none required) before the loop step could give it the schema of the result. A
prompt that read the loop's name then got a warning that the field is not guaranteed. The
pick runs no project code, so the check that a tool returns its required fields skips it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.validation.dag_schema_fit_validator import find_dag_schema_compatibility_gaps

WF = "agent_workflow/wf/agent_config/wf.yml"

BRANCH = {
    "branch": "round",
    "description": "Write, then check",
    "inputs": {"spec": "the spec", "prior": "the previous check"},
    "outputs": ["check"],
    "actions": [
        {
            "name": "write",
            "intent": "write",
            "prompt": "$wf.Write",
            "schema": "draft",
            "dependencies": ["spec"],
            "context_scope": {"observe": ["spec.topic", "prior.*"]},
        },
        {
            "name": "check",
            "kind": "tool",
            "impl": "check_it",
            "intent": "check",
            "schema": "verdict",
            "dependencies": ["write"],
            "context_scope": {"observe": ["write.text", "prior.*"]},
        },
    ],
}
WORKFLOW = {
    "name": "wf",
    "description": "d",
    "defaults": {"model_vendor": "openai", "model_name": "gpt-4o-mini", "api_key": "K"},
    "actions": [
        {
            "name": "spec",
            "kind": "tool",
            "impl": "make_spec",
            "intent": "spec",
            "schema": {"topic": "string"},
            "context_scope": {"observe": ["source.topic"]},
        },
        {
            "loop": "rounds",
            "include": "round",
            "max_iterations": 2,
            "inputs": {"spec": "spec"},
            "feedback": {"prior": "check"},
            "until": "check.passed == true",
            "result": "check",
        },
    ],
}
SCHEMAS = {
    "draft": "name: draft\nfields:\n  - {id: text, type: string, required: true}\n",
    "verdict": (
        "name: verdict\nfields:\n"
        "  - {id: passed, type: boolean, required: true}\n"
        "  - {id: note, type: string}\n"
    ),
}


def _render(root: Path) -> dict[str, dict]:
    (root / "agent_actions.yml").write_text("schema_path: schema\ntool_path: [tools]\n")
    (root / "prompt_store").mkdir()
    (root / "prompt_store" / "wf.md").write_text(
        "{prompt Write}\nWrite about {{ spec.topic }}.\n{end_prompt}\n"
    )
    (root / "branches").mkdir()
    (root / "branches" / "round.yml").write_text(yaml.safe_dump(BRANCH, sort_keys=False))
    (root / "schema").mkdir()
    for name, text in SCHEMAS.items():
        (root / "schema" / f"{name}.yml").write_text(text)
    workflow = root / WF
    workflow.parent.mkdir(parents=True)
    workflow.write_text(yaml.safe_dump(WORKFLOW, sort_keys=False))
    rendered = yaml.safe_load(
        render_pipeline_with_templates(
            workflow, root / "templates", schema_dir=root / "schema", project_root=root
        )
    )
    return {action["name"]: action for action in rendered["actions"]}


def test_the_loop_name_takes_the_schema_of_the_result_with_its_required_fields(tmp_path):
    schema = _render(tmp_path)["rounds"]["schema"]

    assert schema["name"] == "rounds_result"
    assert [(f["id"], f.get("required", False)) for f in schema["fields"]] == [
        ("passed", True),
        ("note", False),
    ]


def test_a_built_in_tool_is_not_held_to_return_its_required_fields():
    pick = {
        "kind": "tool",
        "_builtin": {"tool": "pick", "of": ["a", "b"]},
        "json_output_schema": {"type": "object", "required": ["passed"]},
    }
    tool = {**pick, "_builtin": None, "impl": "check_it"}

    assert find_dag_schema_compatibility_gaps({"rounds": pick, "check": tool}) == {
        "check": ["passed"]
    }


def test_the_loop_name_takes_no_rule_of_the_result(tmp_path, monkeypatch):
    # A rule of the result reads the last iteration's names; a record that left the loop
    # early holds none of them, so the loop's name keeps the fields and drops the rules.
    ruled = (
        "name: verdict\nfields:\n"
        "  - id: passed\n    type: boolean\n    required: true\n"
        "    expectations:\n      - {id: is_set, type: not_null}\n"
        "  - {id: note, type: string}\n"
        "expectations:\n"
        "  - id: a_note_when_failed\n    type: expression\n"
        '    params: {condition: "passed or note IS NOT NULL"}\n'
    )
    monkeypatch.setitem(SCHEMAS, "verdict", ruled)

    actions = _render(tmp_path)
    schema = actions["rounds"]["schema"]

    assert [(f["id"], f.get("required", False)) for f in schema["fields"]] == [
        ("passed", True),
        ("note", False),
    ]
    assert "expectations" not in schema
    assert all("expectations" not in field for field in schema["fields"])
    # The result itself keeps its rules.
    result = actions["rounds_iter2__check"]["schema"]
    assert result["expectations"][0]["id"] == "a_note_when_failed"
    assert result["fields"][0]["expectations"][0]["id"] == "is_set"
