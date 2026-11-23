"""A batch answer that does not match the action's schema is warned about, as online warns.

Online checks every answer against the action's schema and logs what is off; only an `expect:`
block enforces it. Batch stored such an answer without a word.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agent_actions.llm.batch.core.batch_context_metadata import BatchContextMetadata
from agent_actions.llm.batch.processing.batch_result_strategy import BatchResultStrategy
from agent_actions.llm.providers import client_base
from agent_actions.llm.providers.batch_base import BatchResult

from .one_answer_both_ways import ROW, VENDORS, action_config, batch, online

SCHEMA = {
    "name": "page_tags",
    "type": "object",
    "properties": {"tag": {"type": "string"}, "score": {"type": "number"}},
    "required": ["tag", "score"],
}
OFF_SCHEMA = {
    "a-missing-field": '{"tag": "a"}',
    "no-declared-field": '{"label": "a"}',
    "prose": "The page is about tides.",
}
# What the check says of these is its own business; batch says the same.
OTHER_ANSWERS = {
    "a-wrong-type": '{"tag": "a", "score": "high"}',
    "one-item-of-a-list": '[{"tag": "a", "score": 1}, {"tag": "b"}]',
    "a-list-of-strings": '["a", "b"]',
}


@pytest.fixture(autouse=True)
def _no_cached_sdk_client(monkeypatch):
    monkeypatch.setattr(client_base, "_client_cache", {})


def _schema_warnings(caplog, run) -> list[str]:
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        run()
    return [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("Schema validation warning")
    ]


def _both(
    caplog, tmp_path, vendor: str, text: str, **settings: Any
) -> tuple[list[str], list[str]]:
    config = action_config(json_mode=True, **settings)
    in_online = _schema_warnings(caplog, lambda: online(vendor, text, config))
    in_batch = _schema_warnings(caplog, lambda: batch(vendor, text, config, tmp_path))
    return in_batch, in_online


@pytest.mark.parametrize("vendor", VENDORS)
@pytest.mark.parametrize("text", OFF_SCHEMA.values(), ids=OFF_SCHEMA.keys())
def test_an_answer_off_the_schema_is_warned_about_in_online_s_words(
    vendor, text, caplog, tmp_path
):
    in_batch, in_online = _both(caplog, tmp_path, vendor, text, schema=SCHEMA)

    assert in_batch == in_online
    assert len(in_batch) == 1
    assert in_batch[0].startswith("Schema validation warning for 'tag_page': ")


@pytest.mark.parametrize("vendor", VENDORS)
@pytest.mark.parametrize("text", OTHER_ANSWERS.values(), ids=OTHER_ANSWERS.keys())
def test_batch_says_of_any_answer_what_online_says(vendor, text, caplog, tmp_path):
    in_batch, in_online = _both(caplog, tmp_path, vendor, text, schema=SCHEMA)

    assert in_batch == in_online


def test_the_answer_is_stored_all_the_same(tmp_path):
    config = action_config(json_mode=True, schema=SCHEMA)

    assert batch("openai", OFF_SCHEMA["a-missing-field"], config, tmp_path) == [{"tag": "a"}]


def test_an_answer_that_matches_is_not_warned_about(caplog, tmp_path):
    text = '{"tag": "a", "score": 1}'

    assert _both(caplog, tmp_path, "openai", text, schema=SCHEMA) == ([], [])


def test_an_action_with_no_schema_is_not_checked(caplog, tmp_path):
    assert _both(caplog, tmp_path, "openai", OFF_SCHEMA["a-missing-field"]) == ([], [])


def test_an_action_with_an_expect_block_is_warned_about_too(caplog, tmp_path):
    expect = {
        "repair": "none",
        "expectations": [{"id": "has_tag", "type": "not_null", "field": "tag"}],
    }

    in_batch, in_online = _both(
        caplog, tmp_path, "openai", OFF_SCHEMA["a-missing-field"], schema=SCHEMA, expect=expect
    )

    assert in_batch == in_online
    assert len(in_batch) == 1


class TestASchemaChosenPerRecord:
    """Online checks an answer against the schema its record's dispatch chose; so does batch."""

    @staticmethod
    def _stored(caplog, root, chosen: str, answer: dict[str, Any]) -> tuple[list[str], list[Any]]:
        (root / "agent_actions.yml").write_text("schema_path: schema\n")
        (root / "schema").mkdir()
        (root / "schema" / "topic_answer.yml").write_text(
            "name: topic_answer\nfields:\n  - id: topic\n    type: string\n"
        )
        config = action_config(
            schema="dispatch_task('pick_schema')",
            schema_options=["topic_answer", "page_label"],
            _project_root=str(root),
        )
        row = dict(ROW)
        BatchContextMetadata.set_output_schema(row, chosen)
        results: list[Any] = []

        def run() -> None:
            results.extend(
                BatchResultStrategy().process(
                    [BatchResult(custom_id="r1", content=answer, success=True)],
                    context_map={"r1": row},
                    agent_config=config,
                )
            )

        return _schema_warnings(caplog, run), results

    def test_an_answer_off_the_chosen_schema_is_warned_about(self, caplog, tmp_path):
        warnings, _ = self._stored(caplog, tmp_path, "topic_answer", {"verdict": "wrong shape"})

        assert len(warnings) == 1
        assert "Expected at least one of ['topic'], got ['verdict']" in warnings[0]

    def test_an_answer_that_matches_the_chosen_schema_is_not(self, caplog, tmp_path):
        warnings, _ = self._stored(caplog, tmp_path, "topic_answer", {"topic": "tides"})

        assert warnings == []

    def test_a_chosen_schema_that_no_longer_loads_costs_the_record_nothing(self, caplog, tmp_path):
        warnings, (result,) = self._stored(caplog, tmp_path, "page_label", {"label": "a"})

        assert warnings == []
        assert [record["content"]["tag_page"] for record in result.data] == [{"label": "a"}]
