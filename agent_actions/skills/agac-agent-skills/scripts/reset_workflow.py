#!/usr/bin/env python3
"""Reset workflow state.

Default (soft reset): removes .agent_status.json so the next run starts from
scratch while keeping source data and the SQLite store intact.

--full: wipes source/, store/, target/, and .agent_status.json, then
recreates target/.

Usage:
  python reset_workflow.py <workflow> [--full]

Self-locates the project root by walking up looking for agent_actions.yml.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def find_project_root(start: Path) -> Path:
    for d in [start, *start.parents]:
        if (d / "agent_actions.yml").is_file():
            return d
    sys.exit("error: agent_actions.yml not found in current directory or any parent")


def remove(p: Path) -> None:
    if p.is_dir():
        shutil.rmtree(p)
    elif p.exists():
        p.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow")
    parser.add_argument("--full", action="store_true", help="wipe all agent_io state")
    args = parser.parse_args()

    root = find_project_root(Path.cwd())
    base = root / "agent_workflow" / args.workflow / "agent_io"
    if not base.exists():
        sys.exit(f"error: {base} not found")

    status = base / ".agent_status.json"

    if args.full:
        print(f"Full reset: wiping source, store, target, and status under {base}")
        for sub in ("target", "source", "store"):
            remove(base / sub)
        remove(status)
        (base / "target").mkdir(parents=True, exist_ok=True)
        print("Done.")
    else:
        print(f"Soft reset: clearing {status} (keeps DB and source)")
        remove(status)
        print(f"Done. Run `agac run -a {args.workflow} -u tools` to re-run from scratch.")


if __name__ == "__main__":
    main()
