"""`add_dispatch` puts the schema a record's dispatch chose on its answer, in batch as online.

Online merges `{function: chosen}` into every item of the response before anything reads
it. Batch kept the chosen name on the context map and never put it on the answer. Each
case prepares two records for real, so the dispatch function runs once per record.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.expectations.service import create_expectation_service_from_config
from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.services.shared import retrieve_and_reconcile
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.evaluation.strategies import ExpectationStrategy
from agent_actions.processing.helpers import run_dynamic_agent, transform_with_passthrough

ACTION = "label_page"
PROMPT = "Label it."
TOOL = """\
import json


def pick_schema(context_json):
    page_id = json.loads(context_json)["source"]["page_id"]
    return "topic_answer" if page_id == "p1" else "verdict_answer"
"""
ANSWERS: dict[str, Any] = {
    "an object": {"t1": {"topic": "cats"}, "t2": {"verdict": "yes"}},
    "a list of objects": {
        "t1": [{"topic": "cats"}, {"topic": "dogs"}],
        "t2": [{"verdict": "yes"}],
    },
    "a list with a non-object": {"t1": [{"topic": "cats"}, "dogs"], "t2": ["yes"]},
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "agent_actions.yml").write_text("required_by_default: true\nschema_path: schema\n")
    (tmp_path / "schema").mkdir()
    for name, field in (("topic_answer", "topic"), ("verdict_answer", "verdict")):
        (tmp_path / "schema" / f"{name}.yml").write_text(
            f"name: {name}\nfields:\n  - id: {field}\n    type: string\n"
        )
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "pick_schema.py").write_text(TOOL)
    return tmp_path


def _config(project: Path, **overrides: Any) -> dict[str, Any]:
    return {
        "agent_type": ACTION,
        "action_name": ACTION,
        "model_vendor": "openai",
        "model_name": "gpt-4o",
        "json_mode": True,
        "granularity": "record",
        "schema": "dispatch_task('pick_schema')",
        "schema_options": ["topic_answer", "verdict_answer"],
        "add_dispatch": True,
        "tool_path": [str(project / "tools")],
        "_project_root": str(project),
        "context_scope": {"observe": ["source.page_id"]},
        **overrides,
    }


def _rows() -> list[dict[str, Any]]:
    return [
        {"target_id": f"t{i}", "source_guid": f"sg{i}", "content": {"page_id": f"p{i}"}}
        for i in (1, 2)
    ]


def _context_map(config: dict[str, Any]) -> dict[str, Any]:
    """The context map a real preparation stores for the two records."""
    provider = MagicMock()
    provider.prepare_tasks.return_value = []
    with patch(
        "agent_actions.prompt.formatter.PromptFormatter.get_raw_prompt", return_value=PROMPT
    ):
        prepared = BatchTaskPreparator(action_indices={}, dependency_configs={}).prepare_tasks(
            agent_config=config,
            data=_rows(),
            provider=provider,
            output_directory=str(Path(config["_project_root"]) / "out"),
        )
    return prepared.context_map


def _returned(config: dict[str, Any], answers: dict[str, Any]) -> tuple[list[BatchResult], dict]:
    """The results as the collect pass reads them from the provider."""
    context_map = _context_map(config)
    provider = MagicMock()
    provider.retrieve_results.return_value = [
        BatchResult(custom_id=custom_id, content=answer, success=True)
        for custom_id, answer in answers.items()
    ]
    results = retrieve_and_reconcile(
        provider, "b1", None, context_map=context_map, agent_config=config
    )
    return results, context_map


def _batch(config: dict[str, Any], answers: dict[str, Any]) -> dict[str, list[Any]]:
    results, context_map = _returned(config, answers)
    stored: dict[str, list[Any]] = {}
    for result in BatchResultStrategy().process(
        results, context_map=context_map, agent_config=config
    ):
        for row in result.data:
            stored.setdefault(row["target_id"], []).append(row["content"][ACTION])
    return stored


def _online(config: dict[str, Any], answers: dict[str, Any]) -> dict[str, list[Any]]:
    stored: dict[str, list[Any]] = {}
    for row in _rows():
        answer = answers[row["target_id"]]
        llm_context = {"source": dict(row["content"])}
        with patch(
            "agent_actions.llm.realtime.builder.create_dynamic_agent",
            return_value=answer if isinstance(answer, list) else [answer],
        ):
            response, _ = run_dynamic_agent(
                config, ACTION, llm_context, PROMPT, llm_context=llm_context
            )
        records = transform_with_passthrough(
            response,
            row["content"],
            row["source_guid"],
            config,
            action_name=ACTION,
            existing_content=row["content"],
            input_record=row,
        )
        stored[row["target_id"]] = [record["content"][ACTION] for record in records]
    return stored


@pytest.mark.parametrize("answers", ANSWERS.values(), ids=ANSWERS.keys())
def test_the_stored_answer_is_the_one_online_stores(project, answers):
    config = _config(project)
    assert _batch(config, answers) == _online(config, answers)


def test_each_record_names_the_schema_its_dispatch_chose(project):
    """Pinned outright, so agreeing on a wrong record cannot pass the parity test."""
    assert _batch(_config(project), ANSWERS["an object"]) == {
        "t1": [{"topic": "cats", "pick_schema": "topic_answer"}],
        "t2": [{"verdict": "yes", "pick_schema": "verdict_answer"}],
    }


def test_a_text_answer_is_stored_as_online_stores_it(project):
    """Without JSON mode the answer becomes an object only where it is stored."""
    config = _config(project, json_mode=False)
    answers = {"t1": "cats", "t2": "yes"}
    online = {key: {"raw_response": text} for key, text in answers.items()}

    assert _batch(config, answers) == _online(config, online)


def test_without_add_dispatch_nothing_is_added(project):
    config = _config(project, add_dispatch=None)
    assert _batch(config, ANSWERS["an object"]) == {
        "t1": [{"topic": "cats"}],
        "t2": [{"verdict": "yes"}],
    }


def test_a_rule_reads_the_chosen_schema_in_a_repair_pass(project):
    """The repair loop evaluates the answer as returned, so it must hold the name by then."""
    expect = {
        "repair": "auto",
        "expectations": [
            {
                "id": "schema_named",
                "type": "expression",
                "params": {
                    "condition": "pick_schema == 'topic_answer' or pick_schema == 'verdict_answer'"
                },
            }
        ],
    }
    config = _config(project, expect=expect)
    results, _ = _returned(config, ANSWERS["an object"])
    strategy = ExpectationStrategy(
        create_expectation_service_from_config(expect, action_name=ACTION, agent_config=config)
    )

    assert [strategy.evaluate(result).passed for result in results] == [True, True]
