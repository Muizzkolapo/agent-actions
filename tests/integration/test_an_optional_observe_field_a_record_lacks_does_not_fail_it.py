"""An action that observes a field as optional runs every record, whatever each one holds.

`note_direct` gives `summary` for one record and not for the other, or is skipped for it
by a guard. Three actions read `note_direct.summary`: an LLM action whose prompt prints
it, a tool that runs per record and a tool that runs per file. Observed as optional, in
either form, no record fails, the tools are handed the field as `None` or as its stated
default, and preflight has no null warning to give. Observed without the mark, the
record that lacks the field still fails and the warning is still given.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

WORKFLOW = "optional_observe"
READERS = ("publish", "relay", "roll_up")

TOOLS = """\
import json
from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import FileUDFResult, Granularity


@udf_tool
def make_note(data: Any, *args) -> list[dict]:
    text = str(((data or {}).get("source") or {}).get("text"))
    if text == "two":
        return [{"kind": "k-two", "note": "n-two"}]
    return [{"kind": "k-" + text, "summary": "s-" + text}]


@udf_tool
def relay_input(data: Any, *args) -> list[dict]:
    return [{"handed": json.dumps((data or {}).get("note_direct"), sort_keys=True)}]


@udf_tool(granularity=Granularity.FILE)
def roll_up_input(data: Any, *args) -> Any:
    return FileUDFResult(
        [
            {"source_index": i, "data": {"handed": json.dumps(dict(item), sort_keys=True)}}
            for i, item in enumerate(data or [])
        ]
    )
"""

NOTE_SCHEMA = """\
name: note
fields:
  - id: kind
    type: string
  - id: summary
    type: string
    required: false
  - id: note
    type: string
    required: false
"""

OUT_SCHEMA = """\
name: out
fields:
  - id: summary
    type: string
"""

HANDED_SCHEMA = """\
name: handed
fields:
  - id: handed
    type: string
"""

PROMPT = """\
{prompt Publish}
Restate {{ source.text }} ({{ note_direct.kind }}): [{{ note_direct.summary }}]
{end_prompt}

{prompt PublishBelowAGuard}
Restate {{ source.text }}: [{{ note_direct.summary }}]
{end_prompt}
"""

CONFIG = """\
name: optional_observe
description: "Three actions read a field one record lacks"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: agac-provider
  model_name: m
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: note_direct
    kind: tool
    intent: "Note"
    schema: note
    impl: make_note
    context_scope: {{ observe: [source.text] }}
{guard}  - name: publish
    dependencies: [note_direct]
    intent: "Publish"
    schema: out
    prompt: $optional_observe.{prompt}
    context_scope:
      observe:
        - source.text
{kind}        - {entry}
  - name: relay
    kind: tool
    dependencies: [note_direct]
    intent: "Report what a record tool is handed"
    schema: handed
    impl: relay_input
    context_scope:
      observe:
{kind}        - {entry}
  - name: roll_up
    kind: tool
    granularity: File
    dependencies: [note_direct]
    intent: "Report what a file tool is handed"
    schema: handed
    impl: roll_up_input
    context_scope:
      observe:
{kind}        - {entry}
"""

GUARD = "    guard: { condition: \"source.text == 'one'\", on_false: skip }\n"
SUFFIX = "note_direct.summary?"
MAPPING = '{ field: note_direct.summary, optional: true, default: "none" }'
REQUIRED = "note_direct.summary"
NULL_WARNING = "'note_direct.summary' may be null at runtime"

FORMS = pytest.mark.parametrize(
    "entry, missing", [(SUFFIX, None), (MAPPING, "none")], ids=["suffix", "mapping-default"]
)
MODES = pytest.mark.parametrize("run_mode", ["online", "batch"])


def _project(base: Path, entry: str, run_mode: str = "online", guard: str = "") -> Path:
    root = base / "project"
    directory = root / "agent_workflow" / WORKFLOW
    (directory / "agent_config").mkdir(parents=True)
    (directory / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\nschema_path: schema\n"
        'tool_path: ["tools"]\n'
    )
    (root / "schema" / WORKFLOW / "note.yml").write_text(NOTE_SCHEMA)
    (root / "schema" / WORKFLOW / "out.yml").write_text(OUT_SCHEMA)
    (root / "schema" / WORKFLOW / "handed.yml").write_text(HANDED_SCHEMA)
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPT)
    (root / "tools" / WORKFLOW / "optional_observe_tools.py").write_text(TOOLS)
    # `kind` is observed without the mark, so only where no guard can skip its action.
    (directory / "agent_config" / f"{WORKFLOW}.yml").write_text(
        CONFIG.format(
            run_mode=run_mode,
            guard=guard,
            entry=entry,
            kind="" if guard else "        - note_direct.kind\n",
            prompt="PublishBelowAGuard" if guard else "Publish",
        )
    )
    (directory / "agent_io" / "staging" / "rows.json").write_text(
        json.dumps([{"text": "one"}, {"text": "two"}])
    )
    return root


def _agac(root: Path, *args: str):
    return run_agac(
        root,
        *args,
        env={"OPENAI_API_KEY": "sk-not-used", "AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )


def _run_to_the_end(root: Path) -> str:
    """Run until nothing asks to be run again: a batch action pauses once it has submitted."""
    transcript: list[str] = []
    for attempt in range(6):
        result = _agac(root, "run", "-a", WORKFLOW, *(["--fresh"] if attempt == 0 else []))
        transcript.append(result.stdout + result.stderr)
        if "run again" not in transcript[-1]:
            return "\n".join(transcript)
    raise AssertionError("the workflow never stopped asking to be run again")


def _failed(root: Path) -> list[tuple[str, str]]:
    db = root / "agent_workflow" / WORKFLOW / "agent_io" / "store" / f"{WORKFLOW}.db"
    with sqlite3.connect(db) as con:
        return con.execute(
            "select action_name, coalesce(reason, '') from record_disposition "
            "where disposition = 'failed'"
        ).fetchall()


def _answers(root: Path, action: str) -> list[dict]:
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        rows = [
            row
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
    finally:
        backend.close()
    return [row["content"][action] for row in rows if row["content"].get(action)]


def _handed(root: Path, action: str) -> list[dict]:
    """What the tool was handed for each record, the record with a summary first."""
    handed = [json.loads(answer["handed"]) for answer in _answers(root, action)]
    return sorted(handed, key=lambda item: item.get("summary") != "s-one")


@MODES
@FORMS
def test_a_record_whose_upstream_gave_no_such_field_passes_every_reader(
    tmp_path, entry, missing, run_mode
):
    """Holds in online and batch mode, for a record tool and for a file tool."""
    root = _project(tmp_path, entry, run_mode)

    transcript = _run_to_the_end(root)

    assert _failed(root) == [], transcript
    assert len(_answers(root, "publish")) == 2, transcript
    expected = [
        {"kind": "k-one", "summary": "s-one"},
        {"kind": "k-two", "summary": missing},
    ]
    assert _handed(root, "relay") == expected
    assert _handed(root, "roll_up") == expected


@MODES
@FORMS
def test_a_record_a_guard_skipped_the_upstream_for_passes_every_reader(
    tmp_path, entry, missing, run_mode
):
    root = _project(tmp_path, entry, run_mode, guard=GUARD)

    transcript = _run_to_the_end(root)

    assert _failed(root) == [], transcript
    assert NULL_WARNING not in transcript
    assert len(_answers(root, "publish")) == 2, transcript
    assert _handed(root, "relay") == [{"summary": "s-one"}, {"summary": missing}]
    assert _handed(root, "roll_up") == [{"summary": "s-one"}, {"summary": missing}]


@MODES
def test_the_same_field_without_the_mark_still_fails_the_record_that_lacks_it(tmp_path, run_mode):
    """Each of the three readers fails the record that lacks the field."""
    root = _project(tmp_path, REQUIRED, run_mode)

    _run_to_the_end(root)

    failed = {action for action, _ in _failed(root)}
    assert failed == set(READERS)
    assert len(_answers(root, "publish")) == 1


@FORMS
def test_inspect_gives_no_null_warning_for_an_optional_field_of_a_skipped_upstream(
    tmp_path, entry, missing
):
    """Neither the null warning nor the prompt-contract warning is given."""
    root = _project(tmp_path, entry, guard=GUARD)

    result = _agac(root, "inspect", "-a", WORKFLOW)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "may be null at runtime" not in output, output
    assert "does not guarantee 'summary'" not in output, output


def test_inspect_still_gives_it_for_the_same_field_without_the_mark(tmp_path):
    root = _project(tmp_path, REQUIRED, guard=GUARD)

    result = _agac(root, "inspect", "-a", WORKFLOW)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert output.count(NULL_WARNING) == len(READERS), output
    assert "does not guarantee" in output, output


def test_inspect_shows_the_entry_with_its_mark(tmp_path):
    root = _project(tmp_path, MAPPING)

    result = _agac(root, "inspect", "context", "-a", WORKFLOW, "publish", "--json")

    assert result.returncode == 0, result.stdout + result.stderr
    scope = json.loads(result.stdout)["context_scope"]
    assert scope["observe"] == ["source.text", "note_direct.kind", "note_direct.summary?"]
    assert scope["passthrough"] == []


@pytest.mark.parametrize(
    "entry, problem",
    [
        ("note_direct.*?", "a wildcard cannot be optional"),
        ("note_direct?.summary", "at the end of the reference"),
    ],
    ids=["wildcard", "misplaced"],
)
def test_an_entry_that_cannot_be_optional_stops_the_load_naming_it(tmp_path, entry, problem):
    root = _project(tmp_path, entry)

    result = _agac(root, "inspect", "-a", WORKFLOW)
    output = " ".join((result.stdout + result.stderr).split())

    assert result.returncode != 0, output
    assert entry in output
    assert problem in output


def test_a_field_the_upstream_schema_does_not_declare_is_refused_though_optional(tmp_path):
    root = _project(tmp_path, "note_direct.sumary?")

    result = _agac(root, "inspect", "-a", WORKFLOW)
    output = " ".join((result.stdout + result.stderr).split())

    assert result.returncode != 0, output
    assert "Field 'sumary' not found in action 'note_direct' output schema" in output
    assert "sumary?" not in output
