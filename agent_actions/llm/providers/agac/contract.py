"""Mock answers that meet an action's expectation rules as well as its schema.

The rules are the suite the run resolves for the action, so the mock reads them as the
runner does. Each top-level field a rule names gets a value built to meet that field's
schema and rules. The real runner then checks the whole record; while a rule fails, the
record is built again, up to ``TRIES`` times. What still fails is logged once per action
and field, and the best attempt is returned.
"""

from __future__ import annotations

import copy
import functools
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any

import jsonschema  # type: ignore[import-untyped]

from agent_actions.expectations import registry
from agent_actions.expectations.fields import WILDCARD_SUFFIX
from agent_actions.expectations.runner import run_suite
from agent_actions.expectations.types import Expectation, Suite
from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator
from agent_actions.utils import deep_json
from agent_actions.utils.jsonschema_cache import checked_validator

logger = logging.getLogger(__name__)

TRIES = 20

# A judge's verdict is a side call of its own, answered apart from the record.
_NOT_EVALUATED = frozenset({"llm_judge"})

# Schema keywords a warning names as constraints on a field.
_SCHEMA_CONSTRAINTS = (
    "type",
    "enum",
    "pattern",
    "format",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minItems",
    "maxItems",
)

_reported: set[tuple[str, str]] = set()
_reported_lock = threading.Lock()


def reset_reports() -> None:
    """Forget which unmet constraints were logged, so the next run logs them again."""
    with _reported_lock:
        _reported.clear()


def rules_for(agent_config: dict[str, Any], action: str) -> list[Expectation]:
    """The rules the run checks the action's output against, less those the mock cannot run."""
    expect = agent_config.get("expect")
    if not isinstance(expect, dict):
        return []
    # Imported here: the service imports the pipeline's error types, which a provider
    # module must not load at import time.
    from agent_actions.expectations.service import create_expectation_service_from_config

    try:
        service = create_expectation_service_from_config(
            expect, action_name=action, agent_config=agent_config
        )
    except Exception:
        # The run builds the same service and reports the same error itself.
        logger.debug("The mock read no rules for action '%s'", action, exc_info=True)
        return []
    if service is None:
        return []
    return [
        rule
        for rule in service.suite.expectations
        if rule.type not in _NOT_EVALUATED and registry.get(rule.type) is not None
    ]


def observed_refs(agent_config: dict[str, Any]) -> list[str]:
    """The action's ``context_scope.observe`` references a mock answer may copy from.

    Not a loop's feedback input: it holds the previous iteration, and a copy of it would
    keep every iteration on one value.
    """
    scope = agent_config.get("context_scope")
    entries = scope.get("observe") if isinstance(scope, dict) else None
    if not isinstance(entries, list):
        return []
    feedback = _feedback_namespaces(agent_config)
    refs = [entry.rstrip("?") for entry in entries if isinstance(entry, str)]
    return [ref for ref in refs if ref.partition(".")[0] not in feedback]


def _feedback_namespaces(agent_config: dict[str, Any]) -> set[str]:
    """Each name a loop iteration's action reads the previous iteration under."""
    origin = agent_config.get("_include")
    if not isinstance(origin, dict) or not isinstance(origin.get("loop"), dict):
        return set()
    names = origin.get("names") if isinstance(origin.get("names"), dict) else {}
    keys = [key for key in origin["loop"].get("feedback") or [] if isinstance(key, str)]
    return {*keys, *(str(names[key]) for key in keys if key in names)}


def parse_context(context_data: Any) -> dict[str, Any]:
    """The record's context as the request sends it, keyed by namespace."""
    if isinstance(context_data, dict):
        return context_data
    if isinstance(context_data, str):
        try:
            parsed = deep_json.loads(context_data)
        except (ValueError, RecursionError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


@dataclass
class _FieldPlan:
    rules: list[Expectation] = field(default_factory=list)
    element_rules: list[Expectation] = field(default_factory=list)
    not_null: bool = False


@dataclass
class Contract:
    """What one request's answer must meet: the action's rules and the record's context."""

    action: str
    rules: list[Expectation]
    context: dict[str, Any]
    observe: list[str]

    @classmethod
    def for_request(cls, agent_config: dict[str, Any], action: str, context_data: Any) -> Contract:
        observe = observed_refs(agent_config)
        return cls(
            action=action,
            rules=rules_for(agent_config, action),
            context=parse_context(context_data) if observe else {},
            observe=observe,
        )

    def to_task(self) -> dict[str, Any]:
        """The parts a batch task keeps, without the context it carries already."""
        return {
            "action": self.action,
            "rules": [rule.model_dump(exclude_none=True) for rule in self.rules],
            "observe": self.observe,
        }

    @classmethod
    def from_task(cls, spec: Any, context_data: Any) -> Contract | None:
        if not isinstance(spec, dict):
            return None
        rules = [
            Expectation(**entry)
            for entry in spec.get("rules") or []
            if isinstance(entry, dict) and registry.get(str(entry.get("type"))) is not None
        ]
        return cls(
            action=str(spec.get("action") or "action"),
            rules=rules,
            context=parse_context(context_data),
            observe=[ref for ref in spec.get("observe") or [] if isinstance(ref, str)],
        )

    def generate(self, schema: dict[str, Any], attempt: int) -> Any:
        """A value for *schema* that meets the rules, from the generator's current stream."""
        record = FakeDataGenerator.generate_from_schema(schema, attempt)
        if not isinstance(record, dict):
            return record
        fields = _field_schemas(schema)
        echoes = self._echoes(fields)
        # No record meets these, so no try is spent on them.
        why = {id(rule): _unmeetable(rule, fields) for rule in self.rules}
        rules = [rule for rule in self.rules if why[id(rule)] is None]
        unmet = [
            (_target(rule), f"{rule.resolved_id} ({why[id(rule)]})")
            for rule in self.rules
            if why[id(rule)] is not None
        ]
        if not rules:
            record.update(echoes)
            self._report(unmet, fields)
            return record

        suite = Suite(name=f"{self.action}:mock", expectations=rules)
        plans = self._plans(rules, fields, echoes)
        best: dict[str, Any] = record
        best_failed: tuple[list[tuple[str, str]], list[tuple[str, str]]] | None = None
        for _ in range(TRIES):
            for name, plan in plans.items():
                record[name] = self._value(name, fields.get(name, {}), plan, attempt, echoes)
            refused, failed = self._failures(suite, record, plans, fields)
            if not refused and not failed:
                self._report(unmet, fields)
                return record
            # A record the schema refuses is worse than one that fails only rules.
            rank = (len(refused), len(failed))
            if best_failed is None or rank < (len(best_failed[0]), len(best_failed[1])):
                # Each try replaces a field's value whole, so a shallow copy keeps this one.
                best, best_failed = dict(record), (refused, failed)
            record = FakeDataGenerator.generate_from_schema(schema, attempt)
        self._report([*unmet, *(best_failed[0] + best_failed[1] if best_failed else [])], fields)
        return best

    def _failures(
        self,
        suite: Suite,
        record: dict[str, Any],
        plans: dict[str, _FieldPlan],
        fields: dict[str, dict[str, Any]],
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """``(field, detail)`` for each field its schema refuses, and for each rule it fails."""
        by_id = {rule.resolved_id: rule for rule in self.rules}
        refused = [
            (name, f"schema refuses {record.get(name)!r}")
            for name in plans
            if not _conforms(record.get(name), fields.get(name, {}))
        ]
        failed = [
            (_target(by_id.get(outcome.id)), f"{outcome.id} ({outcome.detail})")
            for outcome in run_suite(suite, record).outcomes
            if not outcome.passed
        ]
        return refused, failed

    def _echoes(self, fields: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Each output field an observe reference names exactly, with that input's value.

        Not a wildcard, which can hold the very field the action rewrites.
        """
        found: dict[str, Any] = {}
        for ref in self.observe:
            namespace, _, name = ref.partition(".")
            values = self.context.get(namespace)
            if name in found or name not in fields or not isinstance(values, dict):
                continue
            if name in values and _conforms(values[name], fields[name]):
                found[name] = values[name]
        return found

    @staticmethod
    def _plans(
        rules: list[Expectation], fields: dict[str, dict[str, Any]], echoes: dict[str, Any]
    ) -> dict[str, _FieldPlan]:
        plans: dict[str, _FieldPlan] = {}
        for rule in rules:
            selector = rule.field
            if isinstance(selector, str):
                if selector.endswith(WILDCARD_SUFFIX):
                    name = selector[: -len(WILDCARD_SUFFIX)]
                    plans.setdefault(name, _FieldPlan()).element_rules.append(rule)
                else:
                    plans.setdefault(selector, _FieldPlan()).rules.append(rule)
            elif rule.type == "no_null_fields":
                excluded = set(rule.params.get("exclude") or ())
                for name in fields:
                    if not name.startswith("_") and name not in excluded:
                        plans.setdefault(name, _FieldPlan()).not_null = True
        for name in echoes:
            plans.setdefault(name, _FieldPlan())
        return plans

    def _value(
        self,
        name: str,
        schema: dict[str, Any],
        plan: _FieldPlan,
        attempt: int,
        echoes: dict[str, Any],
    ) -> Any:
        if name in echoes and _meets(echoes[name], schema, plan):
            return echoes[name]
        best: Any = None
        best_conforms: bool | None = None
        for _ in range(TRIES):
            value = self._candidate(name, schema, plan, attempt)
            if _meets(value, schema, plan):
                return value
            conforms = _conforms(value, schema)
            if best_conforms is None or (conforms and not best_conforms):
                best, best_conforms = value, conforms
        return best

    def _candidate(self, name: str, schema: dict[str, Any], plan: _FieldPlan, attempt: int) -> Any:
        rng = FakeDataGenerator._get_rng()
        rules = plan.rules
        choices = _choices(schema, rules)
        if choices:
            return copy.deepcopy(rng.choice(choices))
        if (
            _primary_type(schema) == "array"
            or plan.element_rules
            or any(rule.type == "item_count" for rule in rules)
        ):
            return self._array(name, schema, plan, attempt)

        value: Any = None
        kind = _primary_type(schema)
        bounds = FakeDataGenerator._length_bounds(schema)
        for rule in rules:
            if rule.type == "matches_regex" and not rule.params.get("negate"):
                value = FakeDataGenerator.from_pattern(str(rule.params["pattern"]), bounds)
                if kind not in (None, "string"):
                    value = _as_type(value, kind, schema, rule)
                if value is not None:
                    break
        words = _word_range(rules)
        if value is None and words is not None:
            value = FakeDataGenerator.sentence_of(rng.randint(*words), rng)
        if value is None:
            value = FakeDataGenerator.generate_from_schema(schema, attempt, field_name=name)
        # A field-name value (an id, a code) carries digits and marks a forbidden
        # pattern often names; plain words carry none.
        if isinstance(value, str) and any(
            _forbids(rule, value) for rule in rules if rule.type == "matches_regex"
        ):
            value = FakeDataGenerator.sentence_of(rng.randint(3, 12), rng)
        if plan.not_null and value in (None, ""):
            value = FakeDataGenerator.sentence_of(3, rng)
        return value

    def _array(self, name: str, schema: dict[str, Any], plan: _FieldPlan, attempt: int) -> list:
        rng = FakeDataGenerator._get_rng()
        low, high = _item_range(schema, plan, attempt)
        items = schema.get("items")
        items_schema = items if isinstance(items, dict) else {}
        element_plan = _FieldPlan(rules=plan.element_rules)
        return [
            self._value(name, items_schema, element_plan, attempt, {})
            if plan.element_rules
            else FakeDataGenerator.generate_from_schema(items_schema, attempt, field_name=name)
            for _ in range(rng.randint(low, high))
        ]

    def _report(self, failed: list[tuple[str, str]], fields: dict[str, dict[str, Any]]) -> None:
        grouped: dict[str, list[str]] = {}
        for target, detail in failed:
            grouped.setdefault(target, []).append(detail)
        for target, details in grouped.items():
            with _reported_lock:
                if (self.action, target) in _reported:
                    continue
                _reported.add((self.action, target))
            logger.warning(
                "agac-provider could not meet every constraint on action '%s' field '%s' "
                "after %d tries; constraints: %s; still failing: %s",
                self.action,
                target,
                TRIES,
                self._describe(target, fields),
                "; ".join(details),
            )

    def _describe(self, target: str, fields: dict[str, dict[str, Any]]) -> str:
        schema = fields.get(target, {})
        parts = [f"{key}={schema[key]!r}" for key in _SCHEMA_CONSTRAINTS if key in schema]
        parts += [
            f"{rule.type}({json.dumps(rule.params, sort_keys=True, default=str)})"
            for rule in self.rules
            if _target(rule) == target
        ]
        return ", ".join(parts) or "none declared"


def _target(rule: Expectation | None) -> str:
    """The field a rule is about, as a warning names it."""
    if rule is None or rule.field is None:
        return "(record)"
    if isinstance(rule.field, list):
        return ", ".join(rule.field)
    return rule.field.removesuffix(WILDCARD_SUFFIX)


def _field_schemas(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        return {
            name: value if isinstance(value, dict) else {} for name, value in properties.items()
        }
    fields = schema.get("fields")
    if isinstance(fields, list):
        return {f["id"]: f for f in fields if isinstance(f, dict) and isinstance(f.get("id"), str)}
    return {}


def _as_type(text: str | None, kind: str, schema: dict[str, Any], rule: Expectation) -> Any:
    """The number *text* spells, when *schema* accepts it and *rule* still passes.

    The check reads ``str(value)``, so a number can meet a pattern. None for any other type.
    """
    if text is None or kind not in ("integer", "number"):
        return None
    try:
        value: int | float = int(text)
    except ValueError:
        if kind == "integer":
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    return value if _conforms(value, schema) and _passes(rule, value) else None


def _primary_type(schema: dict[str, Any]) -> str | None:
    declared = schema.get("type")
    if isinstance(declared, list):
        return next((kind for kind in declared if kind != "null"), None)
    return declared if isinstance(declared, str) else None


def _choices(schema: dict[str, Any], rules: list[Expectation]) -> list[Any] | None:
    """The values both ``enum`` and every ``accepted_values`` allow; None when none limit it."""
    sets: list[list[Any]] = []
    if isinstance(schema.get("enum"), list):
        sets.append(list(schema["enum"]))
    sets += [
        list(rule.params["values"])
        for rule in rules
        if rule.type == "accepted_values" and isinstance(rule.params.get("values"), list | tuple)
    ]
    if not sets:
        return None
    first, *rest = sets
    return [value for value in first if all(value in other for other in rest)]


def _word_range(rules: list[Expectation]) -> tuple[int, int] | None:
    low: int | None = None
    high: int | None = None
    for rule in rules:
        if rule.type != "word_count_between":
            continue
        if rule.params.get("min") is not None:
            low = max(low or 0, int(rule.params["min"]))
        if rule.params.get("max") is not None:
            high = int(rule.params["max"]) if high is None else min(high, int(rule.params["max"]))
    if low is None and high is None:
        return None
    shortest = max(low or 1, 0)
    longest = shortest + 20 if high is None else high
    return (shortest, max(shortest, longest))


def _item_range(schema: dict[str, Any], plan: _FieldPlan, attempt: int) -> tuple[int, int]:
    lows = [int(schema["minItems"])] if isinstance(schema.get("minItems"), int) else []
    highs = [int(schema["maxItems"])] if isinstance(schema.get("maxItems"), int) else []
    for rule in plan.rules:
        if rule.type != "item_count":
            continue
        for key, bucket in (("equals", lows), ("min", lows)):
            if rule.params.get(key) is not None:
                bucket.append(int(rule.params[key]))
        for key in ("equals", "max"):
            if rule.params.get(key) is not None:
                highs.append(int(rule.params[key]))
    low = max([*lows, 1 if plan.not_null else 0])
    usual = FakeDataGenerator.ARRAY_SIZES.get(attempt, FakeDataGenerator.ARRAY_SIZES[3])
    high = min(highs) if highs else max(low, usual)
    return low, max(low, high)


def _conforms(value: Any, schema: dict[str, Any]) -> bool:
    if not schema:
        return True
    try:
        return bool(checked_validator(schema).is_valid(value))
    except jsonschema.exceptions.SchemaError:
        return True
    except RecursionError:
        return False


def _passes(rule: Expectation, value: Any) -> bool:
    etype = registry.get(rule.type)
    if etype is None:
        return True
    params = {key: val for key, val in rule.params.items() if key != "row_condition"}
    try:
        return etype.check(value, params)[0]
    except Exception:
        logger.debug("Rule '%s' raised on a mock value", rule.resolved_id, exc_info=True)
        return False


def _unmeetable(rule: Expectation, fields: dict[str, dict[str, Any]]) -> str | None:
    """Why no record the mock may build meets *rule*; None when one can.

    The mock adds no key the schema does not declare, so a rule on such a field cannot pass.
    """
    if rule.type == "matches_regex" and not _compiles(str(rule.params.get("pattern"))):
        return "Python cannot compile its pattern"
    selectors = [rule.field] if isinstance(rule.field, str) else rule.field or []
    undeclared = [s for s in selectors if s.removesuffix(WILDCARD_SUFFIX) not in fields]
    if undeclared:
        return f"the schema declares no field {', '.join(map(repr, undeclared))}"
    return None


@functools.lru_cache(maxsize=256)
def _compiles(pattern: str) -> bool:
    try:
        re.compile(pattern)
    except (re.error, RecursionError):
        return False
    return True


def _forbids(rule: Expectation, value: str) -> bool:
    """Whether a negated ``matches_regex`` rule refuses *value*."""
    return bool(rule.params.get("negate")) and not _passes(rule, value)


def _meets(value: Any, schema: dict[str, Any], plan: _FieldPlan) -> bool:
    """Whether *value* meets its schema and each rule on its own field.

    A rule with a ``row_condition`` depends on the rest of the record, so the whole-record
    check decides it.
    """
    if not _conforms(value, schema):
        return False
    if plan.not_null and value in (None, "", [], {}):
        return False
    for rule in plan.rules:
        if "row_condition" not in rule.params and not _passes(rule, value):
            return False
    if plan.element_rules:
        if not isinstance(value, list):
            return False
        for rule in plan.element_rules:
            if "row_condition" not in rule.params and not all(_passes(rule, v) for v in value):
                return False
    return True
