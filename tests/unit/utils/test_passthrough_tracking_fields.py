"""Tests for PassthroughTransformer preserving tracking fields via input_record."""

from agent_actions.utils.transformation.passthrough import PassthroughTransformer


def _simple_config():
    return {"agent_type": "summarize"}


class TestPassthroughTransformerInputRecord:
    def test_tracking_fields_carried_when_input_record_provided(self):
        """version_correlation_id must reach the output when input_record is given."""
        transformer = PassthroughTransformer()
        data = [{"summary": "short version"}]
        context_data = {"summary": "short version"}
        input_record = {
            "source_guid": "g1",
            "version_correlation_id": "vcid-original",
            "content": {"source": {"raw": "data"}},
        }

        results = transformer.transform_with_passthrough(
            data=data,
            context_data=context_data,
            source_guid="g1",
            agent_config=_simple_config(),
            action_name="summarize",
            input_record=input_record,
        )

        assert len(results) == 1
        assert results[0]["version_correlation_id"] == "vcid-original"

    def test_tracking_fields_absent_when_no_input_record(self):
        """Without input_record, version_correlation_id is not injected by the transformer."""
        transformer = PassthroughTransformer()
        data = [{"summary": "short version"}]
        context_data = {"summary": "short version"}

        results = transformer.transform_with_passthrough(
            data=data,
            context_data=context_data,
            source_guid="g1",
            agent_config=_simple_config(),
            action_name="summarize",
        )

        assert len(results) == 1
        assert "version_correlation_id" not in results[0]

    def test_source_guid_carried_from_input_record(self):
        """source_guid from input_record must appear in output."""
        transformer = PassthroughTransformer()
        data = [{"summary": "short"}]
        input_record = {
            "source_guid": "guid-from-input",
            "content": {},
        }

        results = transformer.transform_with_passthrough(
            data=data,
            context_data={"summary": "short"},
            source_guid="guid-fallback",
            agent_config=_simple_config(),
            action_name="summarize",
            input_record=input_record,
        )

        assert results[0]["source_guid"] == "guid-from-input"

    def test_metadata_not_leaked_from_input_record(self):
        """metadata in input_record must NOT bleed into output (per-stage field)."""
        transformer = PassthroughTransformer()
        data = [{"summary": "short"}]
        input_record = {
            "source_guid": "g1",
            "metadata": {"model": "gpt-4", "tokens": 100},
            "content": {},
        }

        results = transformer.transform_with_passthrough(
            data=data,
            context_data={"summary": "short"},
            source_guid="g1",
            agent_config=_simple_config(),
            action_name="summarize",
            input_record=input_record,
        )

        assert "metadata" not in results[0]

    def test_existing_content_wins_when_richer_than_input_record_content(self):
        """First-stage records: existing_content (synthesised by extract_existing_content)
        may be richer than input_record['content']. Both are honoured — tracking fields
        come from input_record, namespaces come from existing_content.
        """
        transformer = PassthroughTransformer()
        data = [{"summary": "short"}]
        # Simulate a first-stage record with no 'content' key: existing_content is
        # synthesised as {"source": raw_fields} but input_record has no content.
        input_record = {
            "source_guid": "g1",
            "version_correlation_id": "vcid-first-stage",
        }
        existing_content = {"source": {"raw_field": "value"}}

        results = transformer.transform_with_passthrough(
            data=data,
            context_data={"summary": "short"},
            source_guid="g1",
            agent_config=_simple_config(),
            action_name="summarize",
            input_record=input_record,
            existing_content=existing_content,
        )

        assert len(results) == 1
        # Tracking field preserved from input_record
        assert results[0]["version_correlation_id"] == "vcid-first-stage"
        # Upstream namespace preserved from existing_content
        assert results[0]["content"].get("source") == {"raw_field": "value"}
