"""A fan-in pairs each split record with its own input when an expansion sits above both branches.

A split record keeps the earliest expanded identity as its parent, which no branch
holds; only the input it consumed names the record the other branch answered for.
"""

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_a_fan_in_over_a_splitting_branch import (
    PAGES,
    WORKFLOW,
    _action,
    _summaries,
    project,  # noqa: F401
)

TOOLS = """from typing import Any

from agent_actions import udf_tool


@udf_tool
def below_expand(data: Any, *args) -> list[dict]:
    page = data["source"]["page_content"]
    return [{"summary": f"{page}{part}", "exam_density": "low"} for part in ("x", "y")]


@udf_tool
def below_left(data: Any, *args) -> list[dict]:
    return [{"summary": f"L-{data['expand']['summary']}", "exam_density": "low"}]


@udf_tool
def below_right(data: Any, *args) -> list[dict]:
    part = data["expand"]["summary"]
    return [{"summary": f"R-{part}-{i}", "exam_density": "low"} for i in (1, 2)]


@udf_tool
def below_join(data: Any, *args) -> list[dict]:
    return [{"summary": f"{data['left']['summary']}|{data['right']['summary']}", "exam_density": "low"}]
"""


@pytest.mark.parametrize("run_mode", ["online", "batch"])
@pytest.mark.parametrize("order", [["left", "right"], ["right", "left"]], ids=["lr", "rl"])
def test_each_split_record_is_paired_with_the_record_it_was_split_from(project, run_mode, order):  # noqa: F811
    (project / "tools" / WORKFLOW / "fan_in_below_an_expansion.py").write_text(TOOLS)
    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    head = (
        config.read_text().split("actions:")[0].replace("run_mode: online", f"run_mode: {run_mode}")
    )
    config.write_text(
        head
        + "actions:\n"
        + _action("expand", "below_expand", [], ["source.page_content"])
        + _action("left", "below_left", ["expand"], ["expand.summary"])
        + _action("right", "below_right", ["expand"], ["expand.summary"])
        + _action("join", "below_join", order, ["left.summary", "right.summary"])
    )

    result = CliRunner().invoke(cli, ["run", "-a", WORKFLOW, "--fresh"])

    assert result.exit_code == 0, result.output
    assert _summaries(project, "join") == sorted(
        f"L-{p}{part}|R-{p}{part}-{i}" for p in PAGES for part in "xy" for i in (1, 2)
    )
