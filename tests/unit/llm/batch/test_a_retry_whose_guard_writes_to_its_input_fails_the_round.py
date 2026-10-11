"""A retry round whose guard UDF writes to its input fails, not transiently (1314).

submit_retry_batch and resubmit_missing_records treat every prepare_tasks
exception as transient and swallow it, so the lost record would complete as
though a later pass could still resolve it. A write-to-input refusal is
action-fatal and must propagate instead -- the identical guard, run through
the real BatchTaskPreparator a retry round rebuilds its prompt with, not a
mocked one standing in for it.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.batch.services.retry import BatchRetryService
from agent_actions.utils.udf_management import registry as registry_module
from agent_actions.utils.udf_management.registry import UDF_REGISTRY

from .recording_provider import RecordingProvider

ACTION = "publish"
LOST = "t-1"


def guard_writes_to_its_input_1314(data):
    data["page_content"] = str(data.get("page_content", "")).strip().lower()
    return True


@pytest.fixture
def registered_udf():
    modules_before = set(registry_module._registered_modules)
    registry_module.udf_tool(guard_writes_to_its_input_1314)
    try:
        yield
    finally:
        UDF_REGISTRY.pop("guard_writes_to_its_input_1314", None)
        registry_module._registered_modules.intersection_update(modules_before)


def _config() -> dict[str, Any]:
    return {
        "name": ACTION,
        "action_name": ACTION,
        "agent_type": ACTION,
        "kind": "llm",
        "json_mode": False,
        "model_name": "test-model",
        "run_mode": "batch",
        "prompt": "Restate: {{ source.page_content }}",
        "context_scope": {"observe": ["source.page_content"]},
        "conditional_clause": "guard_writes_to_its_input_1314",
        "retry": {"enabled": True, "max_attempts": 1},
    }


def _context_map() -> dict[str, Any]:
    return {
        LOST: {
            "target_id": LOST,
            "source_guid": "sg-1",
            "content": {"source": {"page_content": " Keep "}},
        }
    }


def test_submit_retry_batch_fails_the_round_not_the_provider(tmp_path, registered_udf):
    service = BatchRetryService(action_indices={ACTION: 0}, dependency_configs={})
    provider = RecordingProvider()

    with pytest.raises(ConfigurationError, match="wrote to its input"):
        service.submit_retry_batch(
            provider=provider,
            missing_ids={LOST},
            context_map=_context_map(),
            output_directory=str(tmp_path),
            file_name="pages.json",
            agent_config=_config(),
        )

    assert provider.submitted == []


def test_retrieve_results_with_retry_fails_the_round_not_the_provider(tmp_path, registered_udf):
    service = BatchRetryService(action_indices={ACTION: 0}, dependency_configs={})
    provider = RecordingProvider()

    with pytest.raises(ConfigurationError, match="wrote to its input"):
        service.retrieve_results_with_retry(
            provider,
            "batch-0",
            str(tmp_path),
            context_map=_context_map(),
            file_name="pages.json",
            agent_config=_config(),
        )

    assert provider.submitted == []
