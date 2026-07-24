"""Namespaced passthrough fields must land at content level, not inside the action output.

context_scope.passthrough produces {namespace: {field: value}} dicts. The output
record must carry each namespace as a sibling of the action's own namespace so
downstream observe refs like ``ns.field`` resolve against ``content[ns]``.
"""

from agent_actions.prompt.context.scope_application import apply_context_scope
from agent_actions.utils.transformation.passthrough import PassthroughTransformer


def _config(passthrough_refs):
    return {"context_scope": {"passthrough": passthrough_refs}}


class TestNamespacedPassthroughPlacement:
    def test_unstructured_output_places_namespace_at_content_level(self):
        transformer = PassthroughTransformer()
        llm_output = [{"batch_name": "batch_A"}]
        passthrough = {"approve_final_question": {"hitl_status": "approved"}}

        result = transformer.transform_with_passthrough(
            data=llm_output,
            context_data={},
            source_guid="g1",
            agent_config=_config(["approve_final_question.*"]),
            action_name="assign_batch_name",
            passthrough_fields=passthrough,
        )

        content = result[0]["content"]
        assert content.get("approve_final_question") == {"hitl_status": "approved"}
        assert content.get("assign_batch_name") == {"batch_name": "batch_A"}

    def test_action_namespace_not_polluted_with_passthrough(self):
        transformer = PassthroughTransformer()
        llm_output = [{"batch_name": "batch_A"}]
        passthrough = {"approve_final_question": {"hitl_status": "approved"}}

        result = transformer.transform_with_passthrough(
            data=llm_output,
            context_data={},
            source_guid="g1",
            agent_config=_config(["approve_final_question.*"]),
            action_name="assign_batch_name",
            passthrough_fields=passthrough,
        )

        action_output = result[0]["content"]["assign_batch_name"]
        assert "approve_final_question" not in action_output

    def test_structured_output_places_namespace_at_content_level(self):
        transformer = PassthroughTransformer()
        data = [{"source_guid": "g1", "content": {"batch_name": "batch_A"}}]
        passthrough = {"approve_final_question": {"hitl_status": "approved"}}

        result = transformer.transform_with_passthrough(
            data=data,
            context_data={},
            source_guid="g1",
            agent_config=_config(["approve_final_question.*"]),
            action_name="assign_batch_name",
            passthrough_fields=passthrough,
        )

        content = result[0]["content"]
        assert content.get("approve_final_question") == {"hitl_status": "approved"}
        assert content.get("assign_batch_name") == {"batch_name": "batch_A"}
        assert "approve_final_question" not in content["assign_batch_name"]

    def test_existing_richer_namespace_not_clobbered(self):
        """Carry-forward already holds the full namespace; the passthrough subset
        must not shrink it."""
        transformer = PassthroughTransformer()
        existing = {
            "approve_final_question": {"hitl_status": "approved", "reviewer": "ann"},
        }
        passthrough = {"approve_final_question": {"hitl_status": "approved"}}

        result = transformer.transform_with_passthrough(
            data=[{"batch_name": "batch_A"}],
            context_data={},
            source_guid="g1",
            agent_config=_config(["approve_final_question.hitl_status"]),
            action_name="assign_batch_name",
            passthrough_fields=passthrough,
            existing_content=existing,
        )

        content = result[0]["content"]
        assert content["approve_final_question"]["hitl_status"] == "approved"
        assert content["approve_final_question"]["reviewer"] == "ann"
        assert "approve_final_question" not in content["assign_batch_name"]

    def test_multiple_passthrough_namespaces_all_at_content_level(self):
        transformer = PassthroughTransformer()
        passthrough = {
            "approve_final_question": {"hitl_status": "approved"},
            "review_consolidated_answers": {"decision": "pass"},
        }

        result = transformer.transform_with_passthrough(
            data=[{"batch_name": "batch_A"}],
            context_data={},
            source_guid="g1",
            agent_config=_config(["approve_final_question.*", "review_consolidated_answers.*"]),
            action_name="assign_batch_name",
            passthrough_fields=passthrough,
        )

        content = result[0]["content"]
        assert content.get("approve_final_question") == {"hitl_status": "approved"}
        assert content.get("review_consolidated_answers") == {"decision": "pass"}
        assert "approve_final_question" not in content["assign_batch_name"]
        assert "review_consolidated_answers" not in content["assign_batch_name"]

    def test_downstream_observe_resolves_passthrough_namespace(self):
        """The stored shape must satisfy a downstream observe of the passthrough field."""
        transformer = PassthroughTransformer()
        passthrough = {"approve_final_question": {"hitl_status": "approved"}}

        result = transformer.transform_with_passthrough(
            data=[{"batch_name": "batch_A"}],
            context_data={},
            source_guid="g1",
            agent_config=_config(["approve_final_question.*"]),
            action_name="assign_batch_name",
            passthrough_fields=passthrough,
        )

        content = result[0]["content"]
        _, llm_context, _ = apply_context_scope(
            content,
            {"observe": ["approve_final_question.hitl_status"]},
            action_name="downstream",
        )
        assert llm_context.get("approve_final_question", {}).get("hitl_status") == "approved"
