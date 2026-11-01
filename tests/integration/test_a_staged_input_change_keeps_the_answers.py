"""A change to staged input answers only the records it changed (1603).

Any change to a staged file used to reset the first action and every action reading it, and
answer every record again, as ``--fresh`` would. Now, as for a config edit (#1629), the
answers held for records the change left alone stand: a record added or changed is
answered, and a record removed leaves nothing behind. Each run is its own ``agac`` process.
"""

import json

from tests.integration.test_a_config_edit_keeps_the_answers import (
    FAULT,
    SCOPE,
    WIDER_SCOPE,
    WORKFLOW,
    _agac,
    _backend,
    _config,
    _edit,
    _ran,
    _reader_echoed,
    _recap_saw,
    _statuses,
    _workflow,
    completed,  # noqa: F401
    project,  # noqa: F401
)


def _stage(root, items):
    path = _workflow(root) / "agent_io" / "staging" / "items.json"
    path.write_text(json.dumps(items))


def test_only_added_and_changed_records_are_answered(completed):  # noqa: F811
    _stage(
        completed,
        [
            {"item_id": "alpha", "text": "first item"},
            {"item_id": "gamma", "text": "third item, reworded"},
            {"item_id": "delta", "text": "fourth item"},
        ],
    )

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    answered = ["delta", "gamma"]
    assert _ran(completed) == {"recap": answered, "after_recap": answered, "bystander": answered}
    assert _recap_saw(completed) == ["alpha:-", "delta:-", "gamma:-"]
    assert _reader_echoed(completed) == ["alpha:-", "delta:-", "gamma:-"]


def test_a_record_removed_leaves_no_row_and_nothing_is_answered(completed):  # noqa: F811
    _stage(completed, [{"item_id": "alpha", "text": "first item"}])

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {}
    assert _recap_saw(completed) == ["alpha:-"]
    assert _reader_echoed(completed) == ["alpha:-"]


def test_rerun_still_answers_every_record_again(completed):  # noqa: F811
    _stage(
        completed,
        [{"item_id": "alpha", "text": "first item"}, {"item_id": "delta", "text": "fourth"}],
    )

    result = _agac(completed, "run", "-a", WORKFLOW, "--rerun", "stage_items")

    assert result.returncode == 0, result.printed
    answered = ["alpha", "delta"]
    assert _ran(completed) == {"recap": answered, "after_recap": answered, "bystander": answered}


def test_an_edit_beside_an_input_change_is_named_and_held_to_until_rerun(completed):  # noqa: F811
    _edit(completed, SCOPE, WIDER_SCOPE)
    _stage(completed, [*_staged(completed), {"item_id": "delta", "text": "fourth item"}])

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {"recap": ["delta"], "after_recap": ["delta"], "bystander": ["delta"]}
    assert _recap_saw(completed) == ["alpha:-", "beta:-", "delta:fourth item", "gamma:-"]
    assert "recap was edited since it completed (context scope)" in result.printed

    result = _agac(completed, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _ran(completed) == {}
    assert "recap was edited since it completed (context scope)" in result.printed


def _staged(root):
    return json.loads((_workflow(root) / "agent_io" / "staging" / "items.json").read_text())


# A first action that fails the items named in fault.json, and one action reading it.
SMALL_CONFIG = """name: map_reduce_fanin_check
description: "a removed record leaves nothing behind"
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
  - name: st
    kind: tool
    impl: faulty_stage
    intent: "Stage, failing the items named in fault.json"
    schema: { item_id: string }
    context_scope:
      observe: [source.item_id]
{limit}
  - name: rd
    kind: tool
    impl: echo_stage
    dependencies: [st]
    intent: "Read the staged item"
    schema: { seen: string }
    context_scope:
      observe: [st.item_id]
"""

SMALL_TOOLS = f"""import json
from pathlib import Path
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def faulty_stage(data: dict[str, Any]) -> dict[str, Any]:
    item = (data.get("source") or {{}}).get("item_id", "?")
    fault = Path({FAULT!r})
    if fault.exists() and item in json.loads(fault.read_text()):
        raise ValueError("refused " + item)
    return {{"item_id": item}}


@udf_tool()
def echo_stage(data: dict[str, Any]) -> dict[str, Any]:
    return {{"seen": (data.get("st") or {{}}).get("item_id", "?")}}
"""


def _small(root, files, *, limit="", fault=()):
    """The small workflow, staged with *files* ({name: [item ids]}) and run once."""
    _config(root).write_text(SMALL_CONFIG.replace("{limit}\n", limit))
    (root / "tools" / WORKFLOW / "logged.py").write_text(SMALL_TOOLS)
    staging = _workflow(root) / "agent_io" / "staging"
    for stale in staging.glob("*.json"):
        stale.unlink()
    _stage_ids(root, files)
    (root / FAULT).write_text(json.dumps(list(fault)))
    _agac(root, "run", "-a", WORKFLOW, "--fresh")
    return root


def _stage_ids(root, files):
    staging = _workflow(root) / "agent_io" / "staging"
    for name, ids in files.items():
        path = staging / f"{name}.json"
        if ids is None:
            path.unlink()
        else:
            path.write_text(json.dumps([{"item_id": item} for item in ids]))


def _held(root, action):
    """{item id: disposition} the action holds, by the item each record came from."""
    backend = _backend(root)
    try:
        items = {
            row["source_guid"]: row["content"]["source"]["item_id"]
            for path in backend.list_source_files()
            for row in backend.read_source(path)
        }
        return {
            items.get(row["record_id"], row["record_id"]): row["disposition"]
            for row in backend.get_disposition(action, snapshots=False)
        }
    finally:
        backend.close()


def test_a_failed_record_removed_from_staging_leaves_nothing_to_retry(project):  # noqa: F811
    _small(project, {"items": ["p1", "p2", "p3"]}, fault=["p1"])
    assert _held(project, "st") == {"p1": "failed", "p2": "success", "p3": "success"}
    assert _statuses(project)["st"]["status"] == "completed_with_failures"

    _stage_ids(project, {"items": ["p2", "p3"]})
    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _held(project, "st") == {"p2": "success", "p3": "success"}
    assert set(_held(project, "rd")) == {"p2", "p3"}
    assert _statuses(project)["st"]["status"] == "completed"
    retry = _agac(project, "retry", "-a", WORKFLOW, "--dry-run")
    assert "Records to retry" not in retry.printed, retry.printed


def test_a_staged_file_removed_leaves_none_of_its_records(project):  # noqa: F811
    _small(project, {"items": ["p1", "p2"], "more": ["m1", "m2"]}, fault=["m1"])
    assert set(_held(project, "st")) == {"p1", "p2", "m1", "m2"}

    _stage_ids(project, {"more": None})
    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _held(project, "st") == {"p1": "success", "p2": "success"}
    assert set(_held(project, "rd")) == {"p1", "p2"}
    assert _statuses(project)["st"]["status"] == "completed"


def test_a_record_outside_the_record_limit_is_not_removed(project):  # noqa: F811
    _small(project, {"items": ["p1", "p2", "p3"]}, limit="    record_limit: 2\n")
    assert _held(project, "st") == {"p1": "success", "p2": "success"}

    _stage_ids(project, {"items": ["p0", "p1", "p2", "p3"]})
    result = _agac(project, "run", "-a", WORKFLOW)

    assert result.returncode == 0, result.printed
    assert _held(project, "st") == {"p0": "success", "p1": "success", "p2": "success"}
