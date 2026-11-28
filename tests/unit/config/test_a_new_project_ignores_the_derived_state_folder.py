"""`agac init` puts `.agac/`, which holds derived state such as the knowledge indexes, in the
project's `.gitignore`: it writes the file, or adds the line to an existing one."""

from __future__ import annotations

import logging

import pytest

from agent_actions.config.init import ProjectInitializer


def _ignored(project):
    return (project / ".gitignore").read_text(encoding="utf-8")


def test_a_new_project_ignores_agac(tmp_path):
    ProjectInitializer("demo", base_path=tmp_path).init_project()

    assert ".agac/" in _ignored(tmp_path / "demo").splitlines()


@pytest.mark.parametrize("existing", ["mine\n", "mine"])
def test_an_existing_gitignore_keeps_its_lines_and_gains_agac(tmp_path, existing):
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / ".gitignore").write_text(existing, encoding="utf-8")

    ProjectInitializer("demo", base_path=tmp_path).init_project()

    assert _ignored(tmp_path / "demo") == "mine\n.agac/\n"


@pytest.mark.parametrize("line", [".agac/", ".agac", "/.agac/"])
def test_a_gitignore_that_already_ignores_agac_is_left_as_it_is(tmp_path, line):
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / ".gitignore").write_text(f"mine\n{line}\n", encoding="utf-8")

    ProjectInitializer("demo", base_path=tmp_path).init_project()

    assert _ignored(tmp_path / "demo") == f"mine\n{line}\n"


def test_a_project_from_an_example_ignores_agac(tmp_path, monkeypatch):
    from agent_actions.cli import init as init_module

    def fetch(name, dest, *, force=False):
        dest.mkdir(parents=True)
        (dest / "agent_actions.yml").write_text("project_name: x\n", encoding="utf-8")

    monkeypatch.setattr(init_module, "_fetch_example", fetch)

    init_module._install_example(
        "reviewer", "demo", str(tmp_path), False, log=logging.getLogger("t")
    )

    assert ".agac/" in _ignored(tmp_path / "demo").splitlines()
