"""An action that completed reading the staged input, then gains a dependency (#1925).

Its input is now another action's output, not the staged files. The run treats the
change as an edit: the answers stand and each run warns until --rerun. It does not
report the staged files as removed, and it does not reopen the action and its readers
as if new input had arrived.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests._support.agac_cli import run_agac

WORKFLOW = "wf"

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def read(data: Any, *args: Any) -> dict:
    return {"kind": "k-" + data["source"]["id"]}


@udf_tool
def tag(data: Any, *args: Any) -> dict:
    return {"tag": data["source"]["id"] + "|" + str((data.get("read") or {}).get("kind"))}


@udf_tool
def final(data: Any, *args: Any) -> dict:
    return {"out": data["tag"]["tag"]}
"""


def _workflow(tag_reads_read: bool) -> str:
    dependencies = "\n    dependencies: [read]" if tag_reads_read else ""
    observe = "[source.*, read.kind]" if tag_reads_read else "[source.*]"
    return f"""name: {WORKFLOW}
description: "An action gains a dependency"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: read
    kind: tool
    impl: read
    intent: "Read"
    schema: {{ kind: string }}
    context_scope: {{ observe: [source.*] }}
  - name: tag
    kind: tool
    impl: tag
    intent: "Tag"{dependencies}
    schema: {{ tag: string }}
    context_scope: {{ observe: {observe} }}
  - name: final
    kind: tool
    impl: final
    intent: "Final"
    dependencies: [tag]
    schema: {{ out: string }}
    context_scope: {{ observe: [tag.tag] }}
"""


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    for folder in ("agent_io/staging", "agent_config"):
        (workflow / folder).mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        "project_name: gains\ntool_path: [tools]\nschema_path: schema\n"
    )
    (root / "tools" / WORKFLOW / "tools.py").write_text(TOOLS)
    _write_workflow(root, tag_reads_read=False)
    staged = workflow / "agent_io" / "staging" / "in.json"
    staged.write_text(json.dumps([{"id": "A"}, {"id": "B"}]))
    return root


def _write_workflow(root: Path, *, tag_reads_read: bool) -> None:
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(_workflow(tag_reads_read))


def _run(root: Path, *extra: str) -> str:
    result = run_agac(root, "run", "-a", WORKFLOW, "-u", "tools", *extra)
    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == 0, output
    return output


def _tags(root: Path) -> list[str]:
    result = run_agac(root, "records", "-w", WORKFLOW, "-A", "tag", "--field", "content.tag.tag")
    assert result.returncode == 0, result.stdout + result.stderr
    return sorted(json.loads(result.stdout))


class TestAnActionThatGainsADependency:
    def test_the_run_warns_of_an_edit_and_not_of_removed_input(self, tmp_path):
        root = _project(tmp_path)
        _run(root)
        _write_workflow(root, tag_reads_read=True)

        output = _run(root)

        assert "The input files of tag changed" not in output
        assert "tag was edited since it completed (context scope, dependencies)" in output
        assert "--rerun tag" in output
        # Neither the action nor what reads it runs again as if new input had arrived.
        assert "tag — already complete" in output
        assert "final — already complete" in output

    def test_the_edit_still_warns_on_the_next_run_while_the_old_answers_stand(self, tmp_path):
        root = _project(tmp_path)
        _run(root)
        _write_workflow(root, tag_reads_read=True)
        _run(root)

        output = _run(root)

        assert "tag was edited since it completed" in output
        assert _tags(root) == ["A|None", "B|None"]

    def test_rerun_answers_each_record_from_the_new_dependency(self, tmp_path):
        root = _project(tmp_path)
        _run(root)
        _write_workflow(root, tag_reads_read=True)
        _run(root)

        output = _run(root, "--rerun", "tag")

        assert "tag was edited since it completed" not in output
        assert _tags(root) == ["A|k-A", "B|k-B"]
