"""What a batch against the fake provider answers with.

This provider writes the task and then answers it. The schema it was handed is
in that task, so the record it produces has to carry the fields the schema
declares — an answer carrying none of them fails every rule an author wrote on
a field that was never generated, and no batch verdict can be reached.
"""

import json

import pytest

from agent_actions.llm.providers.agac.batch_client import AgacBatchClient, MockBatchState

# The shape the runtime hands over: an envelope around the JSON Schema, which is
# what batch preparation puts on the provider config.
ENVELOPE = {
    "name": "page_summary",
    "schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}, "exam_density": {"type": "string"}},
        "required": ["summary", "exam_density"],
        "additionalProperties": True,
    },
}
BARE = ENVELOPE["schema"]
FIELDS = {
    "name": "page_summary",
    "fields": [{"id": "summary", "type": "string"}, {"id": "exam_density", "type": "string"}],
}

DECLARED = {"summary", "exam_density"}


@pytest.fixture
def answer():
    """What one submitted task comes back with: its parsed content and usage.

    Goes through `prepare_tasks`, which is how batch preparation reaches a
    provider — the task under test is the one the provider would really be
    answering, not one hand-built in its shape.
    """

    def _answer(schema, prompt="Summarise the page in one sentence.", target_id="p1"):
        client = AgacBatchClient()
        tasks = client.prepare_tasks(
            [
                {
                    "target_id": target_id,
                    "content": {"source": {"page_content": "..."}},
                    "prompt": prompt,
                }
            ],
            {"model_name": "agac-model", "json_mode": True, "compiled_schema": schema},
        )
        AgacBatchClient._batches["b"] = MockBatchState(batch_id="b", status="completed")
        AgacBatchClient._tasks_by_batch["b"] = tasks

        line = client._fetch_raw_results("b").decode("utf-8").strip()
        body = json.loads(line)["response"]["body"]
        return json.loads(body["choices"][0]["message"]["content"]), body["usage"]

    yield _answer
    AgacBatchClient._batches.clear()
    AgacBatchClient._tasks_by_batch.clear()


class TestTheRecordCarriesTheSchemasFields:
    def test_the_envelope_the_runtime_passes_is_answered_by_its_fields(self, answer):
        """The envelope is the only form batch preparation produces. Reaching
        the inner schema is the whole of it: the envelope itself declares no
        fields, so answering it directly yields a bare value and not a record."""
        content, _ = answer(ENVELOPE)

        assert set(content) == DECLARED

    def test_a_schema_passed_without_its_envelope_is_answered_the_same(self, answer):
        content, _ = answer(BARE)

        assert set(content) == DECLARED

    def test_the_fields_form_is_answered_by_its_fields(self, answer):
        """The other form a compiled schema is written in."""
        content, _ = answer(FIELDS)

        assert set(content) == DECLARED

    def test_each_field_is_answered_by_a_value_of_its_declared_type(self, answer):
        content, _ = answer(ENVELOPE)

        assert all(isinstance(value, str) and value for value in content.values())

    def test_two_records_of_one_schema_are_answered_separately(self, answer):
        """Seeded per record, so a batch is not one answer repeated down the file."""
        first, _ = answer(ENVELOPE, target_id="p1")
        AgacBatchClient._batches.clear()
        AgacBatchClient._tasks_by_batch.clear()
        second, _ = answer(ENVELOPE, target_id="p2")

        assert set(first) == set(second) == DECLARED
        assert first != second


class TestATaskWithNoSchemaToAnswerFrom:
    """An action can run without one, and the generic answer is what it gets."""

    def test_it_is_answered_generically(self, answer):
        content, _ = answer(None)

        assert set(content) == {"result", "status"}
        assert content["status"] == "success"


class TestTheReportedUsageFollowsThePrompt:
    """The prompt is in the task beside the schema, and the usage this provider
    reports is counted off it. Reporting a fixed count instead makes every
    record in a run cost the same no matter what was sent."""

    def test_a_longer_prompt_reports_more_prompt_tokens(self, answer):
        _, short = answer(ENVELOPE, prompt="Summarise.")
        AgacBatchClient._batches.clear()
        AgacBatchClient._tasks_by_batch.clear()
        _, long = answer(ENVELOPE, prompt=" ".join(["Summarise the page."] * 40))

        assert long["prompt_tokens"] > short["prompt_tokens"]

    def test_the_total_counts_the_prompt_it_reported(self, answer):
        _, usage = answer(ENVELOPE)

        assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
