"""A record carried from an interrupted run's checkpoint is stored as an answered one is (1264).

An action stopped before it stores a file leaves a checkpoint row for each record of it
the action answered, and the next run carries those records from them. A checkpoint row
is what the action returned, before enrichment and collection, and the carry stored it
as it was: without lineage, metadata, a parent or a root, and with no entry of the
action's in its state history, so each reader built its rows on a lineage cut short. An
answer that failed to parse was stored as processed, where collection fails it.

Every run is an `agac run` through the CLI, executor, store and the action's own tool or
the mock provider. Only the interrupt is stood in for.
"""

import shutil

import pytest

from agent_actions.llm.providers.agac.client import AgacClient
from tests.integration import test_a_resumed_run_keeps_every_row_of_an_expanded_record as tagging
from tests.integration import (
    test_a_stopped_action_keeps_only_what_its_config_still_answers as summarizing,
)
from tests.integration.test_a_stopped_action_keeps_only_what_its_config_still_answers import (
    online,  # noqa: F401
    project,  # noqa: F401
    provider,  # noqa: F401
)

CONFIG = f"""name: {tagging.WORKFLOW}
description: "An action tagging each staged item once, and its reader"
version: "1.0.0"

defaults:
  json_mode: true
  granularity: Record
  is_operational: true
  run_mode: online
  data_source:
    type: local
    folder: ./staging
    file_type: [json]

actions:
  - name: stage_items
    kind: tool
    impl: stage_items
    intent: "Stage"
    schema: {{ item_id: string, text: string }}
    context_scope:
      observe: [source.item_id, source.text]

  - name: {tagging.ACTION}
    kind: tool
    impl: tag_once
    dependencies: [stage_items]
    intent: "Tag each item"
    schema: {{ tag: string }}
    context_scope:
      observe: [stage_items.*]

  - name: {tagging.READER}
    kind: tool
    impl: read_the_tag
    dependencies: [{tagging.ACTION}]
    intent: "Read each tag"
    schema: {{ seen: string }}
    context_scope:
      observe: [{tagging.ACTION}.*]
"""

FAIL_AT = "AGAC_TEST_FAIL_AT"

# Named apart from the other tests' tools: discovery keeps a tool module by its name, and
# the registry a tool by its own.
TOOLS = f"""import os
from typing import Any

from agent_actions import udf_tool


@udf_tool()
def tag_once(data: dict[str, Any]) -> dict[str, Any]:
    item = (data.get("stage_items") or {{}}).get("item_id", "")
    if os.environ.get("{tagging.STOP_AT}") == item:
        raise KeyboardInterrupt()
    if os.environ.get("{FAIL_AT}") == item:
        raise ValueError(f"no tag for {{item}}")
    return {{"tag": item}}


@udf_tool()
def read_the_tag(data: dict[str, Any]) -> dict[str, Any]:
    return {{"seen": (data.get("{tagging.ACTION}") or {{}}).get("tag", "")}}
"""

PARSE_ERROR = "Failed to parse JSON from LLM response"


@pytest.fixture
def tagged(tmp_path, monkeypatch):
    """Three staged items, alpha, beta and gamma, a tag for each, and a reader of the tags."""
    from agent_actions.utils import path_utils

    root = tmp_path / "tagged"
    shutil.copytree(
        tagging.SOURCE, root, ignore=shutil.ignore_patterns("logs", "store", "__pycache__")
    )
    workflow = root / "agent_workflow" / tagging.WORKFLOW
    (workflow / "agent_config" / f"{tagging.WORKFLOW}.yml").write_text(CONFIG)
    (root / "tools" / tagging.WORKFLOW / "tag_once.py").write_text(TOOLS)
    monkeypatch.chdir(root)
    monkeypatch.delenv("AGAC_RECORD_LIMIT", raising=False)
    monkeypatch.delenv(tagging.STOP_AT, raising=False)
    monkeypatch.delenv(FAIL_AT, raising=False)
    # A run installs a global path manager; left behind, it sends later tests' writes here.
    monkeypatch.setattr(path_utils, "_global_path_manager", path_utils._global_path_manager)
    return root


def _interrupted_at_gamma(root, monkeypatch):
    """A first run stopped on gamma, having finished alpha and beta and stored nothing."""
    monkeypatch.setenv(tagging.STOP_AT, "gamma")
    tagging._run("--fresh")
    monkeypatch.delenv(tagging.STOP_AT)
    assert tagging._status(root) == "interrupted"
    assert tagging._stored(root, tagging.ACTION) == []


def _by_guid(rows):
    return {row["source_guid"]: row for row in rows}


def _transitions(row, action):
    """The states *action* moved the record to, as its history records them."""
    return [entry["to"] for entry in row.get("_state_history") or [] if entry["action"] == action]


def _page(row):
    return ((row.get("content") or {}).get("source") or {}).get("page_content")


def test_a_record_carried_from_its_checkpoint_keeps_the_lineage_of_its_input(tagged, monkeypatch):
    """Gamma stops the first run, so nothing of the file is stored and alpha and beta are
    carried from their checkpoint rows. The reader builds its lineage on theirs."""
    _interrupted_at_gamma(tagged, monkeypatch)

    result = tagging._run()

    assert result.exit_code == 0, result.output
    staged = _by_guid(tagging._stored(tagged, "stage_items"))
    tags = _by_guid(tagging._stored(tagged, tagging.ACTION))
    assert sorted(row["content"][tagging.ACTION]["tag"] for row in tags.values()) == [
        "alpha",
        "beta",
        "gamma",
    ]
    for guid, row in tags.items():
        item = staged[guid]
        assert row.get("lineage") == [*item["lineage"], row["node_id"]]
        assert row.get("parent_target_id") == item["target_id"]
        assert row.get("root_target_id") == item["target_id"]
        assert row.get("metadata") == {"model": "tag_once", "provider": "tool"}
        assert _transitions(row, tagging.ACTION) == ["processed"]
    seen = tagging._stored(tagged, tagging.READER)
    assert len(seen) == len(tags)
    for row in seen:
        tag = tags[row["source_guid"]]
        assert row.get("lineage") == [*tag["lineage"], row["node_id"]]
        assert row.get("root_target_id") == tag["root_target_id"]


def test_a_resumed_run_whose_one_answered_record_fails_counts_what_it_carried(tagged, monkeypatch):
    """Counted apart from what the run answered, the records carried from the checkpoint
    left it with no success and one failure: the action failed as if all three had, and
    its reader was skipped. A run not stopped completes with the one failure."""
    _interrupted_at_gamma(tagged, monkeypatch)
    monkeypatch.setenv(FAIL_AT, "gamma")

    result = tagging._run()

    assert result.exit_code == 0, result.output
    assert tagging._status(tagged) == "completed_with_failures"
    assert tagging._status(tagged, tagging.READER) == "completed"
    items = {
        guid: row["content"]["stage_items"]["item_id"]
        for guid, row in _by_guid(tagging._stored(tagged, "stage_items")).items()
    }
    states = {
        items[row["source_guid"]]: row["_state"] for row in tagging._stored(tagged, tagging.ACTION)
    }
    assert states == {"alpha": "processed", "beta": "processed", "gamma": "failed"}


def test_a_record_carried_from_its_checkpoint_is_stored_as_the_record_answered_after_it(
    online,  # noqa: F811
    provider,  # noqa: F811
):
    """The first run stores pages1.json, answers gamma and is stopped on delta, so the next
    run carries gamma from its checkpoint row and answers delta beside it. The first file's
    rows are carried from the store, already enriched once."""
    provider.stops(at_call=4, raising=KeyboardInterrupt())
    summarizing._run("--fresh")
    assert summarizing._status(online) == "interrupted"
    provider.answers()

    result = summarizing._run()

    assert result.exit_code == 0, result.output
    assert provider.pages() == ["Page delta."]
    rows = summarizing._stored_rows(online)
    assert sorted(_page(row) for row in rows) == summarizing.EVERY_PAGE
    metadata = {"model": summarizing.MODEL, "provider": "agac-provider"}
    for row in rows:
        page = _page(row)
        assert row.get("lineage") == [row["node_id"]], page
        assert row.get("metadata") == metadata, page
        assert _transitions(row, summarizing.ACTION) == ["processed"], page


def test_an_answer_that_failed_to_parse_is_failed_though_the_run_stopped_after_it(
    online,  # noqa: F811
    monkeypatch,
):
    """Collection fails an answer that failed to parse, and its checkpoint row is saved
    before collection, marked answered. Carried as it was, it was stored as processed and
    the action recorded complete; a run not stopped records it failed."""
    answer = AgacClient.call_json
    asked = []

    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        page = summarizing._page_in(prompt_config, context_data)
        asked.append(page)
        if page == "Page delta." and len(asked) == 4:
            raise KeyboardInterrupt()
        if page == "Page gamma.":
            return [{"raw_response": "not json", "_parse_error": PARSE_ERROR}]
        return answer(api_key, agent_config, prompt_config, context_data, schema)

    monkeypatch.setattr(AgacClient, "call_json", staticmethod(call_json))
    summarizing._run("--fresh")
    assert summarizing._status(online) == "interrupted"

    result = summarizing._run()

    assert result.exit_code == 0, result.output
    assert summarizing._status(online) == "completed_with_failures"
    states = {_page(row): row.get("_state") for row in summarizing._stored_rows(online)}
    assert states == {
        "Page alpha.": "processed",
        "Page beta.": "processed",
        "Page gamma.": "failed",
        "Page delta.": "processed",
    }
    backend = summarizing._backend(online)
    try:
        failed = backend.get_disposition(summarizing.ACTION, disposition="failed")
    finally:
        backend.close()
    assert [(row["disposition"], row["reason"]) for row in failed] == [("failed", "parse_error")]
