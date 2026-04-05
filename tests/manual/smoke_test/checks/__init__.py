from __future__ import annotations

from abc import ABC, abstractmethod

from tests.manual.smoke_test.context import CheckResult, RunContext


class Check(ABC):
    """Base class for all smoke test checks."""

    @abstractmethod
    def verify(self, ctx: RunContext) -> list[CheckResult]:
        """Run verification against the completed run. Return one or more results."""
