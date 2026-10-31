"""A batch prep failure on a record with no target_id logs a warning."""

import logging

from agent_actions.llm.batch.core.batch_constants import FilterStatus
from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator

_PREPARATOR_LOGGER = "agent_actions.llm.batch.processing.preparator"


class TestPrepFailedLogging:
    """U-2.G: _mark_prep_failed must warn when target_id is missing."""

    def test_prep_failed_without_target_id_logs_warning(self, caplog):
        """When prep fails and record has no target_id, WARNING must appear in logs."""
        preparator = BatchTaskPreparator()
        record_without_target = {"content": {"text": "no target_id here"}}
        context_map = {}

        with caplog.at_level(logging.WARNING, logger=_PREPARATOR_LOGGER):
            preparator._mark_prep_failed(
                record_without_target,
                context_map,
                "test_agent",
                ValueError("test error"),
            )

        assert any("target_id" in r.message and r.levelname == "WARNING" for r in caplog.records), (
            "Missing WARNING about absent target_id on prep failure"
        )

    def test_prep_failed_with_target_id_no_extra_warning(self, caplog):
        """When prep fails and target_id exists, no warning about missing target_id."""
        preparator = BatchTaskPreparator()
        record = {"target_id": "t-001", "content": {"text": "has target"}}
        context_map = {"t-001": record.copy()}
        BatchContextMetadata.set_filter_status(context_map["t-001"], FilterStatus.INCLUDED)

        with caplog.at_level(logging.WARNING, logger=_PREPARATOR_LOGGER):
            preparator._mark_prep_failed(
                record,
                context_map,
                "test_agent",
                ValueError("test error"),
            )

        target_id_warnings = [
            r
            for r in caplog.records
            if "target_id" in r.message and "untrackable" in r.message and r.levelname == "WARNING"
        ]
        assert len(target_id_warnings) == 0, (
            "Should NOT warn about missing target_id when target_id is present"
        )
