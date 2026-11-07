"""A FILE tool is handed the seed its action declares.

A RECORD tool and a guard load the declared seed; the FILE scope pass did not, so an
action observing `seed.rules` refused every record. The seed is loaded per record from
the action's seed folders and reaches the tool's input under its bare key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_actions.prompt.context.scope_application import apply_context_scope_for_records
from agent_actions.record.tracking import TrackedItem
from agent_actions.workflow.pipeline_file_mode import (
    extract_tool_input,
    reconcile_outputs,
    seed_payload_keys,
)

RULES = {"threshold": 7}


def _project(tmp_path: Path, files: dict[str, object]) -> dict:
    """A project with one workflow whose seed folder holds *files*; the action config."""
    project = tmp_path / "project"
    workflow = project / "agent_workflow" / "wf"
    (workflow / "agent_config").mkdir(parents=True)
    (project / "agent_actions.yml").write_text("schema_path: schema\n")
    config = workflow / "agent_config" / "wf.yml"
    config.write_text('version: "0.1.0"\n')
    seeds = workflow / "seed_data"
    seeds.mkdir()
    for name, content in files.items():
        (seeds / name).write_text(json.dumps(content))
    return {"name": "probe", "workflow_config_path": str(config)}


def _payloads(records: list[dict], scope: dict, agent_config: dict | None, **kwargs) -> list[dict]:
    enriched, skipped = apply_context_scope_for_records(
        records=records,
        context_scope=scope,
        action_name="probe",
        agent_config=agent_config,
        **kwargs,
    )
    assert skipped == []
    return [extract_tool_input(r, scope) for r in enriched]


class TestTheSeedReachesTheTool:
    def test_a_declared_seed_is_handed_under_its_bare_key(self, tmp_path):
        scope = {"observe": ["a.x", "seed.rules"], "seed": {"rules": "$file:rules.json"}}
        agent_config = _project(tmp_path, {"rules.json": RULES})

        (payload,) = _payloads(
            [{"source_guid": "g1", "content": {"a": {"x": 1}}}], scope, agent_config
        )

        assert payload == {"x": 1, "rules": RULES}

    def test_a_seed_selected_by_a_source_field_is_each_records_own(self, tmp_path):
        scope = {
            "observe": ["seed.syllabus"],
            "seed": {
                "syllabus": {
                    "select_by": "source.lang",
                    "files": {"en": "$file:en.json", "fr": "$file:fr.json"},
                }
            },
        }
        agent_config = _project(
            tmp_path, {"en.json": {"name": "english"}, "fr.json": {"name": "french"}}
        )
        records = [
            {"source_guid": "g1", "content": {"source": {"lang": "en"}}},
            {"source_guid": "g2", "content": {"source": {"lang": "fr"}}},
        ]

        assert _payloads(records, scope, agent_config) == [
            {"syllabus": {"name": "english"}},
            {"syllabus": {"name": "french"}},
        ]

    def test_a_seed_selected_by_a_source_field_reads_the_pooled_source(self, tmp_path):
        """The record carries no source namespace of its own; the pool resolves it."""
        scope = {
            "observe": ["a.x", "seed.syllabus"],
            "seed": {
                "syllabus": {
                    "select_by": "source.lang",
                    "files": {"en": "$file:en.json", "fr": "$file:fr.json"},
                }
            },
        }
        agent_config = _project(
            tmp_path, {"en.json": {"name": "english"}, "fr.json": {"name": "french"}}
        )
        records = [{"source_guid": "g2", "content": {"a": {"x": 2}}}]
        pool = [{"source_guid": "g2", "content": {"source": {"lang": "fr"}}}]

        (payload,) = _payloads(records, scope, agent_config, source_data=pool)

        assert payload == {"x": 2, "syllabus": {"name": "french"}}

    def test_the_seed_is_not_written_into_the_record_handed_back(self, tmp_path):
        """The enriched copy carries the seed for the payload; the caller's record does not."""
        scope = {"observe": ["a.x", "seed.rules"], "seed": {"rules": "$file:rules.json"}}
        agent_config = _project(tmp_path, {"rules.json": RULES})
        record = {"source_guid": "g1", "content": {"a": {"x": 1}}}

        apply_context_scope_for_records(
            records=[record], context_scope=scope, action_name="probe", agent_config=agent_config
        )

        assert record == {"source_guid": "g1", "content": {"a": {"x": 1}}}


class TestWhatIsRefused:
    def test_a_declared_seed_without_the_action_config_is_a_caller_error(self):
        scope = {"observe": ["seed.rules"], "seed": {"rules": "$file:rules.json"}}

        with pytest.raises(ValueError, match="'probe' declares context_scope.seed"):
            apply_context_scope_for_records(
                records=[{"source_guid": "g1", "content": {"a": {"x": 1}}}],
                context_scope=scope,
                action_name="probe",
            )

    def test_without_a_declared_seed_the_action_config_is_not_needed(self):
        scope = {"observe": ["a.x"]}

        (payload,) = _payloads([{"source_guid": "g1", "content": {"a": {"x": 1}}}], scope, None)

        assert payload == {"x": 1}

    def test_a_record_lacking_an_observed_field_is_still_refused_with_the_seed_loaded(
        self, tmp_path
    ):
        scope = {"observe": ["a.x", "seed.rules"], "seed": {"rules": "$file:rules.json"}}
        agent_config = _project(tmp_path, {"rules.json": RULES})

        enriched, skipped = apply_context_scope_for_records(
            records=[{"source_guid": "g1", "content": {"a": {"y": 1}}}],
            context_scope=scope,
            action_name="probe",
            agent_config=agent_config,
        )

        assert enriched == []
        assert [s["source_guid"] for s in skipped] == ["g1"]
        assert "a.x" in skipped[0]["detail"]


class TestTheSeedStaysOutOfStoredRows:
    def test_the_seeds_payload_keys_are_planned_as_the_payload_is(self, tmp_path):
        scope = {"observe": ["a.x", "seed.rules"], "seed": {"rules": "$file:rules.json"}}
        agent_config = _project(tmp_path, {"rules.json": RULES})

        (enriched,), _ = apply_context_scope_for_records(
            records=[{"source_guid": "g1", "content": {"a": {"x": 1}}}],
            context_scope=scope,
            action_name="probe",
            agent_config=agent_config,
        )

        assert seed_payload_keys(enriched, scope) == frozenset({"rules"})
        assert seed_payload_keys({"content": {"a": {"x": 1}}}, scope) == frozenset()

    def test_an_item_a_tool_returns_is_stored_without_what_the_seed_supplied(self):
        inputs = [{"source_guid": "g1", "content": {"a": {"x": 1}, "seed": {"rules": RULES}}}]
        returned = [TrackedItem({"x": 1, "rules": RULES, "verdict": "ok"}, source_index=0)]

        rows, _ = reconcile_outputs(returned, "probe", inputs, drop_keys=frozenset({"rules"}))

        (row,) = rows
        assert row["content"]["probe"] == {"x": 1, "verdict": "ok"}

    def test_a_row_the_tool_built_itself_keeps_what_the_tool_put_in_it(self):
        from agent_actions.utils.udf_management.registry import FileUDFResult

        inputs = [{"source_guid": "g1", "content": {"a": {"x": 1}, "seed": {"rules": RULES}}}]
        built = FileUDFResult([{"source_index": 0, "data": {"rules": "kept on purpose"}}])

        rows, _ = reconcile_outputs(built, "probe", inputs, drop_keys=frozenset({"rules"}))

        assert rows[0]["content"]["probe"] == {"rules": "kept on purpose"}

    def test_a_seed_picked_by_no_field_is_the_same_object_for_every_record(self, tmp_path):
        """Loaded once per file: both records' payloads hold the one loaded seed."""
        scope = {"observe": ["seed.rules"], "seed": {"rules": "$file:rules.json"}}
        agent_config = _project(tmp_path, {"rules.json": RULES})

        first, second = _payloads(
            [{"source_guid": "g1", "content": {}}, {"source_guid": "g2", "content": {}}],
            scope,
            agent_config,
        )

        assert first == second == {"rules": RULES}
