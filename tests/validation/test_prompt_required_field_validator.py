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


def test_required_field_ref_is_not_flagged():
    prompts = {"consumer": "Use {{ producer.a }} here."}
    schemas = {"producer": _schema(required={"a"}, optional={"b"})}
    assert find_unguarded_required_refs(prompts, schemas) == []


def test_guarded_ref_is_not_flagged():
    prompts = {"consumer": "{% if producer.b is defined %}{{ producer.b }}{% endif %}"}
    schemas = {"producer": _schema(required={"a"}, optional={"b"})}
    assert find_unguarded_required_refs(prompts, schemas) == []


def test_ref_to_unknown_namespace_is_ignored():
    prompts = {"consumer": "{{ mystery.b }}"}
    schemas = {"producer": _schema(required={"a"}, optional={"b"})}
    assert find_unguarded_required_refs(prompts, schemas) == []


def test_ref_to_field_absent_from_schema_is_ignored():
    # `producer.z` is not declared at all — a dependency/observe concern,
    # not a required-ness one. Not flagged here.
    prompts = {"consumer": "{{ producer.z }}"}
    schemas = {"producer": _schema(required={"a"}, optional={"b"})}
    assert find_unguarded_required_refs(prompts, schemas) == []


def test_nested_if_guard_does_not_crash_and_suppresses():
    prompts = {
        "consumer": (
            "{% if producer.a is defined %}"
            "{% if producer.b is defined %}{{ producer.b }}{% endif %}"
            "{% endif %}"
        )
    }
    schemas = {"producer": _schema(required={"a"}, optional={"b"})}
    assert find_unguarded_required_refs(prompts, schemas) == []


def test_loop_iterable_over_optional_field_is_flagged():
    # A `{{ }}`-only regex would extract `c.key` and miss the loop iterable;
    # AST extraction surfaces `producer.items`, the real crash point.
    prompts = {"consumer": "{% for c in producer.items %}{{ c.key }}{% endfor %}"}
    schemas = {"producer": _schema(required=set(), optional={"items"})}
    findings = find_unguarded_required_refs(prompts, schemas)
    assert any("producer.items" in f for f in findings)


def test_partially_guarded_ref_is_flagged_on_unconditional_use():
    # `b` appears once guarded and once unconditionally — the unconditional
    # use is the risk and must be flagged.
    prompts = {
        "consumer": "{% if producer.b is defined %}{{ producer.b }}{% endif %} {{ producer.b }}"
    }
    schemas = {"producer": _schema(required={"a"}, optional={"b"})}
    findings = find_unguarded_required_refs(prompts, schemas)
    assert any("producer.b" in f for f in findings)


def test_nested_attr_ref_checks_top_level_field_only():
    # `producer.a.detail` — `a` is required, so the ref is not flagged even
    # though the `.detail` sub-attribute is unverifiable (documented coarseness).
    prompts = {"consumer": "{{ producer.a.detail }}"}
    schemas = {"producer": _schema(required={"a"}, optional={"b"})}
    assert find_unguarded_required_refs(prompts, schemas) == []


def test_second_workflow_shape_is_flagged():
    # A second, differently-named shape raises the cost of input-matching.
    prompts = {"writer": "Draft using {{ analyzer.summary }}."}
    schemas = {"analyzer": _schema(required={"score"}, optional={"summary"})}
    findings = find_unguarded_required_refs(prompts, schemas)
    assert any("analyzer.summary" in f and "writer" in f for f in findings)
