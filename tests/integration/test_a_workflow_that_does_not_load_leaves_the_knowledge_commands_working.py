"""A workflow that does not load does not stop `agac knowledge list` or `build`.

`list` and `build` read the workflows only to find the index kinds their retrieve entries
search. A workflow that does not load is named, and the other bases are still listed and
built. `build --prune` keeps every index file then, since the kinds that workflow reads are
not known.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests._support.agac_cli import run_agac

BROKEN = {
    "actions_not_a_list": "name: broken\nactions: 5\n",
    "top_level_list": "- name: broken\n",
}


@pytest.fixture(params=sorted(BROKEN))
def project(request, tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "knowledge" / "help").mkdir(parents=True)
    (root / "knowledge" / "help" / "billing.md").write_text(
        "# Billing\n\nWe refund a duplicate charge.\n", encoding="utf-8"
    )
    config = {
        "project_name": "proj",
        "knowledge": {"help_center": {"sources": ["knowledge/help/*.md"]}},
    }
    (root / "agent_actions.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    workflow = root / "agent_workflow" / "broken" / "agent_config"
    workflow.mkdir(parents=True)
    (workflow / "broken.yml").write_text(BROKEN[request.param], encoding="utf-8")
    return root


def _index_files(project: Path) -> list[str]:
    folder = project / ".agac" / "knowledge" / "help_center"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def test_list_names_the_workflow_and_still_lists_the_base(project):
    result = run_agac(project, "knowledge", "list")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "help_center: 1 source(s), index: keyword" in result.stdout
    assert "broken" in result.stdout + result.stderr


def test_build_still_builds_the_base(project):
    result = run_agac(project, "knowledge", "build")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "help_center keyword:" in result.stdout
    assert any(name.startswith("keyword-") for name in _index_files(project))


def test_prune_keeps_every_index_file_and_says_why(project):
    old = project / ".agac" / "knowledge" / "help_center" / "key-0000000000000000.db"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"")

    result = run_agac(project, "knowledge", "build", "--prune")

    assert old.exists()
    assert "broken" in result.stdout + result.stderr
    assert "Removed" not in result.stdout
