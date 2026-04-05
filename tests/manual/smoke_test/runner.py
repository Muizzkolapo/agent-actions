from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from tests.manual.smoke_test.context import Example, RunContext

logger = logging.getLogger(__name__)


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (where agent_actions/ and examples/ live)."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "examples").is_dir() and (current / "agent_actions").is_dir():
            return current
        current = current.parent
    msg = "Could not find repo root"
    raise RuntimeError(msg)


def _override_vendor(config_path: Path) -> None:
    """Replace LLM vendor/model/key in the workflow config with agac-provider."""
    content = config_path.read_text()

    # Override defaults block values
    content = re.sub(r"(model_vendor:\s*)\S+", r"\1agac-provider", content)
    content = re.sub(r"(model_name:\s*)\S+", r"\1agac-model", content)
    content = re.sub(r"(api_key:\s*)\S+", r"\1not_required", content)

    # Override any kind: hitl to kind: llm (so HITL actions run through AgacClient)
    content = re.sub(r"(kind:\s*)hitl\b", r"\1llm", content)

    # Force online mode so everything runs synchronously in one pass
    content = re.sub(r"(run_mode:\s*)\S+", r"\1online", content)

    config_path.write_text(content)


def run_example(example: Example) -> RunContext:
    """Copy example to temp dir, override vendor, run agac CLI, return context."""
    repo_root = _find_repo_root()
    example_src = repo_root / example.path

    # Copy to temp dir preserving the project structure agac expects
    tmp = Path(tempfile.mkdtemp(prefix=f"smoke_{example.name}_"))
    project_dir = tmp / example.name
    shutil.copytree(example_src, project_dir)

    # Find and override the workflow config — validate at least one was found
    config_dir = project_dir / "agent_workflow" / example.workflow / "agent_config"
    configs_overridden = 0
    for yml in config_dir.glob("*.yml"):
        _override_vendor(yml)
        configs_overridden += 1

    if configs_overridden == 0:
        shutil.rmtree(tmp, ignore_errors=True)
        msg = f"No .yml config files found in {config_dir} — would run against real LLM APIs"
        raise FileNotFoundError(msg)

    # Run agac CLI
    result = subprocess.run(
        ["agac", "run", "-a", example.workflow, "--fresh"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "AGENT_ACTIONS_ENV": "test"},
    )

    return RunContext(
        example=example,
        project_dir=project_dir,
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def cleanup(ctx: RunContext) -> None:
    """Remove the temp project directory."""
    shutil.rmtree(ctx.project_dir.parent, ignore_errors=True)
