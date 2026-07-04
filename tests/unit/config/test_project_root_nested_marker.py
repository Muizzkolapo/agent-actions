"""Regression tests for VIOL-0065: a nested ``agent_actions.yml`` must not
hijack ``find_project_root_dir``; the outermost marker wins.  Single-marker,
no-marker, and fallback-heuristic resolution stay byte-identical.
"""

from __future__ import annotations

from agent_actions.config.path_config import (
    find_project_root_dir,
    find_project_root_dir_with_shadow,
)


def _make_marker(directory, name="agent_actions.yml"):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text("name: x\n")
    return directory


# -- outermost preference (the fix) ------------------------------------------


def test_outermost_marker_wins_over_nested(tmp_path):
    outer = _make_marker(tmp_path / "proj")
    nested = _make_marker(outer / "examples" / "foo")

    assert find_project_root_dir(start=nested) == outer


def test_three_levels_returns_outermost(tmp_path):
    outer = _make_marker(tmp_path / "proj")
    mid = _make_marker(outer / "pkg")
    inner = _make_marker(mid / "examples")

    assert find_project_root_dir(start=inner) == outer


# -- byte-identical single / no-marker paths ---------------------------------


def test_single_marker_from_subdirectory(tmp_path):
    proj = _make_marker(tmp_path / "proj")
    sub = proj / "a" / "b"
    sub.mkdir(parents=True)

    assert find_project_root_dir(start=sub) == proj


def test_no_marker_returns_none(tmp_path):
    sub = tmp_path / "a"
    sub.mkdir()
    assert find_project_root_dir(start=sub) is None


def test_fallback_dir_still_resolves(tmp_path):
    (tmp_path / "agent_config").mkdir()
    assert find_project_root_dir(start=tmp_path) == tmp_path


# -- shadow-reporting variant ------------------------------------------------


def test_shadow_variant_reports_nested_and_chosen(tmp_path):
    outer = _make_marker(tmp_path / "proj")
    nested = _make_marker(outer / "examples" / "foo")

    chosen, shadowed = find_project_root_dir_with_shadow(start=nested)
    assert chosen == outer
    assert shadowed == [nested]


def test_shadow_variant_three_levels_reports_both_nested(tmp_path):
    outer = _make_marker(tmp_path / "proj")
    mid = _make_marker(outer / "pkg")
    inner = _make_marker(mid / "examples")

    chosen, shadowed = find_project_root_dir_with_shadow(start=inner)
    assert chosen == outer
    # Innermost first: both nested markers shadowed, outermost chosen.
    assert shadowed == [inner, mid]


def test_shadow_variant_single_marker_no_shadow(tmp_path):
    proj = _make_marker(tmp_path / "proj")
    sub = proj / "a"
    sub.mkdir()

    chosen, shadowed = find_project_root_dir_with_shadow(start=sub)
    assert chosen == proj
    assert shadowed == []


def test_shadow_variant_no_marker_none_no_shadow(tmp_path):
    sub = tmp_path / "a"
    sub.mkdir()

    chosen, shadowed = find_project_root_dir_with_shadow(start=sub)
    assert chosen is None
    assert shadowed == []


def test_shadow_variant_respects_custom_marker_file(tmp_path):
    outer = _make_marker(tmp_path / "proj", name="custom.yml")
    nested = _make_marker(outer / "examples", name="custom.yml")
    # A default-name marker between them must be ignored under a custom marker.
    _make_marker(nested / "mid")

    chosen, shadowed = find_project_root_dir_with_shadow(
        start=nested / "mid", marker_file="custom.yml"
    )
    assert chosen == outer
    assert shadowed == [nested]


def test_shadow_variant_fallback_disabled_returns_none(tmp_path):
    (tmp_path / "agent_config").mkdir()
    sub = tmp_path / "a"
    sub.mkdir()

    chosen, shadowed = find_project_root_dir_with_shadow(start=sub, use_fallback_heuristics=False)
    assert chosen is None
    assert shadowed == []


def test_fallback_dir_not_reported_as_shadowed_marker(tmp_path):
    """A nested fallback dir (agent_config/) below an outer *marker* must not
    hijack, and must not be reported as a shadowed marker — it is a heuristic,
    not a marker file."""
    outer = _make_marker(tmp_path / "proj")
    nested = outer / "sub"
    (nested / "agent_config").mkdir(parents=True)

    chosen, shadowed = find_project_root_dir_with_shadow(start=nested)
    assert chosen == outer
    assert shadowed == []


# -- warn-once at the CLI entrypoint -----------------------------------------


class _StubCLI:
    def execute(self, argv):
        return 0


def test_warn_helper_names_both_chosen_and_nested(tmp_path, capsys):
    from agent_actions.cli.main import _warn_shadowed_project_root

    chosen = tmp_path / "proj"
    nested = chosen / "examples" / "foo"
    _warn_shadowed_project_root(chosen, [nested])

    err = capsys.readouterr().err
    assert "Warning" in err
    assert str(chosen) in err
    assert str(nested) in err


def test_main_entrypoint_warns_once_on_shadow(tmp_path, monkeypatch, capsys):
    from agent_actions.cli import main as cli_main

    outer = _make_marker(tmp_path / "proj")
    nested = _make_marker(outer / "examples" / "foo")
    monkeypatch.chdir(nested)
    monkeypatch.setattr(cli_main, "CLI", _StubCLI)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)

    assert cli_main.main_entrypoint([]) == 0

    err = capsys.readouterr().err
    assert err.count("nested 'agent_actions.yml' shadowed") == 1
    assert str(outer) in err
    assert str(nested) in err


def test_main_entrypoint_silent_without_shadow(tmp_path, monkeypatch, capsys):
    from agent_actions.cli import main as cli_main

    proj = _make_marker(tmp_path / "proj")
    sub = proj / "a" / "b"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    monkeypatch.setattr(cli_main, "CLI", _StubCLI)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)

    assert cli_main.main_entrypoint([]) == 0
    assert "shadowed" not in capsys.readouterr().err
