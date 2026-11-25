"""`agac run --rerun ACTION --where/--records` answers the matching records again, and no other.

A finished workflow needed one group of its records answered again from one
action. `--rerun` took every record, and `retry` took only failed ones, so the
group was wired by hand in the project. The ticket_triage_warehouse example,
offline: classify (LLM) -> route (tool) -> digest (File tool).
"""

import json
import shutil
from pathlib import Path

import pytest

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "ticket_triage_warehouse"
WORKFLOW = "ticket_triage_warehouse"
CONFIG = Path("agent_workflow") / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
TOOLS = Path("tools") / WORKFLOW / "triage_tools.py"
FIRST_TWO = "source.ticket_id <= 2"


def _agac(project: Path, *args: str, ends_with: int = 0) -> str:
    result = run_agac(project, *args, "-a", WORKFLOW)
    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == ends_with, output[-3000:]
    return output


def _answers(project: Path, action: str) -> dict[int | str, str]:
    """The answer each record holds at *action*, by the ticket (or the row) it is for."""
    backend = get_storage_backend(
        workflow_path=str(project / "agent_workflow" / WORKFLOW), workflow_name=WORKFLOW
    )
    backend.initialize()
    try:
        rows = [
            row
            for relative_path in backend.list_target_files(action)
            for row in backend.read_target(action, relative_path)
        ]
    finally:
        backend.close()
    return {_named(row): row["target_id"] for row in rows}


def _named(row: dict) -> int | str:
    content = row["content"]
    if "slots" in content:
        return f"{content['slots']['ticket']}:{content['slots']['role']}"
    return content["source"]["ticket_id"]


def _changed(before: dict, after: dict) -> set:
    assert before.keys() == after.keys()
    return {name for name in before if before[name] != after[name]}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = tmp_path / WORKFLOW
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns("warehouse.db", "agent_io"))
    config = (project / CONFIG).read_text(encoding="utf-8")
    (project / CONFIG).write_text(config.split("\noutputs:")[0] + "\n", encoding="utf-8")
    (project / "agent_workflow" / WORKFLOW / "agent_io").mkdir()
    import runpy

    runpy.run_path(str(project / "seed_warehouse.py"))["seed"](project / "warehouse.db")
    _agac(project, "run")
    return project


def test_only_the_matching_records_are_answered_again_from_the_action(project):
    before = {action: _answers(project, action) for action in ("classify", "route")}

    output = _agac(project, "run", "--rerun", "classify", "--where", FIRST_TWO)

    assert "2 of 5 record(s) of 'classify' match; the other 3 keep their answers" in output
    assert "✓ classify 2 records" in output and "✓ route 2 records" in output, output
    for action in ("classify", "route"):
        assert _changed(before[action], _answers(project, action)) == {1, 2}


def test_a_rerun_from_a_later_action_leaves_the_actions_above_it_alone(project):
    before = {action: _answers(project, action) for action in ("classify", "route")}

    _agac(project, "run", "--rerun", "route", "--where", FIRST_TWO)

    assert _changed(before["classify"], _answers(project, "classify")) == set()
    assert _changed(before["route"], _answers(project, "route")) == {1, 2}


def test_listed_ids_choose_the_records(project, tmp_path):
    backend_rows = _answers(project, "classify")
    listed = tmp_path / "ids.txt"
    dry = _agac(
        project, "run", "--rerun", "classify", "--where", "source.ticket_id == 4", "--dry-run"
    )
    chosen = [word for word in dry.split() if word.count("-") == 4 and len(word) == 36]
    assert len(chosen) == 1, dry
    listed.write_text(chosen[0] + "\n")

    _agac(project, "run", "--rerun", "classify", "--records", str(listed))

    assert _changed(backend_rows, _answers(project, "classify")) == {4}


def test_a_dry_run_prints_the_count_and_the_ids_and_changes_nothing(project):
    before = _answers(project, "classify")

    output = _agac(project, "run", "--rerun", "classify", "--where", FIRST_TWO, "--dry-run")

    assert "2 of 5 record(s) of 'classify' match" in output
    assert "Dry run" in output
    assert _answers(project, "classify") == before


def test_no_match_says_so_and_changes_nothing(project):
    before = _answers(project, "classify")

    output = _agac(project, "run", "--rerun", "classify", "--where", "source.ticket_id > 99")

    assert "No record matches. Nothing is changed." in output
    assert _answers(project, "classify") == before


def test_an_id_that_names_no_record_stops_the_rerun_before_it_changes_anything(project, tmp_path):
    before = _answers(project, "classify")
    listed = tmp_path / "ids.txt"
    listed.write_text("not-a-record\n")

    output = _agac(project, "run", "--rerun", "classify", "--records", str(listed), ends_with=1)

    assert "name no record that 'classify' stored" in output
    assert _answers(project, "classify") == before


@pytest.mark.parametrize(
    ("flags", "said"),
    [
        (["--where", FIRST_TWO], "give exactly one --rerun ACTION"),
        (["--rerun", "classify", "--rerun", "route", "--where", FIRST_TWO], "exactly one --rerun"),
        (["--rerun", "classify", "--where", FIRST_TWO, "--fresh"], "--fresh does not go with"),
        (["--rerun", "classify", "--where", "source.ticket_id <="], "not a guard expression"),
        (["--rerun", "classify", "--dry-run"], "--dry-run shows what --where or --records"),
    ],
)
def test_a_filter_that_cannot_be_applied_is_a_usage_error(project, flags, said):
    assert said in _agac(project, "run", *flags, ends_with=2)


def test_a_later_plain_run_answers_nothing_again(project):
    _agac(project, "run", "--rerun", "classify", "--where", FIRST_TWO)
    before = {action: _answers(project, action) for action in ("classify", "route")}

    _agac(project, "run")

    assert {action: _answers(project, action) for action in before} == before


SLOTS = '''

_ROLES = ["core", "edge_case"]


@udf_tool(granularity=Granularity.FILE)
def make_slots(data: list[dict[str, Any]]) -> FileUDFResult:
    """Two slots a ticket, each a record of its own."""
    return FileUDFResult(
        outputs=[
            {"source_index": [index], "data": {"role": role, "ticket": item["ticket_id"]}}
            for index, item in enumerate(data)
            for role in _ROLES
        ]
    )
'''
SLOT_ACTIONS = """
  - name: slots
    kind: tool
    impl: make_slots
    granularity: File
    intent: "Turn each ticket into two slots"
    dependencies: [classify]
    schema: slots
    context_scope:
      observe: [classify.category, source.ticket_id]

  - name: write
    intent: "Write for the slot"
    prompt: $ticket_triage_warehouse.Classify
    dependencies: [slots]
    schema: classify
    context_scope:
      observe: [slots.role, source.subject, source.body]
"""


def test_records_an_action_made_from_others_are_answered_again_below_it(tmp_path):
    """The filter names rows a File tool made, whose ids no input of the tool carries."""
    project = tmp_path / WORKFLOW
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns("warehouse.db", "agent_io"))
    config = (project / CONFIG).read_text(encoding="utf-8")
    (project / CONFIG).write_text(
        config.split("  - name: route")[0].rstrip() + "\n" + SLOT_ACTIONS, encoding="utf-8"
    )
    tools = project / TOOLS
    tools.write_text(tools.read_text(encoding="utf-8") + SLOTS, encoding="utf-8")
    (project / "schema" / WORKFLOW / "slots.yml").write_text(
        "name: slots\nfields:\n"
        "  - {id: role, type: string, required: true}\n"
        "  - {id: ticket, type: integer, required: true}\n",
        encoding="utf-8",
    )
    (project / "agent_workflow" / WORKFLOW / "agent_io").mkdir()
    import runpy

    runpy.run_path(str(project / "seed_warehouse.py"))["seed"](project / "warehouse.db")
    _agac(project, "run")
    before = {action: _answers(project, action) for action in ("slots", "write")}
    assert len(before["write"]) == 10

    output = _agac(project, "run", "--rerun", "slots", "--where", 'slots.role == "edge_case"')

    assert "5 of 10 record(s) of 'slots' match" in output
    assert "✓ write 5 records" in output, output
    assert _changed(before["slots"], _answers(project, "slots")) == set()
    assert _changed(before["write"], _answers(project, "write")) == {
        f"{ticket}:edge_case" for ticket in range(1, 6)
    }
    assert json.dumps(sorted(before["write"])) == json.dumps(sorted(_answers(project, "write")))
