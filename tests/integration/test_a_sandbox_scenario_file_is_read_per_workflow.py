"""A sandbox run of workflow `<wf>` reads `sandbox.<wf>.yml`, else `sandbox.yml`.

The scenario names actions of one workflow, and a project holds several. Here the
project has `catalog` (tools `search`, `lookup`) and `other` (tool `find`). A scenario for
`catalog` in `sandbox.catalog.yml` leaves `other` on its own file, or on `happy`; names
stay checked strictly, and a `sandbox.yml` that names another workflow's actions is
refused with a line that names the per-workflow file.
"""

from __future__ import annotations

from pathlib import Path

from tests._support.agac_cli import run_agac
from tests.integration.test_a_sandbox_scenario_stubs_a_tool_action import (
    ENV,
    STUB_SEARCH,
    _called,
    _ok,
    _project,
    _said,
)

OTHER = "other"
OTHER_CONFIG = """name: other
description: "One tool finds each book"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: find
    kind: tool
    intent: "Find the book"
    impl: find_book
    schema: find_output
    context_scope: { observe: [source.title] }
"""
OTHER_TOOLS = """from pathlib import Path
from typing import Any

from agent_actions import udf_tool

CALLED = Path(__file__).resolve().parents[2] / "called"


@udf_tool()
def find_book(data: dict[str, Any]) -> dict[str, Any]:
    CALLED.mkdir(exist_ok=True)
    (CALLED / "find").write_text("called")
    return {"title": data["source"]["title"], "found_by": "the find service"}
"""
OTHER_SCHEMA = (
    "name: find_output\nfields:\n"
    "  - {id: title, type: string, required: true}\n"
    "  - {id: found_by, type: string, required: true}\n"
)
REFUSED = "names no LLM action or tool action of the workflow"
HINT = "put a scenario for one workflow in sandbox.<workflow>.yml"


def _two_workflows(base: Path, files: dict[str, str]) -> Path:
    root = _project(base)
    workflow_dir = root / "agent_workflow" / OTHER
    (workflow_dir / "agent_config").mkdir(parents=True)
    (workflow_dir / "agent_io" / "staging").mkdir(parents=True)
    (workflow_dir / "agent_config" / f"{OTHER}.yml").write_text(OTHER_CONFIG)
    (workflow_dir / "agent_io" / "staging" / "books.json").write_text('[{"title": "Dune"}]')
    (root / "schema" / OTHER).mkdir()
    (root / "schema" / OTHER / "find_output.yml").write_text(OTHER_SCHEMA)
    (root / "tools" / OTHER).mkdir()
    (root / "tools" / OTHER / "other_tools.py").write_text(OTHER_TOOLS)
    for name, text in files.items():
        (root / name).write_text(text)
    return root


def _run(root: Path, workflow: str, *args: str):
    return run_agac(root, "run", "-w", workflow, "--sandbox", *args, env=ENV)


def test_a_scenario_for_one_workflow_in_its_own_file_leaves_the_other_alone(tmp_path):
    root = _two_workflows(tmp_path, {"sandbox.catalog.yml": STUB_SEARCH})

    other = _ok(_run(root, OTHER))
    assert _called(root) == {"find"}
    assert "SANDBOX scenario happy: 0 errors" in other.stdout, _said(other)

    catalog = _ok(_run(root, "catalog"))
    assert _called(root) == {"find", "lookup"}
    assert "SANDBOX scenario sandbox.catalog.yml: 0 errors" in catalog.stdout, _said(catalog)


def test_the_workflow_s_own_file_wins_over_sandbox_yml(tmp_path):
    root = _two_workflows(
        tmp_path,
        {"sandbox.catalog.yml": STUB_SEARCH, "sandbox.yml": "actions:\n  find: {stub: true}\n"},
    )

    _ok(_run(root, "catalog"))
    _ok(_run(root, OTHER))

    assert _called(root) == {"lookup"}


def test_inspect_of_the_other_workflow_reads_its_own_scenario(tmp_path):
    root = _two_workflows(tmp_path, {"sandbox.catalog.yml": STUB_SEARCH})

    shown = run_agac(root, "inspect", "-w", OTHER, "--sandbox", "action", "find")

    assert shown.returncode == 0, _said(shown)
    assert "stubbed" not in _said(shown)


def test_a_scenario_path_wins_over_the_workflow_s_own_file(tmp_path):
    root = _two_workflows(tmp_path, {"sandbox.catalog.yml": STUB_SEARCH})
    path = tmp_path / "plain.yml"
    path.write_text("seed: 3\n")

    _ok(_run(root, "catalog", "--scenario", str(path)))

    assert _called(root) == {"search", "lookup"}


def test_sandbox_yml_naming_another_workflow_s_tool_is_refused_with_the_hint(tmp_path):
    root = _two_workflows(tmp_path, {"sandbox.yml": STUB_SEARCH})

    ran = _run(root, OTHER)
    shown = run_agac(root, "inspect", "-w", OTHER, "--sandbox", "action", "find")

    for result in (ran, shown):
        said = _said(result)
        assert result.returncode != 0, said
        assert f"actions.search: {REFUSED}" in said, said
        assert HINT in said, said
    assert _called(root) == set()


def test_a_project_of_one_workflow_is_refused_without_the_hint(tmp_path):
    root = _project(tmp_path, "actions:\n  find: {stub: true}\n")

    said = _said(_run(root, "catalog"))

    assert f"actions.find: {REFUSED}" in said, said
    assert HINT not in said, said


def test_sandbox_catalog_yml_is_refused_without_the_hint(tmp_path):
    root = _two_workflows(tmp_path, {"sandbox.catalog.yml": "actions:\n  find: {stub: true}\n"})

    said = _said(_run(root, "catalog"))

    assert "Scenario sandbox.catalog.yml has 1 problem(s)" in said, said
    assert HINT not in said, said
