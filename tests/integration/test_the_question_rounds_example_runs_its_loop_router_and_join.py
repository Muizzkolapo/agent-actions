"""The question_rounds example runs offline: a loop of three rounds, a router and a join.

`photosynthesis` passes its check in round 1, `plate tectonics` in round 2 and `the water
cycle` never, so each round takes fewer records, the router sends two to `publish` and one
to `flag_for_review`, and the join holds all three.
"""

import shutil
from pathlib import Path

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "question_rounds"
WORKFLOW = "question_rounds"


def _agac(project: Path, *args: str) -> str:
    result = run_agac(project, *args, "-a", WORKFLOW)
    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == 0, output[-3000:]
    return output


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    project = tmp_path_factory.mktemp("rounds") / WORKFLOW
    shutil.copytree(EXAMPLE, project)
    return project


@pytest.fixture(scope="module")
def run(project) -> str:
    return _agac(project, "run", "--fresh")


def _rows(project: Path, action: str) -> list[dict]:
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=project
    )
    backend = get_storage_backend(workflow_path=str(paths.io_dir.parent), workflow_name=WORKFLOW)
    backend.initialize()
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
    finally:
        backend.close()


def test_inspect_shows_the_loop_the_router_and_the_join(project):
    output = _agac(project, "inspect")

    assert "round loop ×3 max, until check.passed == true" in output, output
    assert "verdict route on round.outcome: passed → publish · default → flag_for_review" in output
    assert "bank join of publish, flag_for_review" in output
    assert "round_iter" not in output.split("Pre-flight")[0]


def test_each_round_takes_only_the_records_that_failed_the_one_before(project, run):
    counts = [len(_rows(project, f"round_iter{k}__check")) for k in (1, 2, 3)]

    assert counts == [3, 2, 1], run
    assert "12 completed" in run, run


def test_the_join_holds_each_topic_once_published_or_flagged(project, run):
    bank = {
        row["content"]["spec"]["topic"]: row["content"]["bank"] for row in _rows(project, "bank")
    }

    assert bank == {
        "photosynthesis": {"status": "published", "summary": "photosynthesis: passed in round 1"},
        "plate tectonics": {
            "status": "published",
            "summary": "plate tectonics: passed in round 2",
        },
        "the water cycle": {
            "status": "needs review",
            "summary": "the water cycle: round 3: the question does not test the water cycle",
        },
    }, run
