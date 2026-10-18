"""Pre-flight prints each distinct static-analysis finding once (1536)."""

from agent_actions.services.preflight_service import static_warning_lines
from agent_actions.validation.static_analyzer.errors import FieldLocation, StaticTypeWarning


def _warning(config_field: str, hint: str | None = "Add a schema.") -> StaticTypeWarning:
    return StaticTypeWarning(
        message="Cannot validate field 'x' - action 'p' has no schema",
        location=FieldLocation(agent_name="c", config_field=config_field, raw_reference="p.x"),
        referenced_agent="p",
        referenced_field="x",
        hint=hint,
    )


def test_the_same_finding_from_two_places_is_one_line():
    lines = static_warning_lines([_warning("prompt"), _warning("context_scope.observe")])

    assert lines == ["c: Cannot validate field 'x' - action 'p' has no schema Add a schema."]


def test_a_finding_without_a_hint_is_its_message():
    assert static_warning_lines([_warning("prompt", hint=None)]) == [
        "c: Cannot validate field 'x' - action 'p' has no schema"
    ]
