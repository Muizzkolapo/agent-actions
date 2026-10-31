"""A tool action routes to the tool vendor."""

from agent_actions.output.response.expander_action_types import process_tool_action


class TestToolActionRouting:
    def test_a_tool_action_routes_to_the_tool_vendor(self):
        agent: dict = {}
        action = {"name": "my_tool", "kind": "tool", "impl": "mod.func", "schema": {"f": "str"}}

        process_tool_action(agent, action)

        assert agent["model_vendor"] == "tool"
        assert agent["model_name"] == "mod.func"
