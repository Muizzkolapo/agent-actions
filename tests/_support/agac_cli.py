"""Run the `agac` console script against the tree these tests live in."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
AGAC = Path(sys.executable).parent / "agac"


def run_agac(
    cwd: Path, *args: str, env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run `agac` in *cwd* with this tree first on its import path.

    The console script otherwise imports `agent_actions` from wherever the
    venv's editable install points, which from a second worktree is another
    checkout; pytest.ini's `pythonpath` reaches only the pytest process.
    """
    merged = {**os.environ, **(env or {})}
    inherited = merged.get("PYTHONPATH")
    merged["PYTHONPATH"] = os.pathsep.join([str(REPO), inherited]) if inherited else str(REPO)
    return subprocess.run(
        [str(AGAC), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=300,
        env=merged,
    )
