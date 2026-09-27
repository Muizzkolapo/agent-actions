"""A version-merge tool's output field must not silently take a namespace's place.

A ``kind: tool`` action with ``version_consumption`` has its output spread flat over
record content rather than nested under its own name, so its field names share the
top-level key space with the framework's namespaces and with every upstream action's.

Driven through both paths that build that content in production — the FILE-mode
reconciler and the batch result strategy — because the flat spread is written out
separately in each.
"""

from typing import Any

import pytest

from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchProcessingContext,
    BatchResultStrategy,
)
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.record_helpers import apply_version_merge
from agent_actions.processing.source_resolution import resolve_source_content
from agent_actions.utils.constants import RUNTIME_BUS_NAMESPACES
from agent_actions.workflow.pipeline_file_mode import _build_record

SOURCE_DOCUMENT = {"url": "http://example.com", "page_content": "the document"}


def _matched_row() -> dict[str, Any]:
    """An input row carrying a source document beside one version's output."""
    return {
        "source_guid": "src_001",
        "content": {
            "source": dict(SOURCE_DOCUMENT),
            "voter_1": {"vote": "keep"},
        },
    }


def _tool_config() -> dict[str, Any]:
    return {
        "action_name": "aggregate",
        "kind": "tool",
        "version_consumption_config": {"source": "voter_1", "pattern": "merge"},
    }


def _batch_content(processor: BatchResultStrategy, output: dict[str, Any]) -> dict[str, Any]:
    """Content the batch path writes for a version-merge tool returning *output*."""
    custom_id = "rec_001"
    row = _matched_row()
    ctx = BatchProcessingContext(
        batch_results=[],
        context_map={custom_id: row},
        output_directory="/tmp/output",
        agent_config=_tool_config(),
    )
    ctx.reconciler = BatchResultReconciler(context_map={custom_id: row})
    result = processor._process_successful_result(
        ctx, BatchResult(custom_id=custom_id, content=output, success=True), custom_id
    )
    assert len(result.data) == 1
    return result.data[0]["content"]


@pytest.fixture
def processor() -> BatchResultStrategy:
    return BatchResultStrategy()


class TestTheSourceDocumentSurvivesAnOutputFieldOfTheSameName:
    def test_file_mode_keeps_the_source_namespace(self):
        content = _build_record("aggregate", {"source": "oops"}, _matched_row(), True)["content"]
        assert content["source"] == SOURCE_DOCUMENT

    def test_batch_keeps_the_source_namespace(self, processor):
        assert _batch_content(processor, {"source": "oops"})["source"] == SOURCE_DOCUMENT

    def test_a_dict_valued_output_field_does_not_become_the_source_document(self):
        """A dict passes the resolver's shape test, so it would be published as the document."""
        content = _build_record(
            "aggregate", {"source": {"url": "FROM_THE_TOOL"}}, _matched_row(), True
        )["content"]
        assert content["source"] == SOURCE_DOCUMENT

    def test_the_record_still_resolves_to_its_source(self):
        record = _build_record("aggregate", {"source": "oops"}, _matched_row(), True)
        assert resolve_source_content(record, None, None, "downstream") is not None

    def test_every_bus_namespace_is_protected_not_only_source(self):
        row = _matched_row()
        row["content"]["workflow"] = {"name": "quiz"}
        row["content"]["seed"] = {"rows": [1]}
        content = _build_record(
            "aggregate", {"workflow": "clobbered", "seed": "clobbered"}, row, True
        )["content"]
        assert content["workflow"] == {"name": "quiz"}
        assert content["seed"] == {"rows": [1]}

    def test_the_dropped_field_is_reported_with_its_key_and_action(self, caplog):
        with caplog.at_level("WARNING"):
            _build_record("aggregate", {"source": "oops"}, _matched_row(), True)
        assert "source" in caplog.text
        assert "aggregate" in caplog.text


class TestAnUpstreamActionNamespaceIsReplacedButReported:
    """A fan-in may intend to publish the version it chose, so this stays allowed."""

    def test_the_replacement_still_happens(self):
        content = _build_record("aggregate", {"voter_1": "chosen"}, _matched_row(), True)["content"]
        assert content["voter_1"] == "chosen"

    def test_but_it_is_reported(self, caplog):
        with caplog.at_level("WARNING"):
            _build_record("aggregate", {"voter_1": "chosen"}, _matched_row(), True)
        assert "voter_1" in caplog.text


class TestAnOutputFieldTakingNoNamespaceIsUntouched:
    def test_the_intended_case_passes_through(self):
        content = _build_record("aggregate", {"winner": "voter_1"}, _matched_row(), True)["content"]
        assert content["winner"] == "voter_1"
        assert content["source"] == SOURCE_DOCUMENT
        assert content["voter_1"] == {"vote": "keep"}

    def test_and_is_not_reported(self, caplog):
        with caplog.at_level("WARNING"):
            _build_record("aggregate", {"winner": "voter_1"}, _matched_row(), True)
        assert "winner" not in caplog.text


class TestTheSharedHelperCarriesTheSameRule:
    def test_apply_version_merge_keeps_the_source_namespace(self):
        content = apply_version_merge(_tool_config(), {"source": "oops"}, _matched_row()["content"])
        assert content["source"] == SOURCE_DOCUMENT

    def test_an_llm_action_is_unaffected_because_it_nests(self):
        config = {**_tool_config(), "kind": "llm"}
        content = apply_version_merge(config, {"source": "oops"}, _matched_row()["content"])
        assert content["source"] == SOURCE_DOCUMENT
        assert content["aggregate"] == {"source": "oops"}


class TestTheShapesTheseTestsRelyOn:
    """Premise guards: each asserts a fixture is exercising what the test names."""

    def test_the_path_under_test_really_is_the_flat_spread(self):
        content = _build_record("aggregate", {"winner": "voter_1"}, _matched_row(), True)["content"]
        assert "winner" in content, "not the flat-spread branch — output was nested"
        assert "aggregate" not in content

    def test_a_namespaced_action_would_not_collide_at_all(self):
        content = _build_record("aggregate", {"source": "oops"}, _matched_row(), False)["content"]
        assert content["aggregate"] == {"source": "oops"}
        assert content["source"] == SOURCE_DOCUMENT

    def test_the_constant_the_rule_reads_holds_the_framework_namespaces(self):
        assert {"source", "version", "workflow", "seed"} <= set(RUNTIME_BUS_NAMESPACES)

    def test_a_scalar_source_really_does_cost_the_document(self):
        """Why a bus namespace is kept rather than reported and overwritten."""
        clobbered = {"source_guid": "src_001", "content": {"source": "oops"}}
        assert resolve_source_content(clobbered, None, None, "downstream") is None
