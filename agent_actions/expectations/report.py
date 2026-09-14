"""Aggregate the verdicts a run stored into per-action, per-rule counts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_actions.utils.constants import VERDICT_KEY


@dataclass(frozen=True)
class RuleTally:
    """How one rule fared across every record it ran on."""

    id: str
    type: str
    severity: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0

    @property
    def checked(self) -> int:
        return self.passed + self.failed

    @property
    def pass_rate(self) -> float | None:
        """None, not zero: a rule that never ran has no rate to report."""
        return self.passed / self.checked if self.checked else None


@dataclass(frozen=True)
class ActionTally:
    """How one action's records fared, and which of its rules drove it."""

    action: str
    records: int
    records_passed: int
    rules: tuple[RuleTally, ...]

    @property
    def pass_rate(self) -> float | None:
        return self.records_passed / self.records if self.records else None


def tally_action(action: str, records: list[dict[str, Any]]) -> ActionTally | None:
    """One action's verdicts, or None when no record carried one.

    None is not an empty tally: an action that never ran expectations and one
    whose every rule passed are different answers, and reporting the first as
    zeroes would invent a denominator.
    """
    verdicts = [
        record[VERDICT_KEY] for record in records if isinstance(record.get(VERDICT_KEY), dict)
    ]
    if not verdicts:
        return None

    counts: dict[str, dict[str, Any]] = {}
    for verdict in verdicts:
        for outcome in verdict.get("outcomes") or []:
            tally = counts.setdefault(
                outcome["id"],
                {
                    "type": outcome.get("type", ""),
                    "severity": outcome.get("severity", "error"),
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                },
            )
            # A skipped rule was not evaluated, so it is neither a pass nor a
            # fail; counting it either way would move a pass rate it never ran in.
            if outcome.get("skipped"):
                tally["skipped"] += 1
            elif outcome.get("passed"):
                tally["passed"] += 1
            else:
                tally["failed"] += 1

    rules = tuple(
        sorted(
            (
                RuleTally(
                    id=rule_id,
                    type=data["type"],
                    severity=data["severity"],
                    passed=data["passed"],
                    failed=data["failed"],
                    skipped=data["skipped"],
                )
                for rule_id, data in counts.items()
            ),
            key=lambda rule: (-rule.failed, rule.id),
        )
    )

    return ActionTally(
        action=action,
        records=len(verdicts),
        records_passed=sum(1 for v in verdicts if v.get("overall_pass")),
        rules=rules,
    )
