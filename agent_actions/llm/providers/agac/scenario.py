"""The scenario a sandbox run follows: which mock answers fail, break a rule or wait.

A scenario is ``sandbox.yml`` at the project root, a preset (``happy``, ``chaos``) or a
file named by ``--scenario``. It is read and checked once, before any call. Every decision
is a hash of the seed, the action, the record, the attempt and the decision's name, so a
parallel run makes the decisions a serial run makes.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from agent_actions.errors import ConfigurationError
from agent_actions.utils import deep_json

SCENARIO_FILE = "sandbox.yml"
ERROR_KINDS = (
    "rate_limit",
    "timeout",
    "server_error",
    "refusal",
    "truncated",
    "empty",
    "invalid_json",
)
COUNTS = ("errors", "rules_broken", "dropped")


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
    actions: dict[str, ActionRules] = Field(default_factory=dict)
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


@dataclass(frozen=True)
class CallRules:
    """What one call of an action follows, after the precedence is applied."""

    latency_ms: tuple[int, int]
    pass_rate: float
    errors: Errors
    break_rules: BreakRules
    pin: dict[str, Any]


class Scenario:
    def __init__(self, name: str, data: _File, llm_actions: list[str]) -> None:
        self.name = name
        self.seed = data.seed
        self.batch = data.batch
        self._data = data
        self._keys = {action: _key_for(action, data.actions) for action in llm_actions}
        self._counts = dict.fromkeys(COUNTS, 0)
        self._lock = threading.Lock()

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
        key = self._keys.get(action) or _key_for(action, self._data.actions)
        layers: list[ActionRules] = []
        if key in self._data.actions:
            layers.append(self._data.actions[key])
        record = self._record_rules(key, context)
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

    def _record_rules(self, key: str, context: Any) -> RecordActionRules | None:
        """The first ``records`` entry whose match the context meets and that names *key*."""
        if not self._data.records:
            return None
        parsed = _context(context)
        for entry in self._data.records:
            if key in entry.actions and all(
                _lookup(parsed, path) == (True, value) for path, value in entry.match.items()
            ):
                return entry.actions[key]
        return None

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
        return self._key_for(action) in self.batch.fail or action in self.batch.fail

    def _key_for(self, action: str) -> str:
        return self._keys.get(action) or action

    def count(self, kind: str, amount: int = 1) -> None:
        with self._lock:
            self._counts[kind] += amount

    def summary(self) -> str:
        with self._lock:
            counts = dict(self._counts)
        return (
            f"SANDBOX scenario {self.name}: {counts['errors']} errors, "
            f"{counts['rules_broken']} rules broken, {counts['dropped']} batch results dropped"
        )


def load(source: str | None, project_root: Path, llm_actions: list[str]) -> Scenario:
    """The scenario *source* names, checked against the workflow's LLM actions.

    None is ``sandbox.yml`` at *project_root* when it exists, else ``happy``.
    """
    if source in PRESETS:
        name, label, raw = source, f"preset {source}", PRESETS[source]
    else:
        if source is None:
            path = project_root / SCENARIO_FILE
            if not path.is_file():
                return load("happy", project_root, llm_actions)
            name = SCENARIO_FILE
        else:
            path = Path(source)
            if not path.is_file():
                raise ConfigurationError(
                    f"--scenario: no scenario file {source}. Give happy, chaos or the path "
                    "of a scenario file."
                )
            name = source
        label = name
        raw = _read(path, label)
    try:
        data = _File.model_validate(raw)
    except ValidationError as e:
        raise _refusal(label, [_problem(error) for error in e.errors()]) from None
    problems = _unknown_names(data, llm_actions)
    if problems:
        raise _refusal(label, problems)
    return Scenario(name, data, llm_actions)


def _read(path: Path, label: str) -> Any:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ConfigurationError(f"Scenario {label} cannot be read: {e}") from None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _refusal(label, [f"(file): must be a mapping, got {type(raw).__name__}"])
    return raw


def _problem(error: Any) -> str:
    key = ".".join(str(part) for part in error["loc"]) or "(file)"
    if error["type"] == "extra_forbidden":
        return f"{key}: unknown key"
    return f"{key}: {str(error['msg']).removeprefix('Value error, ')}"


def _refusal(label: str, problems: list[str]) -> ConfigurationError:
    lines = "\n".join(f"  - {problem}" for problem in problems)
    return ConfigurationError(
        f"Scenario {label} has {len(problems)} problem(s); nothing was called:\n{lines}"
    )


def _unknown_names(data: _File, llm_actions: list[str]) -> list[str]:
    from agent_actions.expectations import registry

    known = registry.known_types()

    def unknown(name: str) -> bool:
        return name not in llm_actions and not any(
            action.startswith(f"{name}_") and action[len(name) + 1 :].isdigit()
            for action in llm_actions
        )

    actions = ", ".join(llm_actions) or "none"
    why = f"names no LLM action of the workflow (its LLM actions: {actions})"
    problems: list[str] = []
    named: list[tuple[str, BreakRules | None]] = [("defaults", data.defaults.break_rules)]
    for name, entry in data.actions.items():
        if unknown(name):
            problems.append(f"actions.{name}: {why}")
        named.append((f"actions.{name}", entry.break_rules))
    for index, record in enumerate(data.records):
        for name, by_record in record.actions.items():
            if unknown(name):
                problems.append(f"records.{index}.actions.{name}: {why}")
            named.append((f"records.{index}.actions.{name}", by_record.break_rules))
    problems += [f"batch.fail: '{name}' {why}" for name in data.batch.fail if unknown(name)]
    for where, broken in named:
        if broken is None or broken.rules == "all":
            continue
        problems += [
            f"{where}.break_rules.rules: unknown rule type '{rule}'"
            for rule in broken.rules
            if rule not in known
        ]
    return problems


def _key_for(action: str, actions: dict[str, Any]) -> str:
    """The ``actions`` key an action answers to: its own name, or its version group's."""
    if action in actions:
        return action
    base, _, suffix = action.rpartition("_")
    return base if base and suffix.isdigit() and base in actions else action


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
