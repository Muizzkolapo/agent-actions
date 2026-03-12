"""Tests for get_project_root() cache behaviour with explicit start_path."""

from agent_actions.config.paths import PathConfig, PathManager


def test_explicit_start_path_caches_for_follow_on_calls(tmp_path):
    """Priming with get_project_root(start_path=...) should store the root
    so that follow-on calls (e.g. get_standard_path) use it instead of
    re-resolving from CWD."""
    project = tmp_path / "my_project"
    project.mkdir()
    (project / "agent_actions.yml").write_text("name: test")

    pm = PathManager(config=PathConfig())

    # Prime the manager with an explicit start_path
    root = pm.get_project_root(start_path=project)
    assert root == project

    # Follow-on call without start_path should use the cached root
    assert pm._project_root == project


def test_explicit_start_path_re_resolves_different_project(tmp_path):
    """Successive calls with different start_paths should re-resolve,
    not return a stale cached root from the first call."""
    proj_a = tmp_path / "project_a"
    proj_a.mkdir()
    (proj_a / "agent_actions.yml").write_text("name: a")

    proj_b = tmp_path / "project_b"
    proj_b.mkdir()
    (proj_b / "agent_actions.yml").write_text("name: b")

    pm = PathManager(config=PathConfig())

    root_a = pm.get_project_root(start_path=proj_a)
    assert root_a == proj_a

    # Second call with different start_path must re-resolve, not return proj_a
    root_b = pm.get_project_root(start_path=proj_b)
    assert root_b == proj_b
