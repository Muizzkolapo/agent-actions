#!/usr/bin/env python3
"""Show an action's config + template variable resolution.

Usage:
  python inspect_action.py <workflow> <action_name> [--tools <path>]

Self-locates the project root by walking up from the current directory
looking for agent_actions.yml.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def find_project_root(start: Path) -> Path:
    for d in [start, *start.parents]:
        if (d / "agent_actions.yml").is_file():
            return d
    sys.exit("error: agent_actions.yml not found in current directory or any parent")


def agac_prefix() -> list[str]:
    if shutil.which("uv"):
        return ["uv", "run", "agac"]
    if shutil.which("agac"):
        return ["agac"]
    sys.exit("error: neither `uv` nor `agac` found on PATH")


def run(cmd: list[str], cwd: Path) -> int:
    print(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=cwd)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("workflow")
    p.add_argument("action_name")
    p.add_argument("--tools", default="tools", help="path to UDF directory (default: tools)")
    args = p.parse_args()

    root = find_project_root(Path.cwd())
    base = agac_prefix()

    print("=== Config & Schema ===")
    rc1 = run(
        base + ["inspect", "action", "-a", args.workflow, "-u", args.tools, args.action_name], root
    )

    print("\n=== Context (template variables) ===")
    rc2 = run(
        base + ["inspect", "context", "-a", args.workflow, "-u", args.tools, args.action_name], root
    )

    sys.exit(rc1 or rc2)


if __name__ == "__main__":
    main()
