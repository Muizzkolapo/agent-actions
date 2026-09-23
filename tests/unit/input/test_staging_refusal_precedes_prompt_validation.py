"""The document rule is what a run reports, not a prompt failure behind it."""

import json

import pytest

from agent_actions.errors import AgentActionsError, RecordContextError
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
        assert "A staging JSON file must hold a list of records" in str(caught.value)

    def test_it_names_the_shape_it_found(self, tmp_path, label, document, found):
        with pytest.raises(AgentActionsError) as caught:
            _run(tmp_path, document)
        assert caught.value.context["document_type"] == found

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
        assert "must hold a list of records" not in str(caught.value)
