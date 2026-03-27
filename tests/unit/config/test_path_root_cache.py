"""Tests for get_project_root() cache behaviour."""

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
    assert pm.get_project_root() == project


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


def test_cwd_change_invalidates_cached_root(tmp_path, monkeypatch):
    """After CWD changes, get_project_root() must re-resolve instead of
    returning the stale cached root from the old CWD."""
    proj_a = tmp_path / "project_a"
    proj_a.mkdir()
    (proj_a / "agent_actions.yml").write_text("name: a")

    proj_b = tmp_path / "project_b"
    proj_b.mkdir()
    (proj_b / "agent_actions.yml").write_text("name: b")

    pm = PathManager(config=PathConfig())

    # Resolve from project_a via CWD
    monkeypatch.chdir(proj_a)
    root_a = pm.get_project_root()
    assert root_a == proj_a

    # Change CWD to project_b — cached root must be invalidated
    monkeypatch.chdir(proj_b)
    root_b = pm.get_project_root()
    assert root_b == proj_b, f"Expected {proj_b} after CWD change, got stale {root_b}"


def test_cwd_unchanged_returns_cached_root(tmp_path, monkeypatch):
    """When CWD hasn't changed, cached root should be returned (no re-resolve)."""
    project = tmp_path / "my_project"
    project.mkdir()
    marker = project / "agent_actions.yml"
    marker.write_text("name: test")

    pm = PathManager(config=PathConfig())
    monkeypatch.chdir(project)

    root1 = pm.get_project_root()
    assert root1 == project

    # Second call should return the same result from cache.
    # Verify caching by confirming that even if the marker file is removed,
    # the cached result is still returned (proving no re-resolution occurred).
    marker.unlink()
    root2 = pm.get_project_root()
    assert root2 == project


def test_explicit_prime_survives_cwd_change(tmp_path, monkeypatch):
    """Root set via explicit start_path should NOT be invalidated by CWD changes."""
    project = tmp_path / "my_project"
    project.mkdir()
    (project / "agent_actions.yml").write_text("name: test")

    other = tmp_path / "other"
    other.mkdir()
    (other / "agent_actions.yml").write_text("name: other")

    pm = PathManager(config=PathConfig())

    # Prime with explicit start_path (not CWD-derived)
    root = pm.get_project_root(start_path=project)
    assert root == project

    # CWD change to a competing valid project should NOT invalidate the pinned root
    monkeypatch.chdir(other)
    root_after = pm.get_project_root()
    assert root_after == project


def test_init_project_root_survives_cwd_change(tmp_path, monkeypatch):
    """Root provided via __init__ should NOT be invalidated by CWD changes."""
    project = tmp_path / "my_project"
    project.mkdir()
    (project / "agent_actions.yml").write_text("name: test")

    other = tmp_path / "other"
    other.mkdir()
    (other / "agent_actions.yml").write_text("name: other")

    pm = PathManager(config=PathConfig(), project_root=project)

    monkeypatch.chdir(other)
    root = pm.get_project_root()
    assert root == project


def test_cwd_change_also_clears_path_cache(tmp_path, monkeypatch):
    """When CWD changes invalidate root, derived path caches must also clear."""
    proj_a = tmp_path / "project_a"
    proj_a.mkdir()
    (proj_a / "agent_actions.yml").write_text("name: a")
    (proj_a / "schema").mkdir()

    proj_b = tmp_path / "project_b"
    proj_b.mkdir()
    (proj_b / "agent_actions.yml").write_text("name: b")
    (proj_b / "schema").mkdir()

    from agent_actions.config.paths import PathType

    pm = PathManager(config=PathConfig())

    monkeypatch.chdir(proj_a)
    path_a = pm.get_standard_path(PathType.SCHEMA)
    assert proj_a in path_a.parents or path_a == proj_a / "schema"

    monkeypatch.chdir(proj_b)
    path_b = pm.get_standard_path(PathType.SCHEMA)
    assert proj_b in path_b.parents or path_b == proj_b / "schema"
    assert path_a != path_b


def test_cwd_subdir_change_within_same_project_resolves_same_root(tmp_path, monkeypatch):
    """Moving CWD between subdirs of the same project resolves the same root."""
    project = tmp_path / "my_project"
    project.mkdir()
    (project / "agent_actions.yml").write_text("name: test")

    subdir_a = project / "subdir_a"
    subdir_a.mkdir()
    subdir_b = project / "subdir_b"
    subdir_b.mkdir()

    pm = PathManager(config=PathConfig())

    monkeypatch.chdir(subdir_a)
    root_a = pm.get_project_root()
    assert root_a == project

    # Move CWD to a different subdir of the same project — root should still be the same
    monkeypatch.chdir(subdir_b)
    root_b = pm.get_project_root()
    assert root_b == project


def test_clear_cache_forces_re_resolution(tmp_path, monkeypatch):
    """clear_cache() empties all cache fields; next call re-resolves."""
    proj_a = tmp_path / "project_a"
    proj_a.mkdir()
    (proj_a / "agent_actions.yml").write_text("name: a")

    proj_b = tmp_path / "project_b"
    proj_b.mkdir()
    (proj_b / "agent_actions.yml").write_text("name: b")

    pm = PathManager(config=PathConfig())

    # Pin to proj_a via explicit start_path — this survives CWD changes
    root = pm.get_project_root(start_path=proj_a)
    assert root == proj_a

    # Without clear_cache, the pin holds even after CWD change
    monkeypatch.chdir(proj_b)
    assert pm.get_project_root() == proj_a  # still pinned

    # clear_cache forgets the pin — now CWD-based resolution finds proj_b
    pm.clear_cache()
    root_b = pm.get_project_root()
    assert root_b == proj_b
