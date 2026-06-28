"""Workflow + batch-registry scaffolding shared by integration tests and manual repros."""

from __future__ import annotations

from pathlib import Path

from agent_actions.llm.batch.core.batch_constants import BatchStatus
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.storage import get_storage_backend


def seed_workflow(
    project_root: Path,
    wf: str,
    action: str,
    batch_id: str,
    *,
    timestamp: str = "2026-06-28T00:00:00Z",
) -> None:
    """Create `agent_workflow/<wf>/{agent_config,agent_io/store}` and seed a
    `batch_registry:{action}` entry in the workflow's SQLite DB."""
    wf_root = project_root / "agent_workflow" / wf
    (wf_root / "agent_io" / "store").mkdir(parents=True, exist_ok=True)
    (wf_root / "agent_config").mkdir(parents=True, exist_ok=True)
    (wf_root / "agent_config" / f"{wf}.yml").write_text(f"name: {wf}\n")
    (wf_root / f"{wf}.yml").write_text(f"name: {wf}\n")

    backend = get_storage_backend(workflow_path=str(wf_root), workflow_name=wf)
    backend.initialize()
    registry = BatchRegistryManager(storage_backend=backend, action_name=action)
    registry.save_batch_job(
        file_name=f"{action}_chunk_0.jsonl",
        entry=BatchJobEntry(
            batch_id=batch_id,
            status=BatchStatus.COMPLETED,
            timestamp=timestamp,
            provider="ollama",
            file_name=f"{action}_chunk_0.jsonl",
        ),
    )
