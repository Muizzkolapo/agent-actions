"""Regression tests for VIOL-0037 + VIOL-0095: `agac docs` build/serve split.

These tests pin the user-facing surface of the new Click group:

* ``build`` must exit 0 without binding a port (CI-friendly).
* ``serve`` must call into the underlying HTTP server (blocking in real use,
  patched here so the test does not hang).
* The bare ``agac docs`` alias must emit a deprecation notice on stderr
  and delegate to ``serve``.
* ``--help`` text must make the blocking/exit semantics discoverable.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from agent_actions.cli import docs as docs_mod
from agent_actions.cli.docs import docs as docs_group


@pytest.fixture
def runner():
    # Click 8.2+ splits stdout/stderr by default, so the deprecation test can
    # assert the notice lands on stderr specifically without extra config.
    return CliRunner()


@pytest.fixture
def fake_project(tmp_path: Path):
    """Patch project-root discovery so subcommands do not need a real project."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    with patch(
        "agent_actions.cli.cli_decorators.ensure_in_project",
        return_value=project_root,
    ):
        yield project_root


def test_build_exits_zero_without_serving(runner, fake_project, tmp_path):
    """`agac docs build` runs the build helper and exits — never invokes serve."""
    output_dir = tmp_path / "out"
    with (
        patch.object(docs_mod, "_build_catalog", return_value=output_dir) as mocked_build,
        patch.object(docs_mod, "_serve_catalog") as mocked_serve,
    ):
        result = runner.invoke(docs_group, ["build", "-o", str(output_dir)])

    assert result.exit_code == 0, (result.stdout, result.stderr)
    mocked_build.assert_called_once()
    mocked_serve.assert_not_called()


def test_serve_invokes_serve_catalog(runner, fake_project, tmp_path):
    """`agac docs serve` builds the catalog, then hands off to the server."""
    output_dir = tmp_path / "out"
    with (
        patch.object(docs_mod, "_build_catalog", return_value=output_dir) as mocked_build,
        patch.object(docs_mod, "_serve_catalog") as mocked_serve,
    ):
        result = runner.invoke(docs_group, ["serve", "-o", str(output_dir), "-p", "0"])

    assert result.exit_code == 0, (result.stdout, result.stderr)
    mocked_build.assert_called_once()
    mocked_serve.assert_called_once()
    # Port is forwarded explicitly so muscle-memory invocations still bind
    # the requested port.
    _, kwargs = mocked_serve.call_args
    assert kwargs.get("port") == 0


def test_bare_docs_warns_on_stderr_and_delegates_to_serve(runner, fake_project, tmp_path):
    """`agac docs` (no subcommand) prints deprecation on stderr and delegates."""
    output_dir = tmp_path / "out"
    with (
        patch.object(docs_mod, "_build_catalog", return_value=output_dir) as mocked_build,
        patch.object(docs_mod, "_serve_catalog") as mocked_serve,
    ):
        result = runner.invoke(docs_group, ["-o", str(output_dir), "-p", "0"])

    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert "deprecated" in result.stderr.lower(), (
        f"Deprecation notice missing from stderr; got: {result.stderr!r}"
    )
    assert "deprecated" not in result.stdout.lower(), (
        "Deprecation notice must NOT appear on stdout (CI consumers may pipe stdout)."
    )
    # Names the replacement so users know what to migrate to.
    assert "agac docs serve" in result.stderr
    mocked_build.assert_called_once()
    mocked_serve.assert_called_once()


def test_bare_docs_forwards_group_options_to_serve(runner, fake_project, tmp_path):
    """Group-level -o/-p flags survive the alias delegation to `serve`."""
    output_dir = tmp_path / "custom"
    with (
        patch.object(docs_mod, "_build_catalog", return_value=output_dir) as mocked_build,
        patch.object(docs_mod, "_serve_catalog") as mocked_serve,
    ):
        result = runner.invoke(docs_group, ["-o", str(output_dir), "-p", "9999"])

    assert result.exit_code == 0, (result.stdout, result.stderr)
    # _build_catalog(output, project_root=...) — first positional is the -o value.
    assert mocked_build.call_args.args[0] == str(output_dir)
    # _serve_catalog(output_dir, port=..., project_root=...) — port is a kwarg.
    assert mocked_serve.call_args.kwargs["port"] == 9999


def test_build_help_mentions_exit_or_ci(runner):
    """`agac docs build --help` must signal it does not block (CI-friendly)."""
    result = runner.invoke(docs_group, ["build", "--help"])
    assert result.exit_code == 0
    text = result.output.lower()
    assert "exit" in text or "ci" in text, (
        f"build --help must mention exit/CI semantics; got: {result.output!r}"
    )


def test_serve_help_signals_blocking_and_default_port(runner):
    """`agac docs serve --help` must surface blocking semantics + default port."""
    result = runner.invoke(docs_group, ["serve", "--help"])
    assert result.exit_code == 0
    text = result.output.lower()
    assert "block" in text, f"serve --help must mention blocking; got: {result.output!r}"
    # Default port (8000) must remain visible so muscle memory survives the split.
    assert "8000" in result.output, f"Default port (8000) missing from --help: {result.output!r}"


def test_group_help_lists_both_subcommands(runner):
    """`agac docs --help` advertises both build and serve."""
    result = runner.invoke(docs_group, ["--help"])
    assert result.exit_code == 0
    text = result.output.lower()
    assert "build" in text and "serve" in text


def test_build_aborts_on_no_workflows(runner, fake_project, tmp_path):
    """When the underlying generator finds nothing, build exits non-zero (Abort)."""
    # generate_docs is the underlying scanner; resolve_project_root with a
    # non-None Path is an idempotent pass-through, so _build_catalog reaches
    # the generate_docs mock without needing additional patches.
    with patch.object(docs_mod, "generate_docs", return_value=False):
        result = runner.invoke(docs_group, ["build", "-o", str(tmp_path / "out")])

    assert result.exit_code != 0
    # Message must land on stderr (CI stdout pipelines must not see error chatter).
    assert "no workflows" in result.stderr.lower(), (
        f"expected 'no workflows' on stderr; got stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_group_options_before_subcommand_are_rejected(runner, fake_project, tmp_path):
    """`agac docs -o X build` must error — Click would otherwise silently drop -o."""
    output_dir = tmp_path / "custom"
    with (
        patch.object(docs_mod, "_build_catalog", return_value=output_dir) as mocked_build,
        patch.object(docs_mod, "_serve_catalog") as mocked_serve,
    ):
        result = runner.invoke(docs_group, ["-o", str(output_dir), "build"])

    assert result.exit_code != 0, (result.stdout, result.stderr)
    assert "must follow the subcommand" in result.stderr.lower()
    # Neither helper should have been reached — the error is raised in the group.
    mocked_build.assert_not_called()
    mocked_serve.assert_not_called()


def test_group_port_before_subcommand_is_rejected(runner, fake_project, tmp_path):
    """Same as above for `-p`; pins the second option independently."""
    with (
        patch.object(docs_mod, "_build_catalog", return_value=tmp_path) as mocked_build,
        patch.object(docs_mod, "_serve_catalog") as mocked_serve,
    ):
        result = runner.invoke(docs_group, ["-p", "9999", "serve"])

    assert result.exit_code != 0, (result.stdout, result.stderr)
    assert "must follow the subcommand" in result.stderr.lower()
    mocked_build.assert_not_called()
    mocked_serve.assert_not_called()
