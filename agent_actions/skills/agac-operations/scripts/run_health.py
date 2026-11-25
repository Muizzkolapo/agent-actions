#!/usr/bin/env python3
"""Stop a run loop when an action keeps far less usable output than normal.

A workflow can end with exit code 0 and keep a small part of its records: a judge
votes FAIL on every record, the repair rounds are used up, and the last output is
kept. This script reads the public counts (``agac dispositions --json``) and the
action status file (``agent_io/.agent_status.json``), and reports each finished
action whose share of bad records is above a limit. With ``--sandbox`` it reads the
output of sandbox runs (``agac run --sandbox``) instead.

Usage (from the project root):

    python3 run_health.py -w <workflow>
    python3 run_health.py -w <workflow> --max-bad 0.2 --min-records 20
    python3 run_health.py -w <workflow> --counts counts.json   # counts saved before
    python3 run_health.py -w <workflow> --sandbox              # sandbox runs

Exit codes: 0 = no action above the limit, 1 = at least one action above it,
2 = the counts or the status file cannot be read.

The script needs only the standard library, so it runs with a plain ``python3``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

BAD = ("failed", "failed_checks", "exhausted")
FINISHED = ("completed", "completed_with_failures")


def find_project_root(start: Path) -> Path | None:
    """The nearest folder at or above *start* that holds ``agent_actions.yml``."""
    for folder in (start, *start.parents):
        if (folder / "agent_actions.yml").is_file():
            return folder
    return None


def status_path(io_dir: Path, sandbox: bool) -> Path:
    """The action status file of real runs, or of sandbox runs."""
    try:
        from agent_actions.config.sandbox import sandbox_mode, status_file
    except ImportError:
        # A plain python3 usually cannot import the framework: the path it writes.
        run_dir = io_dir / "sandbox" if sandbox else io_dir
        return run_dir / ".agent_status.json"
    with sandbox_mode(sandbox):
        return status_file(io_dir)


def read_counts(workflow: str, counts_file: str | None, sandbox: bool = False) -> dict[str, Any]:
    """The ``agac dispositions --json`` report, from a file or from the command."""
    if counts_file:
        report: dict[str, Any] = json.loads(Path(counts_file).read_text(encoding="utf-8"))
        return report
    done = subprocess.run(
        ["agac", "dispositions", "-w", workflow, "--json", *(["--sandbox"] if sandbox else [])],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or f"agac dispositions exited {done.returncode}")
    parsed: dict[str, Any] = json.loads(done.stdout)
    return parsed


def finished_actions(status_file: Path) -> set[str]:
    """The actions that the status file marks completed or completed_with_failures."""
    status = json.loads(status_file.read_text(encoding="utf-8"))
    return {
        name
        for name, entry in status.items()
        if isinstance(entry, dict) and entry.get("status") in FINISHED
    }


def check(
    report: dict[str, Any], finished: set[str], max_bad: float, min_records: int
) -> list[dict[str, Any]]:
    """One row for each finished action: its checked records, bad share and verdict."""
    rows = []
    for entry in report.get("actions", []):
        name = entry.get("name")
        if name not in finished:
            continue
        counts = entry.get("counts") or {}
        bad = sum(int(counts.get(key, 0) or 0) for key in BAD)
        checked = bad + int(counts.get("success", 0) or 0)
        share = bad / checked if checked else 0.0
        rows.append(
            {
                "action": name,
                "checked": checked,
                "bad": bad,
                "bad_share": round(share, 3),
                "above_limit": checked >= min_records and share > max_bad,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-w", "--workflow", required=True, help="Workflow name")
    parser.add_argument(
        "--max-bad", type=float, default=0.2, help="Largest bad share (default 0.2)"
    )
    parser.add_argument(
        "--min-records", type=int, default=20, help="Fewest checked records to judge (default 20)"
    )
    parser.add_argument("--counts", help="Read a saved 'agac dispositions --json' report")
    parser.add_argument(
        "--status", help="Path of .agent_status.json (default: found from the project)"
    )
    parser.add_argument(
        "--sandbox", action="store_true", help="Check the output of sandbox runs (--sandbox)"
    )
    args = parser.parse_args(argv)

    if args.status:
        status_file = Path(args.status)
    else:
        root = find_project_root(Path.cwd())
        if root is None:
            sys.stderr.write("health: no agent_actions.yml at or above this folder\n")
            return 2
        io_dir = root / "agent_workflow" / args.workflow / "agent_io"
        status_file = status_path(io_dir, args.sandbox)
    try:
        report = read_counts(args.workflow, args.counts, args.sandbox)
        finished = finished_actions(status_file)
    except (OSError, ValueError, RuntimeError) as exc:
        sys.stderr.write(f"health: cannot read the counts or the status: {exc}\n")
        return 2

    rows = check(report, finished, args.max_bad, args.min_records)
    for row in rows:
        mark = "  ABOVE THE LIMIT" if row["above_limit"] else ""
        sys.stdout.write(
            f"health: {row['action']}: {row['bad']} bad of {row['checked']} "
            f"({row['bad_share']:.0%}){mark}\n"
        )
    if any(row["above_limit"] for row in rows):
        sys.stdout.write(
            f"health: STOP. An action has more than {args.max_bad:.0%} bad records. "
            f"Read 'agac dispositions -w {args.workflow} --quarantined"
            f"{' --sandbox' if args.sandbox else ''}' before you run again.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
