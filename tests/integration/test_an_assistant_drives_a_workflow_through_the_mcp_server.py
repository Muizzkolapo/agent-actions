"""`agac mcp` serves a project to an MCP client: a real process, asked over stdio.

An assistant lists the workflows, validates one, runs it in the sandbox, reads
what the run stored, answers some records again, and is refused a real run. The
sandbox template, so nothing calls a model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac, start_agac

WORKFLOW = "support_desk"
ENV = {"OPENAI_API_KEY": ""}


class Client:
    """One MCP session with an `agac mcp` process."""

    def __init__(self, project: Path, *flags: str, **extra_env: str) -> None:
        self.process = start_agac(
            project, "mcp", "--project", str(project), *flags, env={**ENV, **extra_env}
        )
        self.sent = 0

    def ask(self, method: str, params: dict | None = None) -> dict:
        self.sent += 1
        message = {"jsonrpc": "2.0", "id": self.sent, "method": method, "params": params or {}}
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        reply = json.loads(self.process.stdout.readline())
        assert reply["id"] == self.sent, reply
        return reply

    def call(self, tool: str, **arguments) -> tuple[bool, str]:
        result = self.ask("tools/call", {"name": tool, "arguments": arguments})["result"]
        return result["isError"], result["content"][0]["text"]

    def close(self) -> str:
        self.process.stdin.close()
        self.process.wait(timeout=30)
        return self.process.stderr.read()


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("mcp")
    created = run_agac(root, "init", "starter", "--template", "sandbox", env=ENV)
    assert created.returncode == 0, created.stdout + created.stderr
    return root / "starter"


@pytest.fixture(scope="module")
def session(project: Path):
    """A session that has run the workflow once in the sandbox."""
    client = Client(project)
    hello = client.ask("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    assert hello["result"]["serverInfo"]["name"] == "agent-actions"
    is_error, text = client.call("run_workflow", workflow=WORKFLOW, fresh=True)
    assert not is_error, text[-3000:]
    yield client
    client.close()


def test_the_server_offers_its_tools_and_says_how_to_work(session):
    hello = session.ask("initialize", {"protocolVersion": "2025-06-18"})["result"]
    tools = {tool["name"] for tool in session.ask("tools/list")["result"]["tools"]}

    assert hello["capabilities"] == {"tools": {}, "resources": {}}
    assert "Run in the sandbox first" in hello["instructions"]
    assert {"list_workflows", "run_workflow", "retry_workflow", "sandbox_check"} <= tools
    assert {"workflow_status", "dispositions", "records", "traces", "usage"} <= tools


def test_the_workflows_are_listed_and_one_is_validated(session):
    is_error, listed = session.call("list_workflows")
    assert not is_error
    assert json.loads(listed) == [
        {"workflow": WORKFLOW, "config": f"agent_workflow/{WORKFLOW}/agent_config/{WORKFLOW}.yml"}
    ]

    is_error, inspected = session.call("inspect_workflow", workflow=WORKFLOW)
    assert not is_error, inspected
    assert "validated" in inspected and "classify" in inspected


def test_the_sandbox_run_is_read_back_as_json(session):
    is_error, status = session.call("workflow_status", workflow=WORKFLOW)
    assert not is_error, status
    held = json.loads(status.split("\n\n", 1)[1])
    assert held["run_status"] == "SUCCESS"

    is_error, categories = session.call(
        "records", workflow=WORKFLOW, action="classify", field="content.classify.category"
    )
    assert not is_error, categories
    assert len(json.loads(categories.split("\n\n", 1)[1])) == 4


def test_records_are_cut_to_the_limit_asked_for(session):
    is_error, text = session.call("records", workflow=WORKFLOW, action="classify", limit=1)

    assert not is_error, text
    assert "4 records in all; the first 1 are shown" in text


def test_some_records_are_answered_again_through_the_server(session):
    is_error, counted = session.call(
        "run_workflow",
        workflow=WORKFLOW,
        rerun=["tag_reply"],
        where='source.priority == "high"',
        dry_run=True,
    )
    assert not is_error, counted
    assert "2 of 4 record(s) of 'tag_reply' match" in counted

    is_error, ran = session.call(
        "run_workflow", workflow=WORKFLOW, rerun=["tag_reply"], where='source.priority == "high"'
    )
    assert not is_error, ran[-3000:]
    # A batch action: the rerun pauses, and the wait collects its two records.
    assert "✓ tag_reply 2 records" in " ".join(ran.split()), ran[-3000:]


def test_a_real_run_is_refused_and_writes_nothing_real(session, project):
    is_error, text = session.call("run_workflow", workflow=WORKFLOW, sandbox=False)

    assert is_error
    assert "agac mcp --allow-real-runs" in text
    io_dir = project / "agent_workflow" / WORKFLOW / "agent_io"
    assert not (io_dir / "store" / f"{WORKFLOW}.db").exists()
    assert not (io_dir / ".agent_status.json").exists()


def test_a_wrong_argument_is_an_answer_the_assistant_can_read(session):
    is_error, text = session.call("run_workflow", workflow=WORKFLOW, speed="fast")

    assert is_error
    assert "takes no argument named speed" in text


def test_the_project_s_files_and_the_skill_guides_are_resources(session):
    listed = session.ask("resources/list")["result"]["resources"]
    uris = {resource["uri"] for resource in listed}

    config = f"agac://project/agent_workflow/{WORKFLOW}/agent_config/{WORKFLOW}.yml"
    assert config in uris
    assert "agac://skills/agac-agent-skills/SKILL.md" in uris
    assert not any(".env" in uri or "agent_io" in uri for uri in uris)

    read = session.ask("resources/read", {"uri": config})["result"]["contents"][0]
    assert read["text"].startswith("# support_desk")

    outside = session.ask("resources/read", {"uri": "agac://project/../../etc/passwd"})
    assert outside["error"]["message"].startswith("Unknown resource")


def test_the_check_of_the_template_passes_through_the_server(project):
    client = Client(project)
    try:
        is_error, text = client.call("sandbox_check", workflow=WORKFLOW)
    finally:
        client.close()

    assert not is_error, text[-3000:]
    assert "exit code 0 (each expected value holds)" in text
    assert "PASS: all" in text


def test_standard_output_carries_only_the_protocol(project):
    client = Client(project)
    client.ask("initialize")
    client.process.stdin.write('{"jsonrpc": "2.0", "method": "notifications/initialized"}\n')
    client.ask("ping")
    said = client.close()

    assert "agac mcp: serving" in said and "sandbox runs only" in said
    assert client.process.stdout.read() == ""


def test_outside_a_project_the_command_says_so(tmp_path):
    result = run_agac(tmp_path, "mcp", env=ENV)

    assert result.returncode != 0
    assert "No Agent Actions project" in result.stdout + result.stderr


def test_the_protocol_is_utf_8_whatever_the_locale_of_the_server(project):
    client = Client(project, PYTHONIOENCODING="ascii", PYTHONUTF8="0")
    try:
        client.ask("initialize", {"protocolVersion": "2025-06-18"})
        failed, said = client.call("run_workflow", workflow=WORKFLOW)
        assert not failed, said[-3000:]
        is_error, text = client.call(
            "run_workflow",
            workflow=WORKFLOW,
            rerun=["classify"],
            where='source.priority == "hïgh"',
            dry_run=True,
        )
    finally:
        client.close()

    assert not is_error, text
    assert "hïgh" in text
