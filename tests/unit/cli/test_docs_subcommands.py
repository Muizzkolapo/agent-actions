"""Regression tests for VIOL-0037 + VIOL-0095: `agac docs` build/serve split."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from agent_actions.cli import docs as docs_mod
from agent_actions.cli.docs import docs as docs_group


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def fake_project(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    with patch(
        "agent_actions.cli.cli_decorators.ensure_in_project",
        return_value=project_root,
    ):
        yield project_root


def test_build_exits_zero_without_serving(runner, fake_project, tmp_path):
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
    output_dir = tmp_path / "out"
    with (
        patch.object(docs_mod, "_build_catalog", return_value=output_dir) as mocked_build,
        patch.object(docs_mod, "_serve_catalog") as mocked_serve,
    ):
        result = runner.invoke(docs_group, ["serve", "-o", str(output_dir), "-p", "0"])

    assert result.exit_code == 0, (result.stdout, result.stderr)
    mocked_build.assert_called_once()
    mocked_serve.assert_called_once()
    assert mocked_serve.call_args.kwargs["port"] == 0


def test_bare_docs_warns_on_stderr_and_delegates_to_serve(runner, fake_project, tmp_path):
    output_dir = tmp_path / "out"
    with (
        patch.object(docs_mod, "_build_catalog", return_value=output_dir) as mocked_build,
        patch.object(docs_mod, "_serve_catalog") as mocked_serve,
    ):
        result = runner.invoke(docs_group, ["-o", str(output_dir), "-p", "0"])

    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert "deprecated" in result.stderr.lower()
    assert "deprecated" not in result.stdout.lower()
    assert "agac docs serve" in result.stderr
    mocked_build.assert_called_once()
    mocked_serve.assert_called_once()


def test_bare_docs_forwards_group_options_to_serve(runner, fake_project, tmp_path):
    output_dir = tmp_path / "custom"
    with (
        patch.object(docs_mod, "_build_catalog", return_value=output_dir) as mocked_build,
        patch.object(docs_mod, "_serve_catalog") as mocked_serve,
    ):
        result = runner.invoke(docs_group, ["-o", str(output_dir), "-p", "9999"])

    assert result.exit_code == 0, (result.stdout, result.stderr)
    assert mocked_build.call_args.args[0] == str(output_dir)
    assert mocked_serve.call_args.kwargs["port"] == 9999


def test_build_help_mentions_exit_or_ci(runner):
    result = runner.invoke(docs_group, ["build", "--help"])
    assert result.exit_code == 0
    text = result.output.lower()
    assert "exit" in text or "ci" in text


def test_serve_help_signals_blocking_and_default_port(runner):
    result = runner.invoke(docs_group, ["serve", "--help"])
    assert result.exit_code == 0
    assert "block" in result.output.lower()
    assert "8000" in result.output


def test_group_help_lists_both_subcommands(runner):
    result = runner.invoke(docs_group, ["--help"])
    assert result.exit_code == 0
    text = result.output.lower()
    assert "build" in text and "serve" in text


def test_build_aborts_on_no_workflows(runner, fake_project, tmp_path):
    with patch.object(docs_mod, "generate_docs", return_value=False):
        result = runner.invoke(docs_group, ["build", "-o", str(tmp_path / "out")])

    assert result.exit_code != 0
    assert "no workflows" in result.stderr.lower()


def test_group_options_before_subcommand_are_rejected(runner, fake_project, tmp_path):
    output_dir = tmp_path / "custom"
    with (
        patch.object(docs_mod, "_build_catalog", return_value=output_dir) as mocked_build,
        patch.object(docs_mod, "_serve_catalog") as mocked_serve,
    ):
        result = runner.invoke(docs_group, ["-o", str(output_dir), "build"])

    assert result.exit_code != 0, (result.stdout, result.stderr)
    assert "must follow the subcommand" in result.stderr.lower()
    mocked_build.assert_not_called()
    mocked_serve.assert_not_called()


def test_group_port_before_subcommand_is_rejected(runner, fake_project, tmp_path):
    with (
        patch.object(docs_mod, "_build_catalog", return_value=tmp_path) as mocked_build,
        patch.object(docs_mod, "_serve_catalog") as mocked_serve,
    ):
        result = runner.invoke(docs_group, ["-p", "9999", "serve"])

    assert result.exit_code != 0, (result.stdout, result.stderr)
    assert "must follow the subcommand" in result.stderr.lower()
    mocked_build.assert_not_called()
    mocked_serve.assert_not_called()
