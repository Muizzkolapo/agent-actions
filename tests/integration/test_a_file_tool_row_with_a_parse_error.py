"""One row of a FILE tool's output holds `_parse_error`; the others still land (#1269).

Driven through `agac run`, because the loss was in collection: every record of
the file was dispositioned failed and nothing was stored.
"""

from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_a_file_tool_that_invents_rows import _raw
from tests.integration.test_retry_ignores_record_cap import (
    RECORDS,
    WORKFLOW,
    _backend,
    project,  # noqa: F401
)

SHAPE_TOOL = '''from typing import Any

from agent_actions import udf_tool
from agent_actions.utils.udf_management.registry import FileUDFResult, Granularity


@udf_tool(granularity=Granularity.FILE)
def shape_pages(data: Any, *args) -> Any:
    """The first row carries a parse error; every other row is a valid answer."""
    outputs = []
    for i, _ in enumerate(data or []):
        row = {"summary": f"s{i}", "exam_density": "low"}
        if i == 0:
            row["_parse_error"] = "Expecting value: line 1 column 1"
        outputs.append({"source_index": i, "data": row})
    return FileUDFResult(outputs)
'''

SHAPE_ACTION = """  - name: shape
    kind: tool
    granularity: File
    dependencies: [flatten]
    intent: "Shape the file, one row per page"
    schema: tool_action_output
    impl: shape_pages
    context_scope: { observe: [flatten.summary] }
    expect: { repair: none }
"""


def test_only_the_row_with_the_parse_error_fails(project):  # noqa: F811
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(config.read_text().rstrip("\n") + "\n" + SHAPE_ACTION)
    (project / "tools" / WORKFLOW / "shape.py").write_text(SHAPE_TOOL)

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

    assert result.exit_code == 0, result.output
    backend = _backend(project)
    try:
        rows = backend.get_disposition("shape")
    finally:
        backend.close()
    outcomes = sorted((r["disposition"], r.get("reason")) for r in rows)
    assert outcomes == sorted([("failed", "parse_error")] + [("success", None)] * (RECORDS - 1))
    answered = sorted(
        r["content"]["shape"]["summary"]
        for r in _raw(project, "shape")
        if r.get("_state") == "processed"
    )
    assert answered == sorted(f"s{i}" for i in range(1, RECORDS))
