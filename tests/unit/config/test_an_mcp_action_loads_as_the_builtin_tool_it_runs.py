"""A `kind: mcp` action loads as a built-in RECORD tool action that calls the server.

Its server must be one agent_actions.yml declares; its arguments are field references
(observed for it) or constants; a key or setting it cannot honour is refused at load.
"""

import pytest

from agent_actions.config.mcp_actions import MCP_IMPL, expand_mcp_actions
from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.tools.builtin_spec import checked_builtin

PROJECT = "mcp_servers:\n  dbt:\n    command: uvx\n    args: [dbt-mcp]\n"


@pytest.fixture
def root(tmp_path):
    (tmp_path / "agent_actions.yml").write_text(PROJECT)
    return tmp_path


def _load(root, **action):
    data = {
        "actions": [
            {"name": "read", "kind": "tool", "impl": "read"},
            {"name": "lineage", "kind": "mcp", "server": "dbt", "tool": "get_lineage", **action},
        ]
    }
    return expand_mcp_actions(data, "w.yml", root)["actions"][1]


def test_the_action_becomes_a_record_tool_that_runs_the_builtin(root):
    action = _load(
        root,
        arguments={"model": "read.table", "depth": 2, "mode": {"value": "full"}},
        context_scope={"observe": ["read.owner"]},
    )

    assert (action["kind"], action["impl"], action["granularity"]) == ("tool", MCP_IMPL, "record")
    assert not {"server", "tool", "arguments"} & set(action)
    assert action["_builtin"] == {
        "tool": "mcp",
        "server": "dbt",
        "name": "get_lineage",
        "arguments": {"model": "read.table", "depth": {"value": 2}, "mode": {"value": "full"}},
    }
    assert action["context_scope"]["observe"] == ["read.owner", "read.table"]
    assert checked_builtin(action["_builtin"])["name"] == "get_lineage"


def test_a_string_that_names_no_action_is_a_constant(root):
    action = _load(root, arguments={"region": "eu.west", "table": "source.table"})

    assert action["_builtin"]["arguments"] == {
        "region": {"value": "eu.west"},
        "table": "source.table",
    }


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"server": "nope"}, "no MCP server named 'nope' in agent_actions.yml (declared: dbt)"),
        ({"server": None}, "needs 'server:'"),
        ({"tool": None}, "needs 'tool:'"),
        ({"impl": "x"}, "takes no 'impl'"),
        ({"prompt": "x"}, "takes no 'prompt'"),
        ({"granularity": "File"}, "granularity is Record"),
        ({"run_mode": "batch"}, "runs online"),
        ({"arguments": ["a"]}, "'arguments:' maps each argument"),
        ({"arguments": {"a": {"value": 1, "x": 2}}}, "field reference or {value: <constant>}"),
    ],
)
def test_what_an_mcp_action_cannot_honour_is_refused_at_load(root, change, said):
    with pytest.raises(ConfigurationError, match=said.replace("(", r"\(").replace(")", r"\)")):
        _load(root, **change)


def test_kind_mcp_in_defaults_is_refused(root):
    with pytest.raises(ConfigurationError, match="set it on each action"):
        expand_mcp_actions({"defaults": {"kind": "mcp"}, "actions": []}, "w.yml", root)


def test_a_workflow_with_no_mcp_action_loads_unchanged(root):
    data = {"actions": [{"name": "a", "kind": "tool", "impl": "a"}]}

    assert expand_mcp_actions(data, "w.yml", root) is data
