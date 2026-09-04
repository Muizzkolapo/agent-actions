"""Models for expectations, suites, and their results."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Severity = Literal["error", "warn", "info"]

_RULE_KEYS = frozenset({"id", "type", "field", "params", "severity", "hint"})

_RENAMED_SEVERITIES = {"fail": "error"}


class Expectation(BaseModel):
    """One rule in a suite.

    Type-specific arguments live under ``params:``. Every other key belongs to
    the framework, so a mistyped rule key is refused by name here rather than
    travelling on as an argument for the registry to reject later.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, description="Stable identifier; derived when omitted")
    type: str = Field(..., description="Registered expectation type name")
    field: str | list[str] = Field(..., description="Field selector this rule is tested against")
    params: dict[str, Any] = Field(
        default_factory=dict, description="Type-specific arguments for the registered check"
    )
    severity: Severity = Field(default="error", description="error, warn, or info")
    hint: str | None = Field(default=None, description="Remedy text; used only by repair")

    @model_validator(mode="before")
    @classmethod
    def _refuse_superseded_spellings(cls, data: Any) -> Any:
        """Name the replacement for a shape that used to be legal."""
        if not isinstance(data, dict):
            return data
        stray = sorted(str(key) for key in data if key not in _RULE_KEYS)
        if stray:
            raise ValueError(
                f"type-specific arguments belong under params:; move {', '.join(stray)} there"
            )
        severity = data.get("severity")
        if isinstance(severity, str) and severity in _RENAMED_SEVERITIES:
            raise ValueError(
                f"severity '{severity}' is now '{_RENAMED_SEVERITIES[severity]}'; "
                f"the levels are error, warn and info"
            )
        return data

    def definition_hash(self) -> str:
        """Stable digest of what this rule tests, ignoring its name."""
        payload = self.model_dump(exclude={"id"}, exclude_none=True)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    @property
    def resolved_id(self) -> str:
        """The authored id, or one derived from type and definition so it survives reordering."""
        return self.id if self.id is not None else f"{self.type}_{self.definition_hash()}"


class Outcome(BaseModel):
    """Result of one expectation against one record."""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    severity: Severity
    passed: bool
    detail: str = ""
    definition_hash: str


class SuiteResult(BaseModel):
    """Every outcome from running one suite over one record."""

    model_config = ConfigDict(extra="forbid")

    suite_name: str
    outcomes: list[Outcome] = Field(default_factory=list)

    @property
    def failed(self) -> list[Outcome]:
        return [o for o in self.outcomes if not o.passed]

    @property
    def overall_pass(self) -> bool:
        """True unless an error-severity expectation failed; warn and info never block."""
        return not any(o.severity == "error" and not o.passed for o in self.outcomes)

    def to_record_dict(self) -> dict[str, Any]:
        """The verdict as attached to a record under the ``expect`` key."""
        return {
            "overall_pass": self.overall_pass,
            "failed": [o.id for o in self.failed if o.severity == "error"],
            "outcomes": [o.model_dump() for o in self.outcomes],
        }


class Suite(BaseModel):
    """A named, reusable list of expectations."""

    model_config = ConfigDict(extra="forbid")

    name: str
    expectations: list[Expectation] = Field(..., min_length=1)
