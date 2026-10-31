"""Each line the formatter builds reads its event's names as text, not as markup.

The first tests drove the methods that carry error text. These are the ones that carry
only identifiers, which is what a name or a batch id is until one holds a bracket.
"""

import pytest
from rich.text import Text

from agent_actions.logging.events import (
    ActionCachedEvent,
    ActionCompleteEvent,
    ActionFailedEvent,
    ActionSkipEvent,
    ActionStartEvent,
    BatchCompleteEvent,
    BatchSubmittedEvent,
    WorkflowFailedEvent,
    WorkflowStartEvent,
)
from agent_actions.logging.events.formatters import AgentActionsFormatter

NAME = "[fragile]_[/x]"


@pytest.mark.parametrize(
    "event",
    [
        WorkflowStartEvent(workflow_name=NAME, action_count=1, execution_mode="parallel"),
        ActionStartEvent(action_name=NAME, total_actions=1),
        ActionCompleteEvent(action_name=NAME, total_actions=1, execution_time=0.1),
        ActionCachedEvent(action_name=NAME, total_actions=1),
        BatchCompleteEvent(batch_id=NAME, elapsed_time=1.0),
        ActionFailedEvent(action_name=NAME, total_actions=1, error_message="boom"),
        ActionSkipEvent(action_name=NAME, total_actions=1, skip_reason="guard"),
        WorkflowFailedEvent(workflow_name=NAME, error_message="boom"),
        BatchSubmittedEvent(batch_id=NAME, request_count=1, provider="p"),
    ],
    ids=[
        "workflow_start",
        "action_start",
        "action_complete",
        "action_cached",
        "batch_complete",
        "action_failed",
        "action_skip",
        "workflow_failed",
        "batch_submitted",
    ],
)
def test_the_name_survives_being_read_as_markup(event):
    line = AgentActionsFormatter(show_timestamp=False, use_color=True).format(event)

    assert NAME in Text.from_markup(line).plain
