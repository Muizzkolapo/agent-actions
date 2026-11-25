"""`agac init <name> --template sandbox` copies a small project that the sandbox can test.

The template ships inside the `agent_actions` package, which is what the wheel holds, so
an installed `agac` has it too.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

import agent_actions
from agent_actions.cli.init import BUNDLED_TEMPLATES, PROJECT_TEMPLATES_DIR, init

TEMPLATE = PROJECT_TEMPLATES_DIR / "sandbox"


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
