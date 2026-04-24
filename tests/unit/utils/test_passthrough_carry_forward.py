"""Tests for record mode namespace carry-forward in passthrough transformation.

Verifies that upstream action namespaces from the input record are preserved
in the output when a record mode LLM action processes a record.
"""

from agent_actions.utils.transformation.passthrough import PassthroughTransformer


class TestCarryForwardNamespaces:
    """PassthroughTransformer.transform_with_passthrough merges existing_content."""

    def _make_agent_config(self, action_name="current_action"):
        return {"agent_type": action_name}

    def test_upstream_namespaces_carried_forward(self):
        """Output includes both upstream namespaces and current action's namespace."""
        transformer = PassthroughTransformer()
        existing = {
            "extract": {"text": "hello"},
            "summarize": {"summary": "hi"},
        }
        llm_output = [{"score": 0.9, "label": "positive"}]

        result = transformer.transform_with_passthrough(
            data=llm_output,
            context_data={},
            source_guid="guid-1",
            agent_config=self._make_agent_config("classify"),
            action_name="classify",
            existing_content=existing,
        )

        assert len(result) == 1
        content = result[0]["content"]
        assert content["extract"] == {"text": "hello"}
        assert content["summarize"] == {"summary": "hi"}
        assert content["classify"] == {"score": 0.9, "label": "positive"}

    def test_no_existing_content_still_works(self):
        """When existing_content is None, output is unchanged."""
        transformer = PassthroughTransformer()
        llm_output = [{"answer": "42"}]

        result = transformer.transform_with_passthrough(
            data=llm_output,
            context_data={},
            source_guid="guid-1",
            agent_config=self._make_agent_config("qa"),
            action_name="qa",
            existing_content=None,
        )

        assert len(result) == 1
        content = result[0]["content"]
        assert content == {"qa": {"answer": "42"}}

    def test_empty_existing_content_no_effect(self):
        """Empty dict existing_content has no effect."""
        transformer = PassthroughTransformer()
        llm_output = [{"answer": "42"}]

        result = transformer.transform_with_passthrough(
            data=llm_output,
            context_data={},
            source_guid="guid-1",
            agent_config=self._make_agent_config("qa"),
            action_name="qa",
            existing_content={},
        )

        assert len(result) == 1
        content = result[0]["content"]
        assert content == {"qa": {"answer": "42"}}

    def test_three_upstream_actions_all_preserved(self):
        """Three upstream namespaces plus current action all present in output."""
        transformer = PassthroughTransformer()
        existing = {
            "flatten_canonical_questions": {"questions": ["q1", "q2"]},
            "deduplicate_across_documents": {"unique": ["q1"]},
            "filter_learning_quality_1": {"quality": "high"},
        }
        llm_output = [{"grade": "A"}]

        result = transformer.transform_with_passthrough(
            data=llm_output,
            context_data={},
            source_guid="guid-1",
            agent_config=self._make_agent_config("grade_content"),
            action_name="grade_content",
            existing_content=existing,
        )

        content = result[0]["content"]
        assert set(content.keys()) == {
            "flatten_canonical_questions",
            "deduplicate_across_documents",
            "filter_learning_quality_1",
            "grade_content",
        }
        assert content["grade_content"] == {"grade": "A"}

    def test_current_action_wins_on_namespace_conflict(self):
        """If the current action name collides with an upstream namespace, current wins."""
        transformer = PassthroughTransformer()
        existing = {"rerun": {"old": True}}
        llm_output = [{"new": True}]

        result = transformer.transform_with_passthrough(
            data=llm_output,
            context_data={},
            source_guid="guid-1",
            agent_config=self._make_agent_config("rerun"),
            action_name="rerun",
            existing_content=existing,
        )

        content = result[0]["content"]
        assert content["rerun"] == {"new": True}

    def test_already_structured_data_gets_merge(self):
        """Already-structured data (NoOpStrategy path) also gets existing_content merged."""
        transformer = PassthroughTransformer()
        existing = {"upstream": {"val": 1}}
        structured_data = [{"source_guid": "guid-1", "content": {"current": {"result": "ok"}}}]

        result = transformer.transform_with_passthrough(
            data=structured_data,
            context_data={},
            source_guid="guid-1",
            agent_config=self._make_agent_config("current"),
            action_name="current",
            existing_content=existing,
        )

        content = result[0]["content"]
        assert content["upstream"] == {"val": 1}
        assert content["current"] == {"result": "ok"}

    def test_multiple_output_records_all_get_merge(self):
        """When LLM produces multiple output records, all get upstream namespaces."""
        transformer = PassthroughTransformer()
        existing = {"extract": {"text": "hello"}}
        llm_output = [
            {"variant": "A"},
            {"variant": "B"},
        ]

        result = transformer.transform_with_passthrough(
            data=llm_output,
            context_data={},
            source_guid="guid-1",
            agent_config=self._make_agent_config("generate"),
            action_name="generate",
            existing_content=existing,
        )

        assert len(result) == 2
        for item in result:
            assert item["content"]["extract"] == {"text": "hello"}
            assert "generate" in item["content"]
