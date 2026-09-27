"""A version-merge tool's output field must not silently take a namespace's place.

A ``kind: tool`` action with ``version_consumption`` has its output spread flat over
record content rather than nested under its own name, so its field names share the
top-level key space with the framework's namespaces and with every upstream action's.

The output still wins at runtime — a guard reading such a field has to keep finding it —
so the collision is reported there and refused where the field name is declared.
"""

from typing import Any

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.llm.batch.processing.batch_result_strategy import (
    BatchProcessingContext,
    BatchResultStrategy,
)
from agent_actions.llm.batch.processing.reconciler import BatchResultReconciler
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.output.response.expander import ActionExpander
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


def _expand(schema: Any, *, kind: str = "tool", version_consumption: bool = True) -> dict[str, Any]:
    """Expand a one-action workflow, as loading a config does."""
    action: dict[str, Any] = {"name": "aggregate", "kind": kind, "schema": schema}
    if kind == "tool":
        action["impl"] = "aggregate"
    if version_consumption:
        action["version_consumption"] = {"source": "voter", "pattern": "merge"}
    config = {
        "name": "wf",
        "defaults": {"model_vendor": "openai", "model_name": "gpt-4o", "api_key": "sk-test"},
        "actions": [action],
    }
    return ActionExpander.expand_actions_to_agents(config)["wf"][0]


@pytest.fixture
def processor() -> BatchResultStrategy:
    return BatchResultStrategy()


class TestTheReplacementIsReported:
    def test_file_mode_reports_it(self, caplog):
        with caplog.at_level("WARNING"):
            _build_record("aggregate", {"source": "oops"}, _matched_row(), True)
        assert "source" in caplog.text
        assert "aggregate" in caplog.text

    def test_batch_reports_it(self, processor, caplog):
        with caplog.at_level("WARNING"):
            _batch_content(processor, {"source": "oops"})
        assert "source" in caplog.text
        assert "aggregate" in caplog.text

    def test_a_framework_namespace_is_named_as_one(self, caplog):
        with caplog.at_level("WARNING"):
            _build_record("aggregate", {"source": "oops"}, _matched_row(), True)
        assert "framework namespace" in caplog.text

    def test_an_upstream_action_namespace_is_reported_too(self, caplog):
        with caplog.at_level("WARNING"):
            _build_record("aggregate", {"voter_1": "chosen"}, _matched_row(), True)
        assert "voter_1" in caplog.text

    def test_but_not_as_a_framework_namespace(self, caplog):
        with caplog.at_level("WARNING"):
            _build_record("aggregate", {"voter_1": "chosen"}, _matched_row(), True)
        assert "framework namespace" not in caplog.text

    def test_the_shared_helper_reports_it(self, caplog):
        with caplog.at_level("WARNING"):
            apply_version_merge(_tool_config(), {"source": "oops"}, _matched_row()["content"])
        assert "source" in caplog.text


class TestTheOutputStillWins:
    """A guard reads these fields, so taking one away would filter the record instead."""

    def test_file_mode_keeps_the_output_field(self):
        content = _build_record("aggregate", {"source": "oops"}, _matched_row(), True)["content"]
        assert content["source"] == "oops"

    def test_batch_keeps_the_output_field(self, processor):
        assert _batch_content(processor, {"source": "oops"})["source"] == "oops"

    def test_an_upstream_namespace_is_still_replaced(self):
        content = _build_record("aggregate", {"voter_1": "chosen"}, _matched_row(), True)["content"]
        assert content["voter_1"] == "chosen"

    def test_untouched_namespaces_are_kept(self):
        content = _build_record("aggregate", {"source": "oops"}, _matched_row(), True)["content"]
        assert content["voter_1"] == {"vote": "keep"}


class TestAnOutputFieldTakingNoNamespaceIsSilent:
    def test_the_intended_case_passes_through(self):
        content = _build_record("aggregate", {"winner": "voter_1"}, _matched_row(), True)["content"]
        assert content["winner"] == "voter_1"
        assert content["source"] == SOURCE_DOCUMENT
        assert content["voter_1"] == {"vote": "keep"}

    def test_and_is_not_reported(self, caplog):
        with caplog.at_level("WARNING"):
            _build_record("aggregate", {"winner": "voter_1"}, _matched_row(), True)
        assert "winner" not in caplog.text


class TestTheNameIsRefusedWhereItIsDeclared:
    def test_a_shorthand_schema_naming_source_is_refused(self):
        with pytest.raises(ConfigValidationError, match="framework namespace"):
            _expand({"winner": "string", "source": "string"})

    def test_a_rendered_schema_naming_source_is_refused(self):
        """Rendering inlines a schema named by file into this shape before expansion."""
        with pytest.raises(ConfigValidationError, match="framework namespace"):
            _expand({"name": "InlineSchema", "fields": [{"id": "source", "type": "string"}]})

    def test_a_json_schema_naming_source_is_refused(self):
        with pytest.raises(ConfigValidationError, match="framework namespace"):
            _expand({"type": "object", "properties": {"source": {"type": "string"}}})

    @pytest.mark.parametrize("namespace", sorted(RUNTIME_BUS_NAMESPACES))
    def test_every_framework_namespace_is_refused(self, namespace):
        with pytest.raises(ConfigValidationError, match="framework namespace"):
            _expand({namespace: "string"})

    def test_the_error_names_the_field_and_the_action(self):
        with pytest.raises(ConfigValidationError) as caught:
            _expand({"source": "string"})
        assert "source" in str(caught.value)
        assert "aggregate" in str(caught.value)

    def test_a_schema_naming_no_namespace_is_accepted(self):
        agent = _expand({"winner": "string", "count": "integer"})
        assert agent["version_consumption_config"]["source"] == "voter"

    def test_an_llm_version_consumer_is_unaffected_because_it_nests(self):
        agent = _expand({"source": "string"}, kind="llm")
        assert agent["version_consumption_config"]["source"] == "voter"

    def test_a_tool_that_consumes_no_versions_is_unaffected(self):
        agent = _expand({"source": "string"}, version_consumption=False)
        assert agent["version_consumption_config"] is None


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

    def test_a_scalar_source_is_what_the_refusal_prevents(self):
        """Why the name is refused: content's copy is the resolver's only fallback."""
        clobbered = {"source_guid": "src_001", "content": {"source": "oops"}}
        assert resolve_source_content(clobbered, None, None, "downstream") is None

    def test_the_pool_still_answers_first_when_it_can_place_the_record(self):
        """So the loss lands on records the pool cannot place, not on every record."""
        pool = [{"source_guid": "src_001", "content": {"source": dict(SOURCE_DOCUMENT)}}]
        clobbered = {"source_guid": "src_001", "content": {"source": "oops"}}
        assert resolve_source_content(clobbered, "src_001", pool, "downstream") is pool[0]
