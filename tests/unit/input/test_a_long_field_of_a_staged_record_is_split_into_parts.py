"""`chunk_config.field` splits one long field of each staged record into parts.

Each part is a record of its own: it keeps every other field of the record, holds one
piece of the field, and gets `chunk_index` (from 0) and `chunk_count`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from agent_actions.config.manager import ConfigManager
from agent_actions.config.schema import ChunkConfig, WorkflowConfig
from agent_actions.errors import AgentActionsError, ConfigurationError
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    InitialStageContext,
    _prepare_batch_data,
    _prepare_online_data,
    precheck_staged_file,
)
from agent_actions.output.response.expander import ActionExpander

BASE_DEFAULTS = {"model_vendor": "openai", "model_name": "gpt-4o", "api_key": "k"}
LONG_PAGE = "".join(chr(ord("a") + i % 26) for i in range(638_545))
LONG_RECORD = {"url": "https://example.test/ref", "exam": "e1", "page_content": LONG_PAGE}
SHORT_RECORD = {"url": "https://example.test/short", "exam": "e1", "page_content": "short"}
SPLIT = {"field": "source.page_content", "chunk_size": 200_000, "split_method": "chars"}


def _agent(action_chunk_config: dict | None = None, defaults_chunk_config: dict | None = None):
    action: dict[str, Any] = {"name": "assess", "intent": "i", "prompt": "p"}
    defaults: dict[str, Any] = dict(BASE_DEFAULTS)
    if action_chunk_config is not None:
        action["chunk_config"] = action_chunk_config
    if defaults_chunk_config is not None:
        defaults["chunk_config"] = defaults_chunk_config
    workflow = WorkflowConfig.model_validate(
        {"name": "wf", "description": "d", "defaults": defaults, "actions": [action]}
    )
    return ActionExpander.expand_actions_to_agents(
        {
            "name": "wf",
            "actions": [
                a.model_dump(mode="python", exclude_unset=True, by_alias=True)
                for a in workflow.actions
            ],
            "defaults": workflow.defaults.model_dump(
                mode="python", exclude_unset=True, by_alias=True
            ),
        }
    )["wf"][0]


def _staged(agent_config: dict, rows: list[dict], mode: str):
    """The `source` payload of each record the first stage makes of *rows*."""
    ctx = DataPreparationContext(
        content=rows,
        file_type=".json",
        agent_config=agent_config,
        file_path="pages.json",
        agent_name="assess",
    )
    prepared, _ = _prepare_batch_data(ctx) if mode == "batch" else _prepare_online_data(ctx)
    return prepared


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_638_545_character_field_split_at_200_000_gives_4_records_with_the_same_other_fields(
    mode,
):
    records = _staged(_agent(SPLIT), [LONG_RECORD], mode)

    sources = [record["content"]["source"] for record in records]
    assert len(sources) == 4
    for index, source in enumerate(sources):
        assert {k: v for k, v in source.items() if k != "page_content"} == {
            "url": LONG_RECORD["url"],
            "exam": LONG_RECORD["exam"],
            "chunk_index": index,
            "chunk_count": 4,
        }
    assert [len(source["page_content"]) for source in sources] == [200_000] * 3 + [38_545 + 30]
    assert (
        "".join(
            source["page_content"][10:] if i else source["page_content"]
            for i, source in enumerate(sources)
        )
        == LONG_PAGE
    )


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_each_part_is_a_record_of_its_own(mode):
    records = _staged(_agent(SPLIT), [LONG_RECORD], mode)

    assert len({record["source_guid"] for record in records}) == 4


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_record_that_fits_is_one_part(mode):
    (record,) = _staged(_agent(SPLIT), [SHORT_RECORD], mode)

    assert record["content"]["source"] == {**SHORT_RECORD, "chunk_index": 0, "chunk_count": 1}


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_record_without_the_field_is_one_part(mode):
    (record,) = _staged(_agent(SPLIT), [{"url": "u"}], mode)

    assert record["content"]["source"] == {"url": "u", "chunk_index": 0, "chunk_count": 1}


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_without_a_field_the_records_are_staged_as_they_are(mode):
    records = _staged(_agent({"chunk_size": 100, "split_method": "chars"}), [LONG_RECORD], mode)

    assert [record["content"]["source"] for record in records] == [LONG_RECORD]


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_the_field_may_be_written_without_its_namespace(mode):
    records = _staged(_agent({**SPLIT, "field": "page_content"}), [LONG_RECORD], mode)

    assert len(records) == 4


def test_a_field_in_the_defaults_block_reaches_the_first_action():
    records = _staged(_agent(defaults_chunk_config=SPLIT), [LONG_RECORD], "batch")

    assert len(records) == 4


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_the_rows_of_a_tabular_file_are_split_too(mode):
    ctx = DataPreparationContext(
        content=[LONG_RECORD],
        file_type=".xlsx",
        agent_config=_agent(SPLIT),
        file_path="pages.xlsx",
        agent_name="assess",
    )
    prepared, _ = _prepare_batch_data(ctx) if mode == "batch" else _prepare_online_data(ctx)

    assert len(prepared) == 4


@pytest.mark.parametrize("mode", ["online", "batch"])
def test_a_field_that_is_not_text_is_refused_naming_the_record(mode):
    with pytest.raises(AgentActionsError, match="page_content") as raised:
        _staged(_agent(SPLIT), [SHORT_RECORD, {"url": "u", "page_content": ["a", "b"]}], mode)

    assert raised.value.context["row_index"] == 1


@pytest.mark.parametrize("taken", ["chunk_index", "chunk_count"])
def test_a_record_that_already_holds_a_part_field_is_refused(taken):
    with pytest.raises(AgentActionsError, match=taken):
        _staged(_agent(SPLIT), [{**SHORT_RECORD, taken: 3}], "batch")


@pytest.mark.parametrize("field", ["", "source.", "source.meta.body"])
def test_a_field_that_does_not_name_one_top_level_field_is_refused_at_load(field):
    with pytest.raises(ValidationError, match="field"):
        ChunkConfig.model_validate({"field": field})


def test_a_field_in_the_project_defaults_is_refused():
    manager = ConfigManager.__new__(ConfigManager)
    manager.default_config = {"default_agent_config": {"chunk_config": {"field": "page_content"}}}
    manager.tool_path = None
    manager.agent_configs = {}

    with pytest.raises(ConfigurationError, match="field"):
        manager.merge_agent_configs([_agent()])


def test_a_field_on_the_action_reaches_the_staging_of_the_merged_agent():
    manager = ConfigManager.__new__(ConfigManager)
    manager.default_config = {"default_agent_config": {"chunk_config": {"chunk_overlap": 0}}}
    manager.tool_path = None
    manager.agent_configs = {}
    manager.merge_agent_configs([_agent(SPLIT)])
    merged = manager.agent_configs["assess"].model_dump()

    records = _staged(merged, [LONG_RECORD], "batch")

    lengths = [len(record["content"]["source"]["page_content"]) for record in records]
    assert lengths == [200_000] * 3 + [38_545]


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_a_prompt_reading_the_part_fields_passes_the_staging_check(run_mode, tmp_path):
    staging = tmp_path / "agent_io" / "staging"
    staging.mkdir(parents=True)
    (staging / "pages.json").write_text(json.dumps([LONG_RECORD, SHORT_RECORD]))
    config: dict[str, Any] = {
        "run_mode": run_mode,
        "workflow_config_path": str(tmp_path / "agent_config" / "wf.yml"),
        "prompt": "{{ source.url }} part {{ source.chunk_index }} of {{ source.chunk_count }}",
        "context_scope": {"observe": ["source.url", "source.chunk_index", "source.chunk_count"]},
        "chunk_config": SPLIT,
    }
    ctx = InitialStageContext(
        agent_config=config,
        agent_name="assess",
        file_path=str(staging / "pages.json"),
        base_directory=str(staging),
        output_directory=str(tmp_path / "agent_io" / "target" / "assess"),
        action_configs={"assess": config},
    )

    precheck_staged_file(ctx)

    config.pop("chunk_config")
    with pytest.raises(AgentActionsError, match="chunk_index"):
        precheck_staged_file(ctx)
