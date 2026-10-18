"""A reference through `action`, `prompt` or `schema` is reported as written and refused
(1512).

No record carries those names: an upstream action's fields are read under the action's
own name, and the three are reserved words. The extractor used to read
`action.producer.field` as `producer.field`, and the type checker let `prompt.x` and
`schema.x` through as built-in namespaces, so pre-flight passed a workflow whose every
record then failed to render, or whose guard filtered every record.
"""

from __future__ import annotations

import pytest

from agent_actions.validation.preflight.guard_validation import validate_guard_conditions
from agent_actions.validation.static_analyzer import ReferenceExtractor
from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)


def _refs(config: dict) -> set[tuple[str, str, str]]:
    refs = ReferenceExtractor().extract_from_agent({"name": "consumer", **config})
    return {(r.source_agent, r.field_path, r.location) for r in refs}


class TestTheExtractorReportsTheNameAsWritten:
    @pytest.mark.parametrize(
        ("prompt", "expected"),
        [
            ("{{ action.producer.severity }}", ("action", "producer.severity")),
            ("{{ action.producer.meta.score }}", ("action", "producer.meta.score")),
            ("{{ action.producer.items() | list }}", ("action", "producer")),
            ("{{ action.producer.get('severity') }}", ("action", "producer")),
            ("{{ action.items() | list }}", ("action", "*")),
            ("{{ action }}", ("action", "")),
            ("{{ action['producer'] }}", ("action", "")),
            ("{{ action | tojson }}", ("action", "")),
            ("{{ prompt.text }}", ("prompt", "text")),
            ("{{ schema }}", ("schema", "")),
        ],
    )
    def test_in_a_prompt(self, prompt, expected):
        assert {(s, f) for s, f, _ in _refs({"prompt": prompt})} == {expected}

    def test_in_a_guard(self):
        refs = _refs({"guard": "action.producer.severity == 'high'"})

        assert refs == {("action", "producer.severity", "guard")}

    def test_in_a_dict_guard(self):
        refs = _refs({"guard": {"field": "action.producer.severity", "value": 1}})

        assert refs == {("action", "producer.severity", "guard.field")}

    def test_in_context_scope(self):
        refs = _refs({"context_scope": {"observe": ["action.producer.severity"]}})

        assert refs == {("action", "producer.severity", "context_scope.observe")}

    def test_a_version_param_of_that_name_is_on_the_record(self):
        """`versions: {param: schema}` promotes `schema` to a top-level name."""
        config = {
            "prompt": "Round {{ schema }} of {{ action }}",
            "_version_context": {"i": 1, "idx": 0, "length": 2, "schema": 1},
        }

        assert {(s, f) for s, f, _ in _refs(config)} == {("action", "")}

    @pytest.mark.parametrize(
        "prompt",
        [
            "{% for action in producer.rows %}{{ action.name }}{% endfor %}",
            "{% set action = producer.row %}{{ action.name }}{{ action }}",
        ],
    )
    def test_a_name_the_template_sets_itself_is_not_a_reference(self, prompt):
        assert {(s, f) for s, f, _ in _refs({"prompt": prompt})} == {
            ("producer", "rows" if "for" in prompt else "row")
        }


def _workflow(**consumer: object) -> dict:
    return {
        "name": "wf",
        "actions": [
            {
                "name": "producer",
                "prompt": "p",
                "schema": {"severity": "string"},
                "context_scope": {"observe": ["source.x"]},
            },
            {
                "name": "consumer",
                "dependencies": ["producer"],
                "prompt": "{{ producer.severity }}",
                "context_scope": {"observe": ["producer.severity"]},
                **consumer,
            },
        ],
    }


def _errors(config: dict) -> list[str]:
    result = WorkflowStaticAnalyzer(config).analyze()
    return [error.format_message() for error in result.errors]


class TestTheStaticAnalyzerRefusesIt:
    @pytest.mark.parametrize(
        ("consumer", "written", "suggested"),
        [
            (
                {"prompt": "{{ action.producer.severity }}"},
                "{{ action.producer.severity }}",
                "{{ producer.severity }}",
            ),
            (
                {"prompt": "{% for k in action.producer.keys() %}{{ k }}{% endfor %}"},
                "{{ action.producer.keys() }}",
                "{{ producer.keys() }}",
            ),
            (
                {"context_scope": {"observe": ["action.producer.severity"]}},
                "action.producer.severity",
                "producer.severity",
            ),
        ],
    )
    def test_a_read_through_action_names_the_spelling_to_write(self, consumer, written, suggested):
        errors = [e for e in _errors(_workflow(**consumer)) if "'action'" in e]

        assert len(errors) == 1, _errors(_workflow(**consumer))
        assert "there is no 'action' namespace" in errors[0]
        assert written in errors[0]
        assert f"Write '{suggested}'" in errors[0]

    @pytest.mark.parametrize("prompt", ["{{ action }}", "{{ action.items() | list }}"])
    def test_a_read_of_action_whole_is_refused(self, prompt):
        errors = _errors(_workflow(prompt="{{ producer.severity }} " + prompt))

        assert any("there is no 'action' namespace" in e for e in errors), errors

    def test_the_docs_placeholder_copied_as_written_names_the_action_to_put_there(self):
        """`{{ action.field }}` is how the docs once wrote `{{ <action name>.field }}`."""
        errors = _errors(_workflow(prompt="{{ producer.severity }} {{ action.severity }}"))

        assert len(errors) == 1, errors
        assert "there is no 'action' namespace" in errors[0]
        assert "Write '{{ <action name>.severity }}'" in errors[0]

    @pytest.mark.parametrize("name", ["prompt", "schema"])
    def test_a_read_through_another_reserved_name_is_refused(self, name):
        errors = _errors(_workflow(prompt="{{ producer.severity }} {{ " + name + ".text }}"))

        assert any(f"'{name}' is a reserved name, not a namespace" in e for e in errors), errors

    def test_the_documented_spelling_is_not_refused(self):
        assert _errors(_workflow()) == []


def _guard_errors(clause: str) -> list[str]:
    configs = {
        "producer": {"name": "producer"},
        "consumer": {
            "name": "consumer",
            "dependencies": ["producer"],
            "guard": {"clause": clause, "scope": "item"},
        },
    }
    return validate_guard_conditions(configs)


class TestTheGuardCheckRefusesIt:
    """A guard clause is checked after expansion, where the extractor does not read it."""

    @pytest.mark.parametrize(
        ("clause", "written", "suggested"),
        [
            ("action.producer.severity == 'high'", "action.producer.severity", "producer.severity"),
            (
                "producer.ok == true and LENGTH(action.producer.tags) > 0",
                "action.producer.tags",
                "producer.tags",
            ),
            ("action.severity == 'high'", "action.severity", "<action name>.severity"),
        ],
    )
    def test_a_read_through_action_names_the_spelling_to_write(self, clause, written, suggested):
        errors = _guard_errors(clause)

        assert len(errors) == 1, errors
        assert "there is no 'action' namespace" in errors[0]
        assert f"'{written}'" in errors[0]
        assert f"Write '{suggested}'" in errors[0]

    @pytest.mark.parametrize("name", ["prompt", "schema"])
    def test_a_read_through_another_reserved_name_is_refused(self, name):
        errors = _guard_errors(f"{name}.text == 'x'")

        assert len(errors) == 1, errors
        assert f"'{name}' is a reserved name, not a namespace" in errors[0]

    def test_the_documented_spelling_is_not_refused(self):
        assert _guard_errors("producer.severity == 'high'") == []
