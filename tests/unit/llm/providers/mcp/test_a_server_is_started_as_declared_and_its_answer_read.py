"""How a declared MCP server is started, and how a tool's answer becomes records."""

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.mcp.client import arguments_for, server_settings
from agent_actions.llm.providers.mcp.session import result_records


def _declare(tmp_path, block: str):
    (tmp_path / "agent_actions.yml").write_text("mcp_servers:\n" + block)
    return tmp_path


def test_a_variable_is_read_from_the_environment_never_the_project(tmp_path, monkeypatch):
    monkeypatch.setenv("DBT_TOKEN", "secret")
    root = _declare(
        tmp_path,
        "  dbt:\n    command: uvx\n    args: [dbt-mcp, '--token=${DBT_TOKEN}']\n"
        "    env: {DBT_PROFILE: '${DBT_TOKEN}-x'}\n    cwd: dbt\n",
    )

    settings = server_settings("dbt", root)

    assert settings["args"] == ["dbt-mcp", "--token=secret"]
    assert settings["env"] == {"DBT_PROFILE": "secret-x"}
    assert settings["cwd"] == root / "dbt"


@pytest.mark.parametrize(
    ("block", "said"),
    [
        ("  other:\n    command: x\n", "No MCP server named 'dbt' in agent_actions.yml"),
        ("  dbt:\n    args: [x]\n", "needs 'command'"),
        ("  dbt:\n    command: x\n    url: http://y\n", "takes no url"),
        ("  dbt:\n    command: x\n    args: '${MISSING_VAR}'\n", "'args' is a list"),
        ("  dbt:\n    command: '${MISSING_VAR}'\n", "reads ${MISSING_VAR}, which is not set"),
    ],
)
def test_a_server_that_cannot_start_as_declared_is_refused(tmp_path, monkeypatch, block, said):
    monkeypatch.delenv("MISSING_VAR", raising=False)
    root = _declare(tmp_path, block)

    with pytest.raises(ConfigurationError, match=said.replace("$", r"\$").replace("{", r"\{")):
        server_settings("dbt", root)


def test_each_argument_is_read_from_the_record_or_taken_as_given():
    spec = {"arguments": {"table": "read.table", "depth": {"value": 2}}}

    assert arguments_for(spec, {"read": {"table": "orders"}}) == {"table": "orders", "depth": 2}
    with pytest.raises(KeyError, match="observe it on the action"):
        arguments_for(spec, {"read": {}})


@pytest.mark.parametrize(
    ("result", "records"),
    [
        ({"structuredContent": {"a": 1}, "content": []}, [{"a": 1}]),
        ({"content": [{"type": "text", "text": '{"a": 1}'}]}, [{"a": 1}]),
        ({"content": [{"type": "text", "text": "[1, 2]"}]}, [{"result": 1}, {"result": 2}]),
        ({"content": [{"type": "text", "text": "plain words"}]}, [{"result": "plain words"}]),
        ({"content": [{"type": "image", "data": "x"}]}, []),
    ],
)
def test_an_answer_becomes_records(result, records):
    assert result_records(result) == records


def test_a_server_that_does_not_start_is_not_started_again_for_each_record(tmp_path):
    import sys
    import time

    from agent_actions.llm.providers.mcp.session import McpError, SessionPool

    pool = SessionPool()
    settings = {"command": sys.executable, "args": ["-c", "import sys; sys.exit(3)"]}

    try:
        with pytest.raises(McpError, match="did not answer initialize: it stopped"):
            pool.get("dead", settings, tmp_path)
        began = time.monotonic()
        with pytest.raises(McpError, match="did not answer initialize"):
            pool.get("dead", settings, tmp_path)
        assert time.monotonic() - began < 0.5
    finally:
        pool.close_all()


def test_a_command_that_does_not_exist_is_named(tmp_path):
    from agent_actions.llm.providers.mcp.session import McpError, SessionPool

    pool = SessionPool()
    try:
        with pytest.raises(McpError, match="did not start"):
            pool.get("gone", {"command": str(tmp_path / "no-such-program")}, tmp_path)
    finally:
        pool.close_all()
