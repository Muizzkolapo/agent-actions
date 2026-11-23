"""A batch file of a prompt with a cache point holds the records of one source next to each
other."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.providers.anthropic.batch_client import AnthropicBatchClient

WITH_POINT = "{{ source.page_content }}\n{% cache_point %}\n{{ source.fact }}\n"
WITHOUT_POINT = "{{ source.page_content }}\n{{ source.fact }}\n"
# Two pages, their records interleaved as an upstream batch may return them.
ROWS = (
    ("a1", "page-a", "Page A."),
    ("b1", "page-b", "Page B."),
    ("a2", "page-a", "Page A."),
    ("b2", "page-b", "Page B."),
    ("a3", "page-a", "Page A."),
)


def _order(tmp_path: Path, prompt: str, *, caching: bool = True) -> list[str]:
    config: dict[str, Any] = {
        "agent_type": "write",
        "action_name": "write",
        "name": "write",
        "model_vendor": "anthropic",
        "model_name": "claude-sonnet-4-6",
        "api_key": "TEST_PROVIDER_KEY",
        "json_mode": False,
        "granularity": "record",
        "enable_prompt_caching": caching,
        "prompt": prompt,
        "context_scope": {"observe": ["source.page_content", "source.fact"]},
    }
    data = [
        {
            "target_id": target_id,
            "source_guid": f"sg-{target_id}",
            "parent_source_guid": page,
            "content": {"page_content": text, "fact": target_id},
        }
        for target_id, page, text in ROWS
    ]
    prepared = BatchTaskPreparator(
        action_indices={}, dependency_configs={}, storage_backend=MagicMock()
    ).prepare_tasks(
        agent_config=config,
        data=data,
        provider=AnthropicBatchClient(api_key="sk-ant-test", enable_prompt_caching=caching),
        output_directory=str(tmp_path),
    )
    assert list(prepared.context_map) == [target_id for target_id, _, _ in ROWS]
    return [task["custom_id"] for task in prepared.tasks]


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PROVIDER_KEY", "sk-test")


def test_records_of_one_source_are_written_next_to_each_other(tmp_path):
    assert _order(tmp_path, WITH_POINT) == ["a1", "a2", "a3", "b1", "b2"]


def test_a_prompt_without_a_cache_point_keeps_the_order_of_its_records(tmp_path):
    assert _order(tmp_path, WITHOUT_POINT) == ["a1", "b1", "a2", "b2", "a3"]


def test_a_client_that_marks_no_cache_point_keeps_the_order_of_its_records(tmp_path):
    assert _order(tmp_path, WITH_POINT, caching=False) == ["a1", "b1", "a2", "b2", "a3"]


def test_records_already_side_by_side_keep_their_order(tmp_path, monkeypatch):
    grouped = (ROWS[1], ROWS[3], ROWS[0], ROWS[2], ROWS[4])
    monkeypatch.setattr(f"{__name__}.ROWS", grouped)

    assert _order(tmp_path, WITH_POINT) == ["b1", "b2", "a1", "a2", "a3"]
