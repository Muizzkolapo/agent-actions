#!/usr/bin/env python3
"""Reset workflow state.

Default (soft reset): removes .agent_status.json so the next run re-drives the
workflow, while keeping source data and the SQLite store intact. Records already
completed in the store are carried forward, not regenerated — use --full for a
true from-scratch rebuild.

--full: wipes source/, store/, target/, and .agent_status.json, then recreates
target/, and reclaims what a provider recorded locally under .agac/ about this
workflow's batches, since the store being removed is what names them.

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


def release_batch_records(root: Path, base: Path, workflow: str) -> bool:
    """Reclaim what a provider recorded locally about this workflow's batches.

    The store about to go holds the registry, and the registry is what names a
    batch: afterwards nothing can find these records, and each holds the payload
    its batch was submitted with. False says the store has to stay.
    """
    if not (base / "store").is_dir():
        return True
    released = True
    try:
        from agent_actions.config.paths import PathManager
        from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
        from agent_actions.llm.providers.local_batch_records import (
            discard_partial_batch_records,
            release_local_batch_record,
        )
        from agent_actions.storage import get_storage_backend
        from agent_actions.utils.path_utils import set_path_manager

        set_path_manager(PathManager(project_root=root))
        discard_partial_batch_records()
        backend = get_storage_backend(workflow_path=str(base.parent), workflow_name=workflow)
        try:
            backend.initialize()
            for action_name in BatchRegistryManager.list_action_names(backend):
                for batch_id in BatchRegistryManager.batch_ids(backend, action_name):
                    released = release_local_batch_record(batch_id) and released
        finally:
            backend.close()
    except Exception as e:  # noqa: BLE001 - a reset must not be blocked by this
        print(
            f"warning: could not reclaim what a provider recorded locally ({e}).",
            file=sys.stderr,
        )
        return False
    return released


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow")
    parser.add_argument(
        "--full",
        action="store_true",
        help="wipe all agent_io state and reclaim this workflow's local batch records",
    )
    args = parser.parse_args()

    root = find_project_root(Path.cwd())
    base = root / "agent_workflow" / args.workflow / "agent_io"
    if not base.exists():
        sys.exit(f"error: {base} not found")

    status = base / ".agent_status.json"

    if args.full:
        print(
            f"Full reset: wiping source, store, target, and status under {base}, "
            "and reclaiming this workflow's local batch records"
        )
        # The store is what names these batches. Removing it over a record that
        # would not go puts that payload out of reach of every command.
        reclaimed = release_batch_records(root, base, args.workflow)
        if not reclaimed:
            print("Keeping store/: it is what names the batches whose records stayed.")
        for sub in ("target", "source", "store") if reclaimed else ("target", "source"):
            remove(base / sub)
        remove(status)
        (base / "target").mkdir(parents=True, exist_ok=True)
        print("Done.")
    else:
        print(f"Soft reset: clearing {status} (keeps DB and source)")
        remove(status)
        print(
            f"Done. Run `agac run -a {args.workflow} -u tools` to re-drive the workflow "
            "(completed records carry forward; use --full to regenerate everything)."
        )


if __name__ == "__main__":
    main()
