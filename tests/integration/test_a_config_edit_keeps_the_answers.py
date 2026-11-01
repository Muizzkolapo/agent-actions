"""A config edit keeps the answers an action already holds.

An edit to an action's model, prompt, schema, guard, context scope or dependencies used to
reset it and every action reading it, so the next run answered every record again. A model
swapped partway through a long run threw that run away. Now the answers stand: records not
yet answered are answered under the edit, a warning names what changed, each prompt trace
row records the config it was answered under, and ``--rerun <action>`` answers the action
and its readers again when that is what the user wants.

`recap` reads one field of `stage_items` and writes what it saw; `after_recap` reads
`recap`; `bystander` reads `stage_items` and nothing the edits touch. Each tool writes a
line to `calls.log` per record, so a test sees which actions ran. Every run is its own
`agac` process. Only the fault is stood in for: a tool raising for a named item.
"""

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "examples" / "map_reduce_fanin_check"
WORKFLOW = "map_reduce_fanin_check"
FAULT = "fault.json"
CALLS = "calls.log"
ITEMS = ["alpha", "beta", "gamma"]
TEXT = {"alpha": "first item", "beta": "second item", "gamma": "third item"}
SAW_THE_ID = [f"{item}:-" for item in ITEMS]
SAW_THE_TEXT = [f"{item}:{TEXT[item]}" for item in ITEMS]
SCOPE = "observe: [stage_items.item_id, merge_direct.decision]"
WIDER_SCOPE = "observe: [stage_items.item_id, stage_items.text, merge_direct.decision]"

CONFIG = """name: map_reduce_fanin_check
description: "a config edit keeps the answers"
version: "1.0.0"

defaults:
  json_mode: true
  granularity: Record
  is_operational: true
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source:
    type: local
    folder: ./staging
    file_type: [json]

actions:
  - name: stage_items
    kind: tool
    impl: stage_items
    intent: "Stage"
    schema: { item_id: string, text: string }
    context_scope:
      observe: [source.item_id, source.text]

  - name: vote_direct
    kind: tool
    impl: cast_vote_direct
    dependencies: [stage_items]
    intent: "Vote"
    versions: { param: voter_id, range: [1, 2] }
    schema: { vote: string, voted_item: string }
    context_scope:
      observe: [stage_items.*]

  - name: merge_direct
    kind: tool
    impl: merge_votes
    dependencies: [vote_direct]
    intent: "Merge"
    version_consumption: { source: vote_direct, pattern: merge }
    schema: { decision: string, n_votes: integer }
    context_scope:
      observe: [vote_direct.*]

  - name: bystander
    kind: tool
    impl: logged_bystander
    dependencies: [stage_items]
    intent: "Reads nothing the edits touch"
    schema: { seen: string }
    context_scope:
      observe: [stage_items.item_id]

  - name: recap
    kind: tool
    impl: logged_recap
    dependencies: [merge_direct]
    intent: "Write what it saw"
    schema: { saw: string }
    context_scope:
      observe: [stage_items.item_id, merge_direct.decision]

  - name: after_recap
    kind: tool
    impl: logged_reader
    dependencies: [recap]
    intent: "Read the recap"
    schema: { echoed: string }
    context_scope:
      observe: [recap.*, stage_items.item_id]

  - name: summary
    dependencies: [stage_items]
    intent: "Say what the item is"
    prompt: "Say what you see of {{ stage_items.item_id }}."
    schema: { said: string }
    context_scope:
      observe: [stage_items.item_id]
"""

TOOLS = f"""import json
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


def _log(action: str, item: str) -> None:
    with open({CALLS!r}, "a") as calls:
        calls.write(action + ":" + item + "\\n")


@udf_tool()
def logged_recap(data: dict[str, Any]) -> dict[str, Any]:
    staged = data.get("stage_items") or {{}}
    item = staged.get("item_id", "?")
    fault = Path({FAULT!r})
    if fault.exists() and json.loads(fault.read_text())["item"] == item:
        raise KeyboardInterrupt()
    _log("recap", item)
    return {{"saw": item + ":" + staged.get("text", "-")}}


@udf_tool()
def logged_reader(data: dict[str, Any]) -> dict[str, Any]:
    item = (data.get("stage_items") or {{}}).get("item_id", "?")
    _log("after_recap", item)
    return {{"echoed": (data.get("recap") or {{}}).get("saw", "?")}}


@udf_tool()
def logged_bystander(data: dict[str, Any]) -> dict[str, Any]:
    item = (data.get("stage_items") or {{}}).get("item_id", "?")
    _log("bystander", item)
    return {{"seen": item}}
"""


def _workflow(root):
    return root / "agent_workflow" / WORKFLOW


def _config(root):
    return _workflow(root) / "agent_config" / f"{WORKFLOW}.yml"


def _statuses(root):
    return json.loads((_workflow(root) / "agent_io" / ".agent_status.json").read_text())


def _edit(root, old, new):
    text = _config(root).read_text()
    assert text.count(old) == 1, f"the config no longer has exactly one {old!r}"
    _config(root).write_text(text.replace(old, new))


def _agac(root, *args):
    """Run the command; ``printed`` is its output with the console's line wrapping undone."""
    result = run_agac(root, *args, env={"OPENAI_API_KEY": "sk-not-used"})
    result.printed = " ".join((result.stdout + result.stderr).split())
    return result


def _ran(root):
    """Which actions ran a record since the last call, as {action: sorted items}."""
    path = root / CALLS
    if not path.exists():
        return {}
    ran: dict[str, list[str]] = {}
    for line in path.read_text().splitlines():
        action, item = line.split(":", 1)
        ran.setdefault(action, []).append(item)
    path.unlink()
    return {action: sorted(items) for action, items in ran.items()}


def _backend(root):
    backend = get_storage_backend(workflow_path=str(_workflow(root)), workflow_name=WORKFLOW)
    backend.initialize()
    return backend


def _rows(root, action):
    backend = _backend(root)
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
    finally:
        backend.close()


def _recap_saw(root):
    return sorted(row["content"]["recap"]["saw"] for row in _rows(root, "recap"))


def _reader_echoed(root):
    return sorted(row["content"]["after_recap"]["echoed"] for row in _rows(root, "after_recap"))


def _traces(root, action):
    backend = _backend(root)
    try:
        return backend.get_prompt_traces(action)
    finally:
        backend.close()


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__"))
    (root / "tools" / WORKFLOW / "logged.py").write_text(TOOLS)
    _config(root).write_text(CONFIG)
    return root


@pytest.fixture
def completed(project):
    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode == 0, result.printed
    assert _recap_saw(project) == SAW_THE_ID
    assert _ran(project) == {"recap": ITEMS, "after_recap": ITEMS, "bystander": ITEMS}
    return project


EDITS = [
    pytest.param(SCOPE, WIDER_SCOPE, "context scope", id="context-scope"),
    pytest.param(
        "dependencies: [merge_direct]\n",
        "dependencies: [merge_direct, stage_items]\n",
        "dependencies",
        id="dependencies",
    ),
    pytest.param(
        "schema: { saw: string }",
        "schema: { saw: string, note: string }",
        "action config (prompt/schema/guard)",
        id="schema",
    ),
]


@pytest.mark.parametrize(("old", "new", "label"), EDITS)
def test_an_edit_to_a_completed_action_keeps_its_answers_and_its_readers(
    completed, old, new, label
):
    _edit(completed, old, new)

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {}
    assert _recap_saw(completed) == SAW_THE_ID
    assert _reader_echoed(completed) == SAW_THE_ID
    assert {name: _statuses(completed)[name]["status"] for name in ("recap", "after_recap")} == {
        "recap": "completed",
        "after_recap": "completed",
    }
    assert f"recap was edited since it completed ({label})" in result.printed
    assert "--rerun recap" in result.printed
    assert "resetting to pending" not in result.printed


def test_an_edit_to_the_workflow_default_model_runs_nothing_again(completed):
    _edit(completed, "  model_name: gpt-4o-mini\n", "  model_name: gpt-4o\n")

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {}
    assert "summary was edited since it completed (model)" in result.printed
    assert "resetting to pending" not in result.printed


def test_an_action_stopped_partway_keeps_what_it_finished_and_answers_the_rest_under_the_edit(
    project,
):
    (project / FAULT).write_text(json.dumps({"item": "beta"}))
    result = _agac(project, "run", "-a", WORKFLOW, "--fresh")
    assert result.returncode != 0, result.printed
    assert _ran(project).get("recap") == ["alpha"]

    (project / FAULT).unlink()
    _edit(project, SCOPE, WIDER_SCOPE)
    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _ran(project) == {"recap": ["beta", "gamma"], "after_recap": ITEMS}
    assert _recap_saw(project) == ["alpha:-", "beta:second item", "gamma:third item"]
    assert "recap was edited since its last run started (context scope)" in result.printed


def test_rerun_answers_the_action_and_its_readers_again_under_the_edit(completed):
    _edit(completed, SCOPE, WIDER_SCOPE)

    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "recap")

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {"recap": ITEMS, "after_recap": ITEMS}
    assert _recap_saw(completed) == SAW_THE_TEXT
    assert _reader_echoed(completed) == SAW_THE_TEXT

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {}
    assert "was edited since" not in result.printed


def test_rerun_of_an_unedited_action_answers_it_and_its_readers_again(completed):
    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "recap")

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {"recap": ITEMS, "after_recap": ITEMS}


def test_rerun_names_an_action_the_workflow_does_not_have(completed):
    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "no_such_action")

    assert result.returncode != 0
    assert f"--rerun: 'no_such_action' is not an action of {WORKFLOW}" in result.printed
    assert _ran(completed) == {}


def test_each_prompt_trace_row_records_the_config_it_was_answered_under(completed):
    before = _statuses(completed)["summary"]["answered_under"]
    traces = _traces(completed, "summary")
    assert len(traces) == len(ITEMS)
    assert [json.loads(row["answered_under"]) for row in traces] == [before] * len(ITEMS)

    _edit(
        completed,
        '    intent: "Say what the item is"\n',
        '    intent: "Say what the item is"\n    model_name: gpt-4o\n',
    )
    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "summary")

    assert result.returncode == 0, result.printed
    after = _statuses(completed)["summary"]["answered_under"]
    assert after["model_name"] == "gpt-4o"
    assert before["model_name"] == "gpt-4o-mini"
    assert [json.loads(row["answered_under"]) for row in _traces(completed, "summary")] == [
        after
    ] * len(ITEMS)


def _project_default(root, line):
    config = root / "agent_actions.yml"
    text = config.read_text()
    assert text.count("default_agent_config:\n") == 1
    config.write_text(text.replace("default_agent_config:\n", f"default_agent_config:\n  {line}\n"))


SUMMARY_INTENT = '    intent: "Say what the item is"\n'


@pytest.mark.parametrize(
    "setting",
    ["temperature: 0.9", "max_tokens: 50", "top_p: 0.5", "stop: END", "presence_penalty: 1.0"],
)
def test_a_generation_setting_on_the_action_is_named_as_an_edit(completed, setting):
    _edit(completed, SUMMARY_INTENT, f"{SUMMARY_INTENT}    {setting}\n")

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert "summary was edited since it completed (generation settings)" in result.printed
    assert "--rerun summary" in result.printed
    assert _statuses(completed)["summary"]["status"] == "completed"


def test_a_project_default_max_tokens_names_only_the_llm_actions(completed):
    _project_default(completed, "max_tokens: 50")

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert "summary was edited since it completed (generation settings)" in result.printed
    assert "recap was edited" not in result.printed
    assert "stage_items was edited" not in result.printed


def test_rerun_restamps_the_generation_settings(completed):
    _edit(completed, SUMMARY_INTENT, f"{SUMMARY_INTENT}    temperature: 0.9\n")

    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "summary")
    assert result.returncode == 0, result.printed
    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert "was edited since" not in result.printed


def test_a_reworded_intent_is_not_an_edit(completed):
    _edit(completed, SUMMARY_INTENT, '    intent: "Name the item"\n')

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert "was edited since" not in result.printed


def test_a_store_stamped_before_generation_settings_names_no_edit(completed):
    path = _workflow(completed) / "agent_io" / ".agent_status.json"
    statuses = json.loads(path.read_text())
    for details in statuses.values():
        details.pop("generation_hash", None)
        (details.get("answered_under") or {}).pop("generation_hash", None)
    path.write_text(json.dumps(statuses))
    _edit(completed, SUMMARY_INTENT, f"{SUMMARY_INTENT}    temperature: 0.9\n")

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert "was edited since" not in result.printed


TOOLS_FILE = Path("tools") / WORKFLOW / "logged.py"
RECAP_RETURNS = 'return {"saw": item + ":" + staged.get("text", "-")}'
GUARD = """from typing import Any

from agent_actions import udf_tool


@udf_tool()
def summary_gate(data: dict[str, Any]) -> bool:
    return True
"""


def _edit_tools(root, old, new):
    path = root / TOOLS_FILE
    text = path.read_text()
    assert text.count(old) == 1, f"the tools no longer have exactly one {old!r}"
    path.write_text(text.replace(old, new))


def test_an_edit_to_a_tools_code_is_named_at_every_action_its_file_serves(completed):
    _edit_tools(completed, RECAP_RETURNS, 'return {"saw": item + ":edited"}')

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {}
    assert _recap_saw(completed) == SAW_THE_ID
    for action in ("recap", "after_recap", "bystander"):
        assert f"{action} was edited since it completed (tool/guard code)" in result.printed
    assert "stage_items was edited" not in result.printed
    assert "summary was edited" not in result.printed


def test_rerun_answers_under_the_edited_code_and_restamps_it(completed):
    _edit_tools(completed, RECAP_RETURNS, 'return {"saw": item + ":edited"}')

    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "recap")
    assert result.returncode == 0, result.printed
    assert _recap_saw(completed) == [f"{item}:edited" for item in ITEMS]
    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert "recap was edited" not in result.printed
    assert "after_recap was edited" not in result.printed
    assert "bystander was edited since it completed (tool/guard code)" in result.printed


def test_an_edit_to_a_tool_file_no_action_uses_is_not_an_edit(project):
    unrelated = project / "tools" / WORKFLOW / "unrelated.py"
    unrelated.write_text(GUARD)
    assert _agac(project, "run", "-a", WORKFLOW, "--fresh").returncode == 0
    unrelated.write_text(GUARD.replace("return True", "return False"))

    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert "was edited since" not in result.printed


def test_an_edit_to_a_guard_udfs_code_is_named(project):
    (project / "tools" / WORKFLOW / "gate.py").write_text(GUARD)
    _edit(project, SUMMARY_INTENT, f'{SUMMARY_INTENT}    guard: "udf:summary_gate"\n')
    assert _agac(project, "run", "-a", WORKFLOW, "--fresh").returncode == 0
    (project / "tools" / WORKFLOW / "gate.py").write_text(GUARD.replace("True", "1 == 1"))

    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert "summary was edited since it completed (tool/guard code)" in result.printed


def test_an_action_stopped_partway_names_a_code_edit(project):
    (project / FAULT).write_text(json.dumps({"item": "beta"}))
    assert _agac(project, "run", "-a", WORKFLOW, "--fresh").returncode != 0
    _ran(project)

    (project / FAULT).unlink()
    _edit_tools(project, RECAP_RETURNS, 'return {"saw": item + ":edited"}')
    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert "recap was edited since its last run started (tool/guard code)" in result.printed
    assert _recap_saw(project) == ["alpha:-", "beta:edited", "gamma:edited"]


def test_a_store_stamped_before_code_digests_names_no_edit(completed):
    path = _workflow(completed) / "agent_io" / ".agent_status.json"
    statuses = json.loads(path.read_text())
    for details in statuses.values():
        details.pop("udf_source_hash", None)
        (details.get("answered_under") or {}).pop("udf_source_hash", None)
    path.write_text(json.dumps(statuses))
    _edit_tools(completed, RECAP_RETURNS, 'return {"saw": item + ":edited"}')

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert "was edited since" not in result.printed
