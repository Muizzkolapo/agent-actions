"""Under batch, a guard UDF's write on a later row only fails that record alone (1314).

The pre-submit preflight check covers the leading rows up to the first one the
guard admits — at most five — and runs outside the main per-row loop, so a
write past that window was treated as an ordinary per-record failure instead
of action-fatal: the file submitted and completed with just that record
failed, where online fails the whole action.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import is_action_fatal
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.utils.udf_management import registry as registry_module
from agent_actions.utils.udf_management.registry import UDF_REGISTRY


def guard_tidy_or_reject_1314(data):
    namespace = data["content"] if "content" in data else data
    tier = namespace.get("page_content", "")
    tidy = tier.strip().lower()
    if tidy != tier:
        namespace["page_content"] = tidy
    return tidy != "reject"


@pytest.fixture
def registered_udf():
    modules_before = set(registry_module._registered_modules)
    registry_module.udf_tool(guard_tidy_or_reject_1314)
    try:
        yield
    finally:
        UDF_REGISTRY.pop("guard_tidy_or_reject_1314", None)
        registry_module._registered_modules.intersection_update(modules_before)


def _agent_config() -> dict:
    return {
        "agent_type": "test",
        "action_name": "test_action",
        "model_vendor": "openai",
        "model_name": "gpt-4",
        "json_mode": False,
        "conditional_clause": "guard_tidy_or_reject_1314",
        "granularity": "record",
        "context_scope": {"observe": ["source.page_content"]},
    }


@patch("agent_actions.prompt.formatter.PromptFormatter.get_raw_prompt", return_value="Hello.")
def test_a_write_past_the_preflight_window_fails_the_whole_action(_mock_prompt, registered_udf):
    """Row 1 is tidy already (preflight admits it and stops there); row 2's
    write happens only in the main loop, past the preflight's reach."""
    data = [
        {"target_id": "t1", "source_guid": "sg1", "content": {"page_content": "keep"}},
        {"target_id": "t2", "source_guid": "sg2", "content": {"page_content": " Reject "}},
    ]
    preparator = BatchTaskPreparator(action_indices={}, dependency_configs={})
    mock_provider = MagicMock()
    mock_provider.prepare_tasks.return_value = []

    with pytest.raises(Exception) as excinfo:
        preparator.prepare_tasks(
            agent_config=_agent_config(),
            data=data,
            provider=mock_provider,
            output_directory="/tmp/test",
        )

    assert is_action_fatal(excinfo.value)
