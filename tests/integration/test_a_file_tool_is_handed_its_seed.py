"""A FILE tool run by `agac run` is handed the seed its action declares, and no stored
row carries it.

Driven through the CLI because the two halves of the contract live in different places:
the seed must be in the tool's input, and must be absent from every row the action
stores, including the tombstone of a record whose upstream failed.
"""

import json

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_retry_ignores_record_cap import (
    RECORDS,
    WORKFLOW,
    _backend,
    project,  # noqa: F401
)

FAIL_ONE_TOOL = '''from typing import Any

from agent_actions import udf_tool


@udf_tool
def fail_one(data: Any, *args) -> list[dict]:
    """Raise on one record, so the FILE action below meets an upstream failure."""
    page = ((data or {}).get("source") or {}).get("page_content") or ""
    if page == "page 2":
        raise RuntimeError("page 2 cannot be prepared")
    return [{"summary": page, "exam_density": "low"}]
'''

REPORT_TOOL = '''from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import FileUDFResult, Granularity


@udf_tool(granularity=Granularity.FILE)
def report_keys(data: Any, *args) -> Any:
    """Report what each item was handed: its keys, and the seed's value."""
    return FileUDFResult(
        [
            {
                "source_index": i,
                "data": {
                    "summary": ",".join(sorted(item)),
                    "exam_density": str((item.get("rules") or {}).get("threshold")),
                },
            }
            for i, item in enumerate(data or [])
        ]
    )
'''

SEEDED_ACTIONS = """  - name: prepare
    kind: tool
    dependencies: [flatten]
    intent: "Pass each record on, failing one"
    schema: tool_action_output
    impl: fail_one
    context_scope: { observe: [source.page_content, flatten.summary] }
    expect: { repair: none }
  - name: seeded
    kind: tool
    granularity: File
    dependencies: [prepare]
    intent: "Report the keys a FILE tool is handed beside a declared seed"
    schema: tool_action_output
    impl: report_keys
    context_scope:
      observe: [prepare.summary, seed.rules]
      seed:
        rules: $file:rules.json
    expect: { repair: none }
"""


@pytest.fixture
def seeded(project):  # noqa: F811
    workflow = project / "agent_workflow" / WORKFLOW
    config = workflow / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SEEDED_ACTIONS)
    (workflow / "seed_data").mkdir(exist_ok=True)
    (workflow / "seed_data" / "rules.json").write_text(json.dumps({"threshold": 7}))
    (project / "tools" / WORKFLOW / "seeded_prepare.py").write_text(FAIL_ONE_TOOL)
    (project / "tools" / WORKFLOW / "seeded_report.py").write_text(REPORT_TOOL)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])
    assert result.exit_code == 0, result.output
    return project


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


def test_the_tool_is_handed_the_seed_under_its_bare_key(seeded):
    rows = _rows(seeded, "seeded")
    handed = [r["content"]["seeded"] for r in rows if r["content"].get("seeded")]

    assert len(handed) == RECORDS - 1
    assert {h["summary"] for h in handed} == {"rules,summary"}
    assert {h["exam_density"] for h in handed} == {"7"}


def test_no_stored_row_of_the_action_carries_the_seed(seeded):
    rows = _rows(seeded, "seeded")

    assert len(rows) == RECORDS
    assert [r for r in rows if "seed" in r["content"]] == []
    # The record whose upstream failed is stored too, as a row the action did not answer.
    unanswered = [r for r in rows if not r["content"].get("seeded")]
    assert len(unanswered) == 1
    assert "seed" not in unanswered[0]["content"]
