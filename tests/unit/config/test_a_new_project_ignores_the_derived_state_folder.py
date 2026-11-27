"""`agac init` writes a `.gitignore` with `.agac/`, which holds derived state such as the
knowledge indexes; an existing `.gitignore` is left as it is."""

from __future__ import annotations

from agent_actions.config.init import ProjectInitializer


def test_a_new_project_ignores_agac(tmp_path):
    ProjectInitializer("demo", base_path=tmp_path).init_project()

    assert ".agac/" in (tmp_path / "demo" / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_an_existing_gitignore_is_kept(tmp_path):
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / ".gitignore").write_text("mine\n", encoding="utf-8")

    ProjectInitializer("demo", base_path=tmp_path).init_project()

    assert (tmp_path / "demo" / ".gitignore").read_text(encoding="utf-8") == "mine\n"
