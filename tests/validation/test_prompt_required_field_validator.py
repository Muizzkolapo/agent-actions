import pytest

from agent_actions.validation.prompt_required_field_validator import (
    find_unguarded_required_refs,
)


def _schema(*, required: set[str], optional: set[str]) -> dict:
    fields = [{"id": name, "type": "string", "required": True} for name in sorted(required)]
    fields += [{"id": name, "type": "string", "required": False} for name in sorted(optional)]
    return {"fields": fields}


def test_unguarded_ref_to_non_required_field_is_flagged():
    prompts = {"consumer": "Use {{ producer.b }} here."}
    schemas = {"producer": _schema(required={"a"}, optional={"b"})}
    findings = find_unguarded_required_refs(prompts, schemas)
    assert any("producer.b" in f and "consumer" in f for f in findings)


@pytest.mark.parametrize(
    "prompt",
    [
        pytest.param("Use {{ producer.a }} here.", id="required"),
        pytest.param("{% if producer.b is defined %}{{ producer.b }}{% endif %}", id="guarded"),
        pytest.param("{{ mystery.b }}", id="unknown-ns"),
        # An undeclared field is a dependency/observe concern, not a required-ness one.
        pytest.param("{{ producer.z }}", id="absent-field"),
        pytest.param(
            "{% if producer.a is defined %}"
            "{% if producer.b is defined %}{{ producer.b }}{% endif %}"
            "{% endif %}",
            id="nested-if",
        ),
        # Only the top-level field is checked; `.detail` is unverifiable (documented coarseness).
        pytest.param("{{ producer.a.detail }}", id="nested-attr-of-required"),
        pytest.param(
            "{% if producer.a is defined %}a"
            "{% elif producer.b is defined %}{{ producer.b }}{% endif %}",
            id="elif-guards-its-body",
        ),
        pytest.param(
            "{%+ if producer.b is defined %}{{ producer.b }}{%+ endif %}",
            id="whitespace-control-guard",
        ),
    ],
)
def test_safe_ref_is_not_flagged(prompt):
    prompts = {"consumer": prompt}
    schemas = {"producer": _schema(required={"a"}, optional={"b"})}
    assert find_unguarded_required_refs(prompts, schemas) == []


def test_loop_iterable_over_optional_field_is_flagged():
    # A `{{ }}`-only regex would extract `c.key` and miss the loop iterable;
    # AST extraction surfaces `producer.items`, the real crash point.
    prompts = {"consumer": "{% for c in producer.items %}{{ c.key }}{% endfor %}"}
    schemas = {"producer": _schema(required=set(), optional={"items"})}
    findings = find_unguarded_required_refs(prompts, schemas)
    assert any("producer.items" in f for f in findings)


def test_second_workflow_shape_is_flagged():
    # A second, differently-named shape raises the cost of input-matching.
    prompts = {"writer": "Draft using {{ analyzer.summary }}."}
    schemas = {"analyzer": _schema(required={"score"}, optional={"summary"})}
    findings = find_unguarded_required_refs(prompts, schemas)
    assert any("analyzer.summary" in f and "writer" in f for f in findings)


# ── Guard analysis must be field-aware, not block-aware ──────────────


@pytest.mark.parametrize(
    "prompt",
    [
        # Guarded once, then used unconditionally: the unconditional use is the risk.
        pytest.param(
            "{% if producer.b is defined %}{{ producer.b }}{% endif %} {{ producer.b }}",
            id="partial-guard",
        ),
        pytest.param(
            "{% if producer.a is defined %}{{ producer.b }}{% endif %}",
            id="guard-on-other-field",
        ),
        # The else branch runs precisely when b is absent.
        pytest.param(
            "{% if producer.b is defined %}ok{% else %}{{ producer.b }}{% endif %}",
            id="else-branch",
        ),
        pytest.param('{{ producer["b"] }}', id="subscript"),
        # A commented-out `{% if %}` is not a real guard.
        pytest.param(
            "{# {% if producer.b is defined %} #}{{ producer.b }}", id="comment-hidden-if"
        ),
    ],
)
def test_unguarded_optional_ref_is_flagged(prompt):
    prompts = {"consumer": prompt}
    schemas = {"producer": _schema(required={"a"}, optional={"b"})}
    findings = find_unguarded_required_refs(prompts, schemas)
    assert any("producer.b" in f for f in findings)


def test_self_namespace_ref_is_not_flagged():
    # An action referencing its own output is a different error class.
    prompts = {"producer": "Emit {{ producer.b }}."}
    schemas = {"producer": _schema(required={"a"}, optional={"b"})}
    assert find_unguarded_required_refs(prompts, schemas) == []


def test_one_field_referenced_many_ways_warns_once():
    prompts = {"consumer": '{{ producer.b }} {{ producer.b["x"] }} {{ producer.b.detail }}'}
    schemas = {"producer": _schema(required={"a"}, optional={"b"})}
    findings = find_unguarded_required_refs(prompts, schemas)
    assert len(findings) == 1


def test_empty_prompts_or_schemas_short_circuit():
    schemas = {"producer": _schema(required=set(), optional={"b"})}
    assert find_unguarded_required_refs({}, schemas) == []
    assert find_unguarded_required_refs({"consumer": "{{ producer.b }}"}, {}) == []


def test_unmarked_field_ref_is_flagged_optional_by_default():
    # An unmarked producer field is optional by default (not guaranteed), so an
    # unguarded ref to it is a risk and must be flagged.
    prompts = {"consumer": "Use {{ producer.b }} here."}
    schemas = {"producer": {"fields": [{"id": "a"}, {"id": "b"}]}}
    findings = find_unguarded_required_refs(prompts, schemas)
    assert any("producer.b" in f for f in findings)


def test_unmarked_field_ref_not_flagged_under_required_by_default_flag():
    # required_by_default: true makes unmarked fields guaranteed, so an unguarded
    # ref to one is safe and must not be flagged.
    prompts = {"consumer": "Use {{ producer.b }} here."}
    schemas = {"producer": {"required_by_default": True, "fields": [{"id": "a"}, {"id": "b"}]}}
    assert find_unguarded_required_refs(prompts, schemas) == []


def test_optional_true_field_ref_is_flagged():
    # optional: true is an optional field, so an unguarded ref to it is a risk
    # and must be flagged (even under the required_by_default flag).
    prompts = {"consumer": "Use {{ producer.b }} here."}
    schemas = {
        "producer": {
            "required_by_default": True,
            "fields": [{"id": "a"}, {"id": "b", "optional": True}],
        }
    }
    findings = find_unguarded_required_refs(prompts, schemas)
    assert any("producer.b" in f for f in findings)
