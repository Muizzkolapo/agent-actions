"""A version merge holds every version after the project moves (1605).

Correlation ids were minted from the workflow's absolute config path, so a version
answered again from another checkout, worktree or mount took other ids than the
versions it kept, and the merge split each record into halves short of a version.
"""

import shutil
from pathlib import Path

import pytest

from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = "map_reduce_fanin_check"
ENV = {"OPENAI_API_KEY": "sk-not-used", "GEMINI_API_KEY": "not-used"}


@pytest.fixture(autouse=True)
def _no_record_limit(monkeypatch):
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)


def _merged(root: Path) -> list[dict]:
    backend = get_storage_backend(
        workflow_path=str(root / "agent_workflow" / WORKFLOW), workflow_name=WORKFLOW
    )
    backend.initialize()
    try:
        return [
            row["content"]["merge_direct"]
            for path in backend.list_target_files("merge_direct")
            for row in backend.read_target("merge_direct", path)
        ]
    finally:
        backend.close()


def test_a_version_answered_again_after_a_move_merges_with_the_rest(tmp_path):
    first = tmp_path / "first"
    shutil.copytree(
        REPO / "examples" / WORKFLOW, first, ignore=shutil.ignore_patterns("logs", "store")
    )
    result = run_agac(first, "run", "-a", WORKFLOW, "--fresh", env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr
    before = _merged(first)
    assert before and {row["n_votes"] for row in before} == {2}

    moved = first.rename(tmp_path / "moved")
    result = run_agac(moved, "run", "-a", WORKFLOW, "--rerun", "vote_direct_2", env=ENV)
    assert result.returncode == 0, result.stdout + result.stderr

    after = _merged(moved)
    assert len(after) == len(before)
    assert {row["n_votes"] for row in after} == {2}
    assert "carry different correlation ids" not in result.stdout + result.stderr
