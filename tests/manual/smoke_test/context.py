from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CheckResult:
    """Result of a single verification check."""

    passed: bool
    name: str
    message: str = ""


@dataclass
class RunContext:
    """Everything a check needs to verify a smoke test run."""

    example: Example
    project_dir: Path
    exit_code: int
    stdout: str
    stderr: str

    @property
    def workflow_dir(self) -> Path:
        return self.project_dir / "agent_workflow" / self.example.workflow

    @property
    def target_dir(self) -> Path:
        return self.workflow_dir / "agent_io" / "target"

    @property
    def config_path(self) -> Path:
        return self.workflow_dir / "agent_config" / f"{self.example.workflow}.yml"


@dataclass
class Example:
    """A registered example project with its expected checks."""

    name: str
    path: str  # relative to repo root, e.g. "examples/support_resolution"
    workflow: str  # workflow name (matches YAML stem)
    actions: int  # expected action count
    checks: list[Any] = field(default_factory=list)
    skip_actions: list[str] = field(default_factory=list)  # actions to skip (e.g. HITL)
