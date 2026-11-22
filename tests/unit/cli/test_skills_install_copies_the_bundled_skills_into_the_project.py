"""`agac skills install` copies the bundled skills into the project folder of the
chosen assistant, and `agac skills list` names them.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from agent_actions.cli import skills as skills_module
from agent_actions.cli.skills import get_bundled_skills_path, get_target_path, skills
from agent_actions.errors import ConfigurationError


@pytest.fixture
def project(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "agent_actions.yml").touch()
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "bundle"
    folder.mkdir()
    monkeypatch.setattr(skills_module, "get_bundled_skills_path", lambda: folder)
    return folder


def _invoke(*args: str):
    return CliRunner().invoke(skills, list(args))


def test_the_package_ships_at_least_one_skill_with_a_skill_file():
    bundled = [d for d in get_bundled_skills_path().iterdir() if d.is_dir()]

    assert bundled
    assert all((d / "SKILL.md").is_file() for d in bundled)


@pytest.mark.parametrize(("flag", "folder"), [("--claude", ".claude"), ("--codex", ".codex")])
def test_install_copies_every_bundled_skill_into_the_assistant_folder(project, flag, folder):
    result = _invoke("install", flag)

    target = project / folder / "skills"
    assert result.exit_code == 0, result.output
    for skill in get_bundled_skills_path().iterdir():
        if skill.is_dir():
            assert (target / skill.name / "SKILL.md").read_text() == (
                skill / "SKILL.md"
            ).read_text()
            assert f"  - {skill.name}\n" in result.output
    assert f"Skills installed to: {target}" in result.output


def test_install_without_an_assistant_flag_is_a_usage_error(project):
    result = _invoke("install")

    assert result.exit_code == 2
    assert "You must specify either --claude or --codex." in result.output
    assert not (project / ".claude").exists()


def test_install_outside_a_project_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = _invoke("install", "--claude")

    assert result.exit_code == 1
    assert "Not in an agent-actions project." in result.output
    assert not (tmp_path / ".claude").exists()


def test_a_skill_already_installed_is_kept_unless_forced(project, bundle):
    (bundle / "demo").mkdir()
    (bundle / "demo" / "SKILL.md").write_text("new")
    installed = project / ".claude" / "skills" / "demo"
    installed.mkdir(parents=True)
    (installed / "SKILL.md").write_text("edited by the user")

    kept = _invoke("install", "--claude")

    assert kept.exit_code == 0
    assert "Skipped (already exists):\n  - demo" in kept.output
    assert "Use --force to overwrite existing skills." in kept.output
    assert (installed / "SKILL.md").read_text() == "edited by the user"

    forced = _invoke("install", "--claude", "--force")

    assert forced.exit_code == 0
    assert "  - demo (overwritten)" in forced.output
    assert (installed / "SKILL.md").read_text() == "new"


def test_install_with_no_bundled_skills_fails(project, bundle):
    result = _invoke("install", "--codex")

    assert result.exit_code == 1
    assert "No bundled skills found." in result.output


def test_install_with_the_bundle_missing_reports_a_corrupted_installation(
    project, tmp_path, monkeypatch
):
    monkeypatch.setattr(skills_module, "get_bundled_skills_path", lambda: tmp_path / "gone")

    result = _invoke("install", "--codex")

    assert result.exit_code == 1
    assert "This may indicate a corrupted installation." in result.output


def test_an_unknown_tool_has_no_target_path(tmp_path):
    with pytest.raises(ConfigurationError, match="Unknown tool: cursor"):
        get_target_path("cursor", tmp_path)


def test_list_names_each_skill_with_the_first_line_of_its_description(bundle):
    (bundle / "alpha").mkdir()
    (bundle / "alpha" / "SKILL.md").write_text("# Alpha\n\nDoes alpha things.\n")
    (bundle / "beta").mkdir()
    (bundle / "beta" / "SKILL.md").write_text("# Beta\n" + "x" * 70 + "\n")
    (bundle / "gamma").mkdir()

    result = _invoke("list")

    assert result.exit_code == 0
    assert "  alpha\n    Does alpha things.\n" in result.output
    assert f"  beta\n    {'x' * 60}...\n" in result.output
    assert "  gamma\n\n" in result.output
    assert "agac skills install --claude" in result.output


def test_list_with_no_bundled_skills_says_so(bundle):
    result = _invoke("list")

    assert result.exit_code == 0
    assert result.output == "No bundled skills available.\n"


def test_list_shows_the_description_from_the_skill_front_matter(bundle):
    (bundle / "demo").mkdir()
    (bundle / "demo" / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Builds demos.\n---\n\n# Demo\n"
    )

    result = _invoke("list")

    assert "  demo\n    Builds demos.\n" in result.output
