"""The scenario a sandbox run follows: which mock answers fail, break a rule or wait.

A scenario is ``sandbox.yml`` at the project root, a preset (``happy``, ``chaos``) or a
file named by ``--scenario``. It is read and checked once, before any call. Every decision
is a hash of the seed, the action, the record's input, the attempt and the decision's name,
so a parallel run makes the decisions a serial run makes, and two runs over the same input
make the same decisions. It also names the tool actions whose code does not run (``stub``).
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

import yaml
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, ValidationError

from agent_actions.errors import ConfigurationError
from agent_actions.utils import deep_json

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

SCENARIO_FILE = "sandbox.yml"
# A workflow_metadata key of the sandbox store: one record's attempts at one action.
ATTEMPTS_KEY_PREFIX = "sandbox_attempts:"
ERROR_KINDS = (
    "rate_limit",
    "timeout",
    "server_error",
    "refusal",
    "truncated",
    "empty",
    "invalid_json",
)
# "calls" is counted to know that the mock answered; the summary line does not show it.
COUNTS = ("errors", "rules_broken", "dropped", "calls")
# The keys that describe a model call, which a tool action does not make.
MODEL_CALL_KEYS = ("latency_ms", "judge", "errors", "break_rules", "error")


def _rate(value: float) -> float:
    if not 0 <= value <= 1:
        raise ValueError(f"must be between 0 and 1, got {value:g}")
    return value


def _heal(value: int | None) -> int | None:
    if value is not None and value < 2:
        raise ValueError(f"must be at least 2, got {value}: attempt 1 is the first call")
    return value


def _kind(value: str) -> str:
    if value not in ERROR_KINDS:
        raise ValueError(f"unknown error kind '{value}'; the kinds are {', '.join(ERROR_KINDS)}")
    return value


def _latency(value: int | list[int] | None) -> int | list[int] | None:
    if isinstance(value, list):
        if len(value) != 2:
            raise ValueError("must be a number of milliseconds or [min, max]")
        low, high = value
        if low > high:
            raise ValueError(f"min {low} is above max {high}")
        if low < 0:
            raise ValueError(f"must not be negative, got {low}")
    elif value is not None and value < 0:
        raise ValueError(f"must not be negative, got {value}")
    return value


Rate = Annotated[float, AfterValidator(_rate)]
Heal = Annotated[int | None, AfterValidator(_heal)]
Kind = Annotated[str, AfterValidator(_kind)]
Latency = Annotated[int | list[int] | None, AfterValidator(_latency)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Errors(_Strict):
    rate: Rate = 0.0
    kinds: list[Kind] = Field(default_factory=lambda: ["rate_limit"], min_length=1)
    heal_on_attempt: Heal = None


class BreakRules(_Strict):
    rules: Literal["all"] | list[str] = "all"
    rate: Rate = 0.0
    heal_on_attempt: Heal = None


class Judge(_Strict):
    pass_rate: Rate = 1.0


class Defaults(_Strict):
    latency_ms: Latency = 0
    judge: Judge = Field(default_factory=Judge)
    errors: Errors = Field(default_factory=Errors)
    break_rules: BreakRules = Field(default_factory=BreakRules)


class ActionRules(_Strict):
    latency_ms: Latency = None
    judge: Judge | None = None
    errors: Errors | None = None
    break_rules: BreakRules | None = None
    pin: dict[str, Any] | None = None


class NamedActionRules(ActionRules):
    # A tool action only: its code does not run, and the mock builds its output.
    stub: StrictBool | None = None


class RecordActionRules(ActionRules):
    # Fails every attempt with this kind: ``errors`` with rate 1 and this one kind.
    error: Kind | None = None


class RecordRule(_Strict):
    match: dict[str, Any] = Field(min_length=1)
    actions: dict[str, RecordActionRules]


class BatchRules(_Strict):
    polls_until_complete: int = Field(default=0, ge=0)
    complete_after_seconds: float = Field(default=0.0, ge=0)
    drop_rate: Rate = 0.0
    fail: list[str] = Field(default_factory=list)


class _File(_Strict):
    seed: int = 0
    defaults: Defaults = Field(default_factory=Defaults)
    actions: dict[str, NamedActionRules] = Field(default_factory=dict)
    records: list[RecordRule] = Field(default_factory=list)
    batch: BatchRules = Field(default_factory=BatchRules)


PRESETS: dict[str, dict[str, Any]] = {
    "happy": {},
    "chaos": {
        "seed": 0,
        "defaults": {
            "errors": {
                "rate": 0.1,
                "kinds": ["rate_limit", "timeout", "truncated", "empty"],
                "heal_on_attempt": 2,
            },
            "break_rules": {"rules": "all", "rate": 0.2, "heal_on_attempt": 2},
            "judge": {"pass_rate": 0.7},
        },
        "batch": {"polls_until_complete": 1, "drop_rate": 0.1},
    },
}


def attempts_key(action: str, record: str) -> str:
    return f"{ATTEMPTS_KEY_PREFIX}{action}:{record}"


class Tally:
    """What the scenario did over one command, across every load of the workflow."""

    def __init__(self) -> None:
        self._counts = dict.fromkeys(COUNTS, 0)
        self._lock = threading.Lock()

    def add(self, kind: str, amount: int = 1) -> None:
        with self._lock:
            self._counts[kind] += amount

    def clear(self) -> None:
        with self._lock:
            self._counts = dict.fromkeys(COUNTS, 0)

    @property
    def calls(self) -> int:
        """The record attempts the mock counted: online calls and batch submissions."""
        with self._lock:
            return self._counts["calls"]

    def line(self, name: str) -> str:
        with self._lock:
            counts = dict(self._counts)
        return (
            f"SANDBOX scenario {name}: {counts['errors']} errors, "
            f"{counts['rules_broken']} rules broken, {counts['dropped']} batch results dropped"
        )


@dataclass(frozen=True)
class Tool:
    """A tool action of the workflow, as a scenario is checked against it."""

    group: str | None = None
    # Why the mock cannot build this tool's output; None when it can.
    cannot_stub: str | None = None


@dataclass(frozen=True)
class CallRules:
    """What one call of an action follows, after the precedence is applied."""

    latency_ms: tuple[int, int]
    pass_rate: float
    errors: Errors
    break_rules: BreakRules
    pin: dict[str, Any]


class Scenario:
    def __init__(
        self,
        name: str,
        data: _File,
        groups: Mapping[str, str | None],
        tally: Tally | None = None,
        tools: Mapping[str, Tool] | None = None,
    ) -> None:
        self.name = name
        self.seed = data.seed
        self.batch = data.batch
        self._data = data
        self._tools = dict(tools or {})
        self._groups = {**groups, **{tool: spec.group for tool, spec in self._tools.items()}}
        self._tally = tally or Tally()
        self._store: StorageBackend | None = None
        self._attempts: dict[str, int] = {}
        self._lock = threading.Lock()

    def attach(self, store: StorageBackend) -> None:
        """Count attempts in *store*, where a later process continues the count."""
        self._store = store

    def next_attempt(self, action: str, record: str) -> int:
        """This call's attempt for *record* at *action*, from 1.

        In the sandbox store once one is attached, so a repair round, a retry, a later
        ``--wait`` pass and ``agac retry`` continue the count. The store adds one under
        its write lock, so two processes cannot both read the old count.
        """
        self._tally.add("calls")
        key = attempts_key(action, record)
        if self._store is not None:
            return self._store.increment_metadata(key)
        with self._lock:
            self._attempts[key] = self._attempts.get(key, 0) + 1
            return self._attempts[key]

    def _named(self, names: Collection[str], action: str) -> str | None:
        """The entry of *names* for *action*: its own name, else its version group's."""
        if action in names:
            return action
        group = self._groups.get(action)
        return group if group is not None and group in names else None

    def stubs(self, action: str) -> bool:
        """Whether the mock builds the output of tool *action* and its code does not run."""
        key = self._named(self._data.actions, action)
        return key is not None and bool(self._data.actions[key].stub)

    def stubbed(self) -> list[str]:
        return [tool for tool in self._tools if self.stubs(tool)]

    def rules_for(self, action: str, context: Any) -> CallRules:
        """A matched record's rules over the action's over the defaults, each key whole."""
        defaults = self._data.defaults
        merged: dict[str, Any] = {
            "latency_ms": defaults.latency_ms,
            "judge": defaults.judge,
            "errors": defaults.errors,
            "break_rules": defaults.break_rules,
            "pin": {},
        }
        layers: list[ActionRules] = []
        key = self._named(self._data.actions, action)
        if key is not None:
            layers.append(self._data.actions[key])
        record = self._record_rules(action, context)
        if record is not None:
            layers.append(record)
        for layer in layers:
            for name in merged:
                value = getattr(layer, name)
                if value is not None:
                    merged[name] = value
            if isinstance(layer, RecordActionRules) and layer.error is not None:
                merged["errors"] = Errors(rate=1.0, kinds=[layer.error])
        latency = merged["latency_ms"]
        low, high = latency if isinstance(latency, list) else (latency, latency)
        return CallRules(
            latency_ms=(low, high),
            pass_rate=merged["judge"].pass_rate,
            errors=merged["errors"],
            break_rules=merged["break_rules"],
            pin=dict(merged["pin"]),
        )

    def _record_rules(self, action: str, context: Any) -> RecordActionRules | None:
        """The first ``records`` entry that names *action* and whose match *context* meets.

        *context* is the record's whole input: each field the action observes, whether
        its prompt prints the field or not.
        """
        if not self._data.records:
            return None
        parsed = _context(context)
        for entry in self._data.records:
            key = self._named(entry.actions, action)
            if key is not None and all(
                _lookup(parsed, path) == (True, value) for path, value in entry.match.items()
            ):
                return entry.actions[key]
        return None

    @staticmethod
    def record_key(record_input: Any, fallback: str) -> str:
        """The record as the decisions name it: a hash of its input, alike in every run.

        A record's ``source_guid`` below an expansion or a FILE tool is new in each run,
        so it is only the *fallback*, for a call that carries no input.
        """
        if record_input is None:
            return fallback
        text = (
            record_input
            if isinstance(record_input, str)
            else deep_json.dumps(record_input, sort_keys=True, default=str, ensure_ascii=False)
        )
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def chance(self, action: str, record: str, attempt: int, decision: str) -> float:
        """A number in [0, 1) that only the seed and these four values decide."""
        text = "\x1f".join((str(self.seed), action, record, str(attempt), decision))
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    def _pick(self, action: str, record: str, attempt: int, decision: str, count: int) -> int:
        return min(int(self.chance(action, record, attempt, decision) * count), count - 1)

    def error_for(self, action: str, record: str, attempt: int, rules: CallRules) -> str | None:
        """The error kind this call fails with, or None."""
        errors = rules.errors
        if errors.heal_on_attempt is not None and attempt >= errors.heal_on_attempt:
            return None
        if self.chance(action, record, attempt, "error") >= errors.rate:
            return None
        return errors.kinds[self._pick(action, record, attempt, "error_kind", len(errors.kinds))]

    def breaks(self, action: str, record: str, attempt: int, rules: CallRules) -> bool:
        broken = rules.break_rules
        if broken.heal_on_attempt is not None and attempt >= broken.heal_on_attempt:
            return False
        return self.chance(action, record, attempt, "break_rules") < broken.rate

    def pick_rule(self, action: str, record: str, attempt: int, count: int) -> int:
        """Which of *count* rules ``rules: all`` breaks on this call."""
        return self._pick(action, record, attempt, "break_rule", count)

    def latency_ms(self, action: str, record: str, attempt: int, rules: CallRules) -> int:
        low, high = rules.latency_ms
        return low + self._pick(action, record, attempt, "latency", high - low + 1)

    def judge_passes(self, action: str, prompt: str) -> bool:
        """Whether the judge's answer to *prompt* passes; the prompt names the record judged."""
        record = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return self.chance(action, record, 0, "judge") < self.rules_for(action, {}).pass_rate

    def drops(self, action: str, record: str, attempt: int) -> bool:
        """Whether a batch leaves this record's result out; only its first submission is."""
        return attempt == 1 and self.chance(action, record, attempt, "drop") < self.batch.drop_rate

    def fails_batch(self, action: str) -> bool:
        return self._named(self.batch.fail, action) is not None

    def count(self, kind: str, amount: int = 1) -> None:
        self._tally.add(kind, amount)

    def summary(self) -> str:
        return self._tally.line(self.name)

    def check_outputs(self, declared: Mapping[str, Collection[str] | None]) -> None:
        """Refuse a ``pin`` or ``break_rules`` that an action's output cannot take.

        *declared* holds the output schema fields of each LLM action and each stubbed
        tool action, or None for an action with no JSON output schema (text mode). An
        action whose fields are not known before it runs is not in it.
        """
        problems: list[str] = []
        for where, name, rules in self._entries():
            keys = [key for key in ("pin", "break_rules") if getattr(rules, key) is not None]
            if not keys:
                continue
            for action in self._actions_named(name):
                if action not in declared:
                    continue
                fields = declared[action]
                if fields is None:
                    problems.append(
                        f"{where}: action '{action}' has no JSON output schema (text mode), "
                        f"so it takes no {' or '.join(keys)}"
                    )
                    continue
                problems += [
                    f"{where}.pin.{field}: the output schema of action '{action}' declares no "
                    f"field '{field}' (its fields: {', '.join(sorted(fields)) or 'none'})"
                    for field in rules.pin or {}
                    if field not in fields
                ]
        if problems:
            label = f"preset {self.name}" if self.name in PRESETS else self.name
            raise _refusal(label, list(dict.fromkeys(problems)))

    def _entries(self) -> list[tuple[str, str, ActionRules]]:
        """Each entry that names an action: its key, the name and its rules."""
        entries: list[tuple[str, str, ActionRules]] = [
            (f"actions.{name}", name, rules) for name, rules in self._data.actions.items()
        ]
        entries += [
            (f"records.{index}.actions.{name}", name, rules)
            for index, record in enumerate(self._data.records)
            for name, rules in record.actions.items()
        ]
        return entries

    def _actions_named(self, name: str) -> list[str]:
        """The actions an entry named *name* applies to: that one, or each version."""
        return [action for action, group in self._groups.items() if name in (action, group)]

    def tool_problems(self) -> list[str]:
        """Each key a tool action cannot take, and each ``stub`` the run cannot follow."""
        problems: list[str] = []
        for where, name, rules in self._entries():
            named = self._actions_named(name)
            tools = [action for action in named if action in self._tools]
            stub = getattr(rules, "stub", None)
            if not tools:
                if stub is not None and named:
                    problems.append(
                        f"{where}.stub: '{name}' is not a tool action; the mock answers an "
                        "LLM action already, and stub is for a tool action"
                    )
                continue
            problems += [
                f"{where}.{key}: '{name}' is a tool action, and {key} describes a model call"
                for key in MODEL_CALL_KEYS
                if getattr(rules, key, None) is not None
            ]
            if stub:
                problems += [
                    f"{where}.stub: tool action '{tool}' {self._tools[tool].cannot_stub}"
                    for tool in tools
                    if self._tools[tool].cannot_stub is not None
                ]
            if rules.pin is not None:
                problems += [
                    f"{where}.pin: tool action '{tool}' is not stubbed, so its own code "
                    "writes its output; set stub: true for it under actions"
                    for tool in tools
                    if not self.stubs(tool)
                ]
        problems += [
            f"batch.fail: '{name}' is a tool action, and a tool action has no batch"
            for name in self._data.batch.fail
            if any(action in self._tools for action in self._actions_named(name))
        ]
        return problems


def load(
    source: str | None,
    project_root: Path,
    groups: Mapping[str, str | None],
    tally: Tally | None = None,
    tools: Mapping[str, Tool] | None = None,
) -> Scenario:
    """The scenario *source* names, checked against the workflow's LLM and tool actions.

    None is ``sandbox.yml`` at *project_root* when it exists, else ``happy``. *groups*
    maps each LLM action to the base name of its version group, or to None.
    """
    if source in PRESETS:
        name, label, raw = source, f"preset {source}", PRESETS[source]
    else:
        if source is None:
            path = project_root / SCENARIO_FILE
            if not path.is_file():
                return load("happy", project_root, groups, tally, tools)
            name = SCENARIO_FILE
        else:
            path = Path(source)
            if not path.is_file():
                raise ConfigurationError(
                    f"--scenario: no scenario file {source}.",
                    context={
                        "config_file": source,
                        "hint": "Give happy, chaos or the path of a scenario file.",
                    },
                )
            name = source
        label = name
        raw = _read(path, label)
    try:
        data = _File.model_validate(raw)
    except ValidationError as e:
        raise _refusal(label, [_problem(error) for error in e.errors()]) from None
    scenario = Scenario(name, data, groups, tally, tools)
    problems = _unknown_names(data, groups, tools or {}) + scenario.tool_problems()
    if problems:
        raise _refusal(label, problems)
    return scenario


_HINT = (
    "Correct each key named above in the scenario file, or give another scenario with "
    "--scenario happy|chaos|PATH"
)


def _read(path: Path, label: str) -> Any:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ConfigurationError(
            f"Scenario {label} cannot be read: {e}",
            context={"config_file": label, "hint": _HINT},
        ) from None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _refusal(label, [f"(file): must be a mapping, got {type(raw).__name__}"])
    return raw


def _problem(error: Any) -> str:
    key = ".".join(str(part) for part in error["loc"]) or "(file)"
    if error["type"] == "extra_forbidden":
        if error["loc"][-1] == "stub":
            return f"{key}: stub is set for one tool action, under actions.<tool action>"
        return f"{key}: unknown key"
    return f"{key}: {str(error['msg']).removeprefix('Value error, ')}"


def _refusal(label: str, problems: list[str]) -> ConfigurationError:
    lines = "\n".join(f"  - {problem}" for problem in problems)
    return ConfigurationError(
        f"Scenario {label} has {len(problems)} problem(s); nothing was called:\n{lines}",
        context={"config_file": label, "hint": _HINT},
    )


def _unknown_names(
    data: _File, groups: Mapping[str, str | None], tools: Mapping[str, Tool]
) -> list[str]:
    from agent_actions.expectations import registry

    known = registry.known_types()
    every = {**groups, **{tool: spec.group for tool, spec in tools.items()}}
    names = set(every) | {group for group in every.values() if group is not None}
    why = (
        "names no LLM action or tool action of the workflow "
        f"(its LLM actions: {', '.join(groups) or 'none'}; "
        f"its tool actions: {', '.join(tools) or 'none'})"
    )
    problems: list[str] = []
    named: list[tuple[str, BreakRules | None]] = [("defaults", data.defaults.break_rules)]
    for name, entry in data.actions.items():
        if name not in names:
            problems.append(f"actions.{name}: {why}")
        named.append((f"actions.{name}", entry.break_rules))
    for index, record in enumerate(data.records):
        for name, by_record in record.actions.items():
            if name not in names:
                problems.append(f"records.{index}.actions.{name}: {why}")
            if by_record.judge is not None:
                problems.append(
                    f"records.{index}.actions.{name}.judge: a judge call answers no record, so "
                    f"a record entry cannot set it; set judge under actions.{name} or defaults"
                )
            named.append((f"records.{index}.actions.{name}", by_record.break_rules))
    problems += [f"batch.fail: '{name}' {why}" for name in data.batch.fail if name not in names]
    for where, broken in named:
        if broken is None or broken.rules == "all":
            continue
        problems += [
            f"{where}.break_rules.rules: unknown rule type '{rule}'"
            for rule in broken.rules
            if rule not in known
        ]
    return problems


def _context(context: Any) -> Any:
    if isinstance(context, str):
        try:
            return deep_json.loads(context)
        except (ValueError, RecursionError):
            return {}
    return context


def _lookup(context: Any, path: str) -> tuple[bool, Any]:
    value = context
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return False, None
        value = value[part]
    return True, value
