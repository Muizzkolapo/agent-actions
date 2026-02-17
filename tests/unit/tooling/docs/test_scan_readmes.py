"""Tests for ProjectScanner.scan_readmes()."""

import pytest
from pathlib import Path

from agent_actions.tooling.docs.scanner import ProjectScanner


@pytest.fixture
def project_tree(tmp_path: Path) -> Path:
    """Create a minimal project tree with workflows and READMEs."""
    # Workflow with a README
    wf_dir = tmp_path / "agent_workflow" / "my_workflow"
    config_dir = wf_dir / "agent_config"
    config_dir.mkdir(parents=True)
    (config_dir / "my_workflow.yml").write_text("name: my_workflow")
    (wf_dir / "README.md").write_text("# My Workflow\nDoes things.")

    # Workflow without a README
    wf2_dir = tmp_path / "agent_workflow" / "no_readme"
    config2_dir = wf2_dir / "agent_config"
    config2_dir.mkdir(parents=True)
    (config2_dir / "no_readme.yml").write_text("name: no_readme")

    return tmp_path


def test_scan_readmes_finds_readme(project_tree: Path):
    scanner = ProjectScanner(str(project_tree))
    readmes = scanner.scan_readmes()

    assert "my_workflow" in readmes
    assert readmes["my_workflow"] == "# My Workflow\nDoes things."


def test_scan_readmes_skips_workflow_without_readme(project_tree: Path):
    scanner = ProjectScanner(str(project_tree))
    readmes = scanner.scan_readmes()

    assert "no_readme" not in readmes


def test_scan_readmes_skips_artefact_directory(project_tree: Path):
    # Create an agent_config inside artefact/ — should be ignored
    artefact_config = project_tree / "artefact" / "agent_config"
    artefact_config.mkdir(parents=True)
    (artefact_config / "hidden.yml").write_text("name: hidden")
    (artefact_config.parent / "README.md").write_text("Should not appear")

    scanner = ProjectScanner(str(project_tree))
    readmes = scanner.scan_readmes()

    assert "hidden" not in readmes


def test_scan_readmes_last_write_wins(tmp_path: Path):
    """Duplicate stems use last-write-wins, matching scan() collision policy."""
    dir_a = tmp_path / "a" / "agent_config"
    dir_a.mkdir(parents=True)
    (dir_a / "dup.yml").write_text("name: dup")
    (dir_a.parent / "README.md").write_text("README A")

    dir_b = tmp_path / "b" / "agent_config"
    dir_b.mkdir(parents=True)
    (dir_b / "dup.yml").write_text("name: dup")
    (dir_b.parent / "README.md").write_text("README B")

    scanner = ProjectScanner(str(tmp_path))
    readmes = scanner.scan_readmes()

    assert "dup" in readmes
    # Last-write-wins: rglob order is non-deterministic, but exactly one wins
    assert readmes["dup"] in ("README A", "README B")


def test_scan_readmes_multiple_yml_in_same_config(tmp_path: Path):
    """Multiple .yml files in one agent_config each get the same README."""
    wf_dir = tmp_path / "multi" / "agent_config"
    wf_dir.mkdir(parents=True)
    (wf_dir / "alpha.yml").write_text("name: alpha")
    (wf_dir / "beta.yml").write_text("name: beta")
    (wf_dir.parent / "README.md").write_text("# Multi")

    scanner = ProjectScanner(str(tmp_path))
    readmes = scanner.scan_readmes()

    assert readmes.get("alpha") == "# Multi"
    assert readmes.get("beta") == "# Multi"


def test_scan_readmes_empty_project(tmp_path: Path):
    scanner = ProjectScanner(str(tmp_path))
    readmes = scanner.scan_readmes()

    assert readmes == {}


def test_scan_readmes_truncates_large_readme(tmp_path: Path):
    """READMEs exceeding 100 KB are truncated with a notice."""
    wf_dir = tmp_path / "big" / "agent_config"
    wf_dir.mkdir(parents=True)
    (wf_dir / "big.yml").write_text("name: big")

    # Write a README larger than 100 KB
    large_content = "x" * (200 * 1024)
    (wf_dir.parent / "README.md").write_text(large_content)

    scanner = ProjectScanner(str(tmp_path))
    readmes = scanner.scan_readmes()

    assert "big" in readmes
    assert len(readmes["big"].encode("utf-8")) < len(large_content.encode("utf-8"))
    assert readmes["big"].endswith("*README truncated (exceeds 100 KB)*\n")
