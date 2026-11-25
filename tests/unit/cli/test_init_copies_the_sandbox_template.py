"""`agac init <name> --template sandbox` copies a small project that the sandbox can test.

The template ships inside the `agent_actions` package, which is what the wheel holds, so
an installed `agac` has it too.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import pathspec
import pytest
import yaml
from click.testing import CliRunner

import agent_actions
from agent_actions.cli.init import BUNDLED_TEMPLATES, PROJECT_TEMPLATES_DIR, init

TEMPLATE = PROJECT_TEMPLATES_DIR / "sandbox"
REPO = Path(agent_actions.__file__).resolve().parents[1]


def _init(tmp_path: Path, *args: str):
    return CliRunner().invoke(init, ["new", *args, "-o", str(tmp_path)], catch_exceptions=False)


def test_the_template_is_in_the_package_the_wheel_ships():
    assert TEMPLATE.is_dir()
    assert TEMPLATE.resolve().is_relative_to(Path(agent_actions.__file__).parent.resolve())
    assert BUNDLED_TEMPLATES == ("sandbox",)


def test_init_copies_every_file_of_the_template(tmp_path):
    result = _init(tmp_path, "my_sandbox", "--template", "sandbox")

    assert result.exit_code == 0, result.output
    project = tmp_path / "my_sandbox"
    shipped = sorted(
        p.relative_to(TEMPLATE)
        for p in TEMPLATE.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )
    copied = {p.relative_to(project) for p in project.rglob("*") if p.is_file()}
    assert set(shipped) <= copied
    assert Path("sandbox.yml") in copied
    assert Path("sandbox_expected.yml") in copied
    assert "agac sandbox check -w support_desk" in result.output


def test_init_writes_the_project_name_into_the_project_config(tmp_path):
    _init(tmp_path, "my_sandbox", "--template", "sandbox")

    config = yaml.safe_load((tmp_path / "my_sandbox" / "agent_actions.yml").read_text())
    assert config["project_name"] == "my_sandbox"
    assert config["schema_path"] == "schema"


def test_init_keeps_the_standard_folders(tmp_path):
    _init(tmp_path, "my_sandbox", "--template", "sandbox")

    for folder in ("agent_workflow", "prompt_store", "schema", "tools", "seed_data"):
        assert (tmp_path / "my_sandbox" / folder).is_dir()


@pytest.mark.parametrize("template", ["default", "minimal"])
def test_the_other_templates_copy_no_project(tmp_path, template):
    _init(tmp_path, "plain", "--template", template)

    assert not (tmp_path / "plain" / "sandbox.yml").exists()


def test_an_unknown_template_is_refused(tmp_path):
    result = CliRunner().invoke(init, ["new", "x", "-t", "sandboxx", "-o", str(tmp_path)])

    assert result.exit_code != 0
    assert not (tmp_path / "x").exists()


# Output a run of the template left in the package folder: never copied, never shipped.
RUN_OUTPUT = [
    "agent_workflow/support_desk/agent_io/target/classify/out.json",
    "agent_workflow/support_desk/agent_io/store/support_desk.sandbox.db",
    "agent_workflow/support_desk/agent_io/sandbox/.agent_status.json",
    "agent_workflow/support_desk/agent_io/.agent_status.json",
    "agent_workflow/support_desk/agent_io/logs/events.json",
    "agent_workflow/support_desk/agent_io/sandbox/artefact/runs.json",
    "artefact/runs.json",
    ".agac/batch_state/b.json",
    "stray.db",
]


def test_init_copies_no_run_output_the_template_folder_holds(tmp_path, monkeypatch):
    templates = tmp_path / "templates"
    shutil.copytree(TEMPLATE, templates / "sandbox")
    for path in RUN_OUTPUT:
        (templates / "sandbox" / path).parent.mkdir(parents=True, exist_ok=True)
        (templates / "sandbox" / path).write_text("{}")
    monkeypatch.setattr("agent_actions.cli.init.PROJECT_TEMPLATES_DIR", templates)

    result = _init(tmp_path, "my_sandbox", "--template", "sandbox")

    assert result.exit_code == 0, result.output
    project = tmp_path / "my_sandbox"
    assert [path for path in RUN_OUTPUT if (project / path).exists()] == []
    assert (project / "agent_workflow/support_desk/agent_io/staging/tickets.json").is_file()


def test_the_wheel_and_the_sdist_leave_out_run_output_in_the_template_folder():
    build = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"]["hatch"]["build"]
    template = TEMPLATE.relative_to(REPO).as_posix()
    shipped = [f"{template}/{p.relative_to(TEMPLATE).as_posix()}" for p in _template_files()]

    for target in ("wheel", "sdist"):
        excluded = pathspec.GitIgnoreSpec.from_lines(build["targets"][target]["exclude"])
        assert [p for p in RUN_OUTPUT if not excluded.match_file(f"{template}/{p}")] == [], target
        assert [p for p in shipped if excluded.match_file(p)] == [], target


def _template_files() -> list[Path]:
    return [p for p in TEMPLATE.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
