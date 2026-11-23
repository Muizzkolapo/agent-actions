"""A tool action's catalog entry carries the function that implements it."""

from agent_actions.tooling.docs.generator import CatalogGenerator

WORKFLOW = """\
name: wf
actions:
  - name: clean
    kind: tool
    impl: clean_rows
  - name: summarize
    dependencies: [clean]
    model_vendor: openai
    model_name: gpt-4o-mini
"""

TOOL = {"signature": "clean_rows(data)", "docstring": "Clean.", "file_path": "tools/wf/t.py"}


def _catalog(tmp_path):
    (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n", encoding="utf-8")
    yaml_path = tmp_path / "wf.yml"
    yaml_path.write_text(WORKFLOW, encoding="utf-8")
    workflows = {"wf": {"rendered": None, "original": str(yaml_path)}}
    return CatalogGenerator(workflows, project_path=str(tmp_path)).generate(
        tool_functions_data={"clean_rows": TOOL}
    )


def test_a_tool_action_gets_its_tool_function(tmp_path):
    action = _catalog(tmp_path)["actions"]["wf.clean"]

    assert action["type"] == "tool"
    assert action["tool_function"] == TOOL


def test_an_llm_action_gets_no_tool_function(tmp_path):
    assert "tool_function" not in _catalog(tmp_path)["actions"]["wf.summarize"]
