"""The batch preflight passes over a record refused for having no source_guid, and nothing else.

It renders the first prompts to stop a broken template before anything is sent. A refused
record renders nothing, so it says nothing about the template; any other error preparing
the head record is what the preflight is there to stop on.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import DataValidationError, MissingSourceGuidError
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.processing.prepared_task import GuardStatus


def _preflight(head_raises: Exception) -> int:
    """Run the preflight over two records, the first refused with *head_raises*.

    Returns how many it prepared.
    """
    preparer = MagicMock()
    preparer.prepare.side_effect = [head_raises, MagicMock(guard_status=GuardStatus.PASSED)]
    with patch(
        "agent_actions.llm.batch.processing.preparator.get_task_preparer", return_value=preparer
    ):
        BatchTaskPreparator()._run_preflight_validation(
            {"name": "write_question", "prompt": "{{ flatten.topic }}"},
            [{"target_id": "t-n1"}, {"target_id": "t-a1", "source_guid": "a1"}],
        )
    return preparer.prepare.call_count


def test_a_record_refused_for_having_no_source_guid_does_not_end_the_preflight():
    assert _preflight(MissingSourceGuidError("Record t-n1 reached ... without a source_guid")) == 2


def test_any_other_data_error_on_the_head_record_stops_the_preflight():
    with pytest.raises(DataValidationError, match="no content namespace"):
        _preflight(DataValidationError("no content namespace"))
