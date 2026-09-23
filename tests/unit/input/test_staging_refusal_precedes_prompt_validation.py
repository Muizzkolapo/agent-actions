"""The document rule is what a run reports, not a prompt failure behind it."""

import json

import pytest

from agent_actions.errors import (
    AgentActionsError,
    ConfigValidationError,
    RecordContextError,
)
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    InitialStageContext,
    process_initial_stage,
)

CONFIG = {
    "run_mode": "online",
    "prompt": "Label {{ source.ticket_id }}: {{ source.text }}",
    "context_scope": {"observe": ["source.ticket_id", "source.text"]},
}
RECORD = {"ticket_id": "T-1", "text": "Server is down"}


def _run(tmp_path, document):
    staging = tmp_path / "agent_io" / "staging"
    staging.mkdir(parents=True)
    target = tmp_path / "agent_io" / "target" / "extract"
    target.mkdir(parents=True)
    doc = staging / "ticket.json"
    doc.write_text(json.dumps(document))
    return process_initial_stage(
        InitialStageContext(
            agent_config=dict(CONFIG),
            agent_name="extract",
            file_path=str(doc),
            base_directory=str(staging),
            output_directory=str(target),
            idx=0,
        )
    )


@pytest.mark.parametrize(
    ("label", "document", "found"),
    [("object", RECORD, "dict"), ("number", 42, "int"), ("string", "hello", "str")],
)
class TestWhatTheRunReports:
    def test_it_is_the_document_rule(self, tmp_path, label, document, found):
        with pytest.raises(AgentActionsError) as caught:
            _run(tmp_path, document)
        assert "A staged input must be rows" in str(caught.value)

    def test_it_names_the_shape_it_found(self, tmp_path, label, document, found):
        with pytest.raises(AgentActionsError) as caught:
            _run(tmp_path, document)
        assert caught.value.context["content_type"] == found

    def test_it_is_not_a_prompt_failure(self, tmp_path, label, document, found):
        with pytest.raises(AgentActionsError) as caught:
            _run(tmp_path, document)
        assert not isinstance(caught.value, RecordContextError)


class TestPromptValidationStillRunsForAList:
    def test_a_record_missing_an_observed_field_is_a_prompt_failure(self, tmp_path):
        with pytest.raises(RecordContextError) as caught:
            _run(tmp_path, [{"ticket_id": "T-1"}])
        assert "source.text" in str(caught.value)

    def test_that_failure_is_not_the_document_rule(self, tmp_path):
        with pytest.raises(RecordContextError) as caught:
            _run(tmp_path, [{"ticket_id": "T-1"}])
        assert "A staged input must be rows" not in str(caught.value)


class TestARowThatIsNotARecord:
    def test_a_list_holding_a_bare_value_reports_the_row_rule(self, tmp_path):
        with pytest.raises(AgentActionsError) as caught:
            _run(tmp_path, [42])
        assert "A staged row must be an object" in str(caught.value)

    def test_it_names_the_row_it_stopped_on(self, tmp_path):
        with pytest.raises(AgentActionsError) as caught:
            _run(tmp_path, [RECORD, "not a record"])
        assert caught.value.context["row_index"] == 1

    def test_it_is_not_a_prompt_failure(self, tmp_path):
        with pytest.raises(AgentActionsError) as caught:
            _run(tmp_path, [42])
        assert not isinstance(caught.value, RecordContextError)


class TestAReservedKeyDoesNotHideTheDocumentRule:
    """The namespace guard runs after the document rule, so it only sees records."""

    def test_a_lone_object_carrying_a_reserved_key_reports_the_document_rule(self, tmp_path):
        with pytest.raises(AgentActionsError) as caught:
            _run(tmp_path, {"version": "2024-01", "items": [{"ticket_id": "T-1"}]})
        assert "A staged input must be rows" in str(caught.value)

    def test_a_list_row_carrying_a_reserved_key_still_reports_the_collision(self, tmp_path):
        """A real record with a reserved field name is still the guard's business."""
        with pytest.raises(ConfigValidationError) as caught:
            _run(tmp_path, [{"version": "2024-01", "ticket_id": "T-1", "text": "x"}])
        assert "collide with reserved namespace names" in str(caught.value)


class TestTheRemedyFitsWhatWasFound:
    def test_an_object_is_told_to_wrap_itself(self, tmp_path):
        with pytest.raises(AgentActionsError) as caught:
            _run(tmp_path, RECORD)
        assert "Wrap it in an array: [ ... ]." in str(caught.value)

    def test_a_bare_value_is_not_told_to_wrap(self, tmp_path):
        """Wrapping a bare value only buys a second refusal about the row inside."""
        with pytest.raises(AgentActionsError) as caught:
            _run(tmp_path, 42)
        assert "Wrap it in an array" not in str(caught.value)
        assert "Give each record its own object" in str(caught.value)
