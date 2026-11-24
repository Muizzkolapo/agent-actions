"""`--sandbox` holds sandbox mode for its own command, and the mode ends with it.

The mode is one flag for the process. A command that ends with the flag still set
would send the next command of the same process, an embedding script or a test, to
the sandbox output.
"""

from __future__ import annotations

import json

import click
import pytest
from click.testing import CliRunner

from agent_actions.cli.cli_decorators import sandbox_option
from agent_actions.cli.records import records
from agent_actions.config import sandbox
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

WORKFLOW = "wf"


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
    config_dir = tmp_path / "agent_workflow" / WORKFLOW / "agent_config"
    config_dir.mkdir(parents=True)
    (config_dir / f"{WORKFLOW}.yml").write_text(f"name: {WORKFLOW}\nactions: []\n")
    monkeypatch.chdir(tmp_path)
    return tmp_path / "agent_workflow" / WORKFLOW / "agent_io"


def _store(io_dir, text: str) -> None:
    db_path = sandbox.store_file(io_dir, WORKFLOW)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    backend = SQLiteBackend(str(db_path), WORKFLOW)
    backend.initialize()
    try:
        backend._write_target_raw("extract", "data.json", [{"source_guid": "g1", "text": text}])
    finally:
        backend.close()


def _texts(result) -> list[str]:
    return [record["text"] for record in json.loads(result.stdout)]


def test_a_sandbox_command_that_succeeds_leaves_the_mode_off(project):
    _store(project, "real")
    with sandbox.sandbox_mode(True):
        _store(project, "sandbox")
    runner = CliRunner()

    shown = runner.invoke(records, ["-w", WORKFLOW, "-A", "extract", "--sandbox"])
    assert shown.exit_code == 0, shown.output
    assert _texts(shown) == ["sandbox"]
    assert sandbox.is_active() is False

    plain = runner.invoke(records, ["-w", WORKFLOW, "-A", "extract"])
    assert plain.exit_code == 0, plain.output
    assert _texts(plain) == ["real"]


def test_a_sandbox_command_that_fails_leaves_the_mode_off(project):
    _store(project, "real")
    runner = CliRunner()

    refused = runner.invoke(records, ["-w", WORKFLOW, "-A", "extract", "--sandbox"])
    assert refused.exit_code != 0
    assert f"{WORKFLOW}.sandbox.db" in refused.output
    assert sandbox.is_active() is False

    plain = runner.invoke(records, ["-w", WORKFLOW, "-A", "extract"])
    assert plain.exit_code == 0, plain.output
    assert _texts(plain) == ["real"]


def test_a_sandbox_command_that_raises_leaves_the_mode_off():
    seen = []

    @click.command()
    @sandbox_option()
    def crash():
        seen.append(sandbox.is_active())
        raise RuntimeError("boom")

    result = CliRunner().invoke(crash, ["--sandbox"])

    assert isinstance(result.exception, RuntimeError)
    assert seen == [True]
    assert sandbox.is_active() is False
