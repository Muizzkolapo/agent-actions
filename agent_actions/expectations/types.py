"""Models for expectations, suites, and their results."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["fail", "warn", "info"]

_DECLARED_FIELDS = frozenset({"id", "type", "field", "severity", "hint"})


class Expectation(BaseModel):
    """One rule in a suite.

    Type-specific parameters (``equals``, ``phrases``, ``max_ratio``, ...) are
    accepted as extra keys so suites read as flat YAML; the registry declares
    which parameters each type takes and preflight rejects the rest.
    """

    model_config = ConfigDict(extra="allow")

    id: str | None = Field(default=None, description="Stable identifier; derived when omitted")
    type: str = Field(..., description="Registered expectation type name")
    field: str | list[str] = Field(..., description="Field selector this rule is tested against")
    severity: Severity = Field(default="fail", description="fail, warn, or info")
    hint: str | None = Field(default=None, description="Remedy text; used only by repair")

    def params(self) -> dict[str, Any]:
        """Type-specific parameters, i.e. everything that is not a declared field."""
        return {k: v for k, v in self.model_dump().items() if k not in _DECLARED_FIELDS}

    def definition_hash(self) -> str:
        """Stable digest of what this rule tests, ignoring its name."""
        payload = self.model_dump(exclude={"id"}, exclude_none=True)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    @property
    def resolved_id(self) -> str:
        """The authored id, or one derived from type and definition so it survives reordering."""
        return self.id or f"{self.type}_{self.definition_hash()}"


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
        """True unless a fail-severity expectation failed; warn and info never block."""
        return not any(o.severity == "fail" and not o.passed for o in self.outcomes)

    def to_record_dict(self) -> dict[str, Any]:
        """The verdict as attached to a record under the ``expect`` key."""
        return {
            "overall_pass": self.overall_pass,
            "failed": [o.id for o in self.failed if o.severity == "fail"],
            "outcomes": [o.model_dump() for o in self.outcomes],
        }


class Suite(BaseModel):
    """A named, reusable list of expectations."""

    model_config = ConfigDict(extra="forbid")

    name: str
    expectations: list[Expectation] = Field(..., min_length=1)
