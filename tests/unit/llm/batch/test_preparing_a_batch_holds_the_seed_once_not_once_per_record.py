"""Preparing a batch holds one parsed copy of a seed file, not one for each record.

A prompt that observes a seed was handed a fresh parse of the seed file for each record,
and the prepared batch kept every one of them until it was sent: memory grew with the
records times the parsed seed. Now every record reads one shared, read-only copy, so a
record adds only what its own request carries.
"""

from __future__ import annotations

import gc
import json
import tracemalloc
from pathlib import Path
from typing import Any

import pytest

from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.providers.openai.batch_client import OpenAIBatchClient
from agent_actions.prompt.context import static_loader
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.utils.readonly import ReadOnlyError

SEED = {
    "title": "Syllabus",
    "topics": [
        {"id": f"t{i}", "name": f"topic {i}", "desc": "d" * 40, "tags": ["a", "b"]}
        for i in range(1500)
    ],
}
SEED_SCOPE = {"syllabus": {"select_by": "source.exam", "files": {"e1": "$file:e1.json"}}}


class _NoStorage:
    """A storage backend that keeps nothing it is handed."""

    def __getattr__(self, name: str) -> Any:
        return lambda *args, **kwargs: None


@pytest.fixture(autouse=True)
def _fresh_shared_loaders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(static_loader, "_SHARED_LOADERS", {})
    monkeypatch.setenv("TEST_PROVIDER_KEY", "k")


@pytest.fixture
def workflow(tmp_path: Path) -> Path:
    (tmp_path / "agent_config").mkdir()
    (tmp_path / "seed_data").mkdir()
    (tmp_path / "agent_config" / "wf.yml").write_text("name: wf\n")
    (tmp_path / "seed_data" / "e1.json").write_text(json.dumps(SEED))
    return tmp_path


def _config(workflow: Path, **scope: Any) -> dict[str, Any]:
    return {
        "agent_type": "examine",
        "action_name": "examine",
        "name": "examine",
        "model_vendor": "openai",
        "model_name": "gpt-4.1",
        "api_key": "TEST_PROVIDER_KEY",
        "json_mode": True,
        "granularity": "record",
        "run_mode": "batch",
        "prompt": "Summarise {{ source.page }} against {{ seed.syllabus.title }}.",
        "schema": {"summary": "string"},
        "context_scope": {
            "observe": ["source.page", "seed.syllabus"],
            "seed": SEED_SCOPE,
            **scope,
        },
        "workflow_config_path": str(workflow / "agent_config" / "wf.yml"),
    }


def _records(n: int) -> list[dict[str, Any]]:
    return [
        {
            "target_id": f"t{i}",
            "source_guid": f"sg{i}",
            "content": {"source": {"exam": "e1", "page": f"page {i}"}},
        }
        for i in range(n)
    ]


def _peak_of_preparing(config: dict[str, Any], n: int) -> int:
    data = _records(n)
    gc.collect()
    tracemalloc.start()
    try:
        base = tracemalloc.get_traced_memory()[0]
        prepared = BatchTaskPreparator(storage_backend=_NoStorage()).prepare_tasks(
            agent_config=config, data=data, provider=OpenAIBatchClient(api_key="k")
        )
        peak = tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()
    assert len(prepared.tasks) == n
    return peak


def _parsed_seed_size() -> int:
    text = json.dumps(SEED)
    gc.collect()
    tracemalloc.start()
    try:
        parsed = json.loads(text)
        size = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    del parsed
    return size


def test_each_record_adds_less_memory_than_one_parsed_seed(workflow):
    config = _config(workflow)
    _peak_of_preparing(config, 5)  # Imports and compiled templates are not the records'.

    per_record = (_peak_of_preparing(config, 60) - _peak_of_preparing(config, 20)) / 40

    # A record's request carries the seed as text; a parsed copy is several times that.
    assert per_record < _parsed_seed_size(), (per_record, _parsed_seed_size())


def _seed_read_by(config: dict[str, Any], page: str) -> Any:
    result = PromptPreparationService.prepare_prompt_with_field_context(
        agent_config=config,
        agent_name="examine",
        contents={},
        field_context={"source": {"exam": "e1", "page": page}},
    )
    return result.llm_context["seed"]["syllabus"]


def test_every_record_reads_the_same_read_only_seed(workflow):
    config = _config(workflow)

    first, second = _seed_read_by(config, "a"), _seed_read_by(config, "b")

    assert first is second
    assert first["title"] == "Syllabus"
    with pytest.raises(ReadOnlyError):
        first["title"] = "changed"


def test_a_scope_that_drops_a_seed_field_edits_a_copy_of_its_own(workflow):
    dropping = _config(workflow, drop=["seed.syllabus.topics"])

    edited = _seed_read_by(dropping, "a")

    assert "topics" not in edited
    assert len(_seed_read_by(_config(workflow), "b")["topics"]) == 1500


def test_a_scope_that_passes_a_seed_field_through_gets_a_copy_of_its_own(workflow):
    passing = _config(workflow, passthrough=["seed.syllabus"])

    passed = _seed_read_by(passing, "a")
    passed["title"] = "mine"

    assert _seed_read_by(_config(workflow), "b")["title"] == "Syllabus"
