"""CLI commands for batch processing operations."""

from dataclasses import dataclass
from pathlib import Path

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.path_config import resolve_project_root
from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.service import create_registry_manager_factory
from agent_actions.llm.batch.services.retrieval import BatchRetrievalService
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.storage import get_storage_backend
from agent_actions.storage.backend import StorageBackend


def _list_workflows(project_root: Path) -> list[str]:
    """Return workflow names — real (non-symlink) subdirs of `agent_workflow/`
    that contain a real `agent_config/`. Symlinks and hidden entries are
    skipped so a stray symlink can't point batch state at a path outside the
    project tree."""
    workflows_dir = project_root / "agent_workflow"
    if not workflows_dir.is_dir() or workflows_dir.is_symlink():
        return []
    candidates = []
    for p in workflows_dir.iterdir():
        if p.name.startswith(".") or p.is_symlink() or not p.is_dir():
            continue
        config = p / "agent_config"
        if config.is_symlink() or not config.is_dir():
            continue
        candidates.append(p.name)
    return sorted(candidates)


def _resolve_workflow(project_root: Path, agent_name: str | None) -> tuple[str, Path]:
    """Return (workflow_name, workflow_root) for the given (optional) agent name.

    Auto-selects the single workflow when only one exists; raises UsageError on
    ambiguity or unknown name. The workflow root is composed directly from the
    project root — `project_root / 'agent_workflow' / agent_name` — rather than
    walked, so a same-named directory nested elsewhere cannot shadow the real one.
    """
    candidates = _list_workflows(project_root)
    if not candidates:
        raise click.UsageError(
            f"No workflows found under {project_root / 'agent_workflow'}. "
            "Run `agac init` to scaffold one."
        )

    if agent_name is None:
        if len(candidates) == 1:
            agent_name = candidates[0]
        else:
            raise click.UsageError(
                "Multiple workflows found; pass -a <workflow_name>. "
                f"Available: {', '.join(candidates)}"
            )
    elif agent_name not in candidates:
        raise click.UsageError(
            f"Workflow '{agent_name}' not found. Available: {', '.join(candidates)}"
        )

    return agent_name, project_root / "agent_workflow" / agent_name


def _resolve_action(
    storage_backend: StorageBackend,
    workflow_name: str,
    action_name: str | None,
    batch_id: str | None = None,
) -> str:
    """Return the action name to use.

    When `--action` is given, it's accepted verbatim — empty strings are
    rejected. Skipping the registry check lets recovery flows work (e.g.
    a batch is still live at the provider after `--fresh` wiped the
    local registry).

    When `--action` is omitted and `batch_id` is supplied, scan registered
    actions for one whose registry contains that batch_id. Exactly one
    match → use it. Multiple matches → error. Otherwise fall back to the
    single-action auto-select.
    """
    if action_name is not None:
        if not action_name.strip():
            raise click.UsageError("--action must not be empty.")
        return action_name

    actions = BatchRegistryManager.list_action_names(storage_backend)
    if not actions:
        raise click.UsageError(
            f"No batch jobs found for workflow '{workflow_name}'; "
            "pass --action <action_name> to address a specific action."
        )

    if batch_id is not None:
        owning = [
            a
            for a in actions
            if BatchRegistryManager(
                storage_backend=storage_backend, action_name=a
            ).get_batch_job_by_id(batch_id)
            is not None
        ]
        if len(owning) == 1:
            return owning[0]
        if len(owning) > 1:
            raise click.UsageError(
                f"Batch '{batch_id}' is registered under multiple actions in "
                f"workflow '{workflow_name}'; pass --action <action_name>. "
                f"Candidates: {', '.join(owning)}"
            )
        # No action owns this batch_id locally — fall through to single-action
        # auto-select; the service layer will surface 'batch not found' if the
        # auto-selected action's registry doesn't include it.

    if len(actions) == 1:
        return actions[0]
    raise click.UsageError(
        f"Multiple batch actions in workflow '{workflow_name}'; "
        f"pass --action <action_name>. Available: {', '.join(actions)}"
    )


def _build_storage_backend(workflow_root: Path, workflow_name: str) -> StorageBackend:
    """Open the workflow's existing SQLite DB. Refuse to silently create one —
    `batch status` and `batch retrieve` are read-mostly commands; if the DB
    doesn't exist the user has never run the workflow and there's nothing to
    query."""
    db_path = workflow_root / "agent_io" / "store" / f"{workflow_name}.db"
    if not db_path.is_file():
        raise click.UsageError(
            f"Workflow '{workflow_name}' has no batch state yet. Run the workflow "
            f"first (no DB at {db_path})."
        )
    backend = get_storage_backend(
        workflow_path=str(workflow_root),
        workflow_name=workflow_name,
        backend_type="sqlite",
    )
    backend.initialize()
    return backend


@dataclass
class _BatchContext:
    workflow_name: str
    workflow_root: Path
    storage_backend: StorageBackend
    action_name: str


def _prepare_batch_context(
    project_root: Path | None,
    agent_name: str | None,
    action_name: str | None,
    batch_id: str | None = None,
) -> _BatchContext:
    root = resolve_project_root(project_root)
    workflow_name, workflow_root = _resolve_workflow(root, agent_name)
    storage_backend = _build_storage_backend(workflow_root, workflow_name)
    resolved_action = _resolve_action(
        storage_backend, workflow_name, action_name, batch_id=batch_id
    )
    return _BatchContext(
        workflow_name=workflow_name,
        workflow_root=workflow_root,
        storage_backend=storage_backend,
        action_name=resolved_action,
    )


def _workflow_action_options(f):
    """Add -a/--agent and --action options to a batch subcommand."""
    f = click.option(
        "--action",
        "action_name",
        required=False,
        help="Action name (required when a workflow has multiple batch actions).",
    )(f)
    f = click.option(
        "-a",
        "--agent",
        "agent_name",
        required=False,
        help="Workflow name (required in multi-workflow projects).",
    )(f)
    return f


@click.group()
def batch():
    """CLI command group for batch processing operations."""


@batch.command()
@_workflow_action_options
@click.option(
    "--batch-id",
    help=("The ID of the batch job to check."),
)
@handles_user_errors("batch status")
@requires_project
def status(
    batch_id: str | None = None,
    agent_name: str | None = None,
    action_name: str | None = None,
    project_root: Path | None = None,
):
    """Checks the status of a running batch job."""
    from agent_actions.cli.args import BatchCommandArgs

    args = BatchCommandArgs(batch_id=batch_id)
    if not args.batch_id:
        raise click.UsageError("--batch-id is required.")

    ctx = _prepare_batch_context(project_root, agent_name, action_name, batch_id=args.batch_id)

    client_resolver = BatchClientResolver(client_cache={}, default_client=None)
    context_manager = BatchContextManager()
    registry_manager_factory = create_registry_manager_factory(ctx.storage_backend)
    task_preparator = BatchTaskPreparator()
    service = BatchSubmissionService(
        task_preparator=task_preparator,
        client_resolver=client_resolver,
        context_manager=context_manager,
        registry_manager_factory=registry_manager_factory,
        storage_backend=ctx.storage_backend,
    )
    batch_status = service.check_status(
        args.batch_id,
        output_directory=str(ctx.workflow_root),
        action_name=ctx.action_name,
    )
    click.echo(f"Batch job status: {batch_status}")


@batch.command()
@_workflow_action_options
@click.option(
    "--batch-id",
    help=("The ID of the batch job to retrieve."),
)
@handles_user_errors("batch retrieve")
@requires_project
def retrieve(
    batch_id: str | None = None,
    agent_name: str | None = None,
    action_name: str | None = None,
    project_root: Path | None = None,
):
    """Retrieves the results of a completed batch job.

    Results are written under the workflow's per-action target directory
    (`agent_workflow/<wf>/agent_io/target/<action>/`), matching the layout
    `agac run` writes to.
    """
    from agent_actions.cli.args import BatchCommandArgs

    args = BatchCommandArgs(batch_id=batch_id)
    if not args.batch_id:
        raise click.UsageError("--batch-id is required.")

    ctx = _prepare_batch_context(project_root, agent_name, action_name, batch_id=args.batch_id)

    client_resolver = BatchClientResolver(client_cache={}, default_client=None)
    context_manager = BatchContextManager()
    registry_manager_factory = create_registry_manager_factory(ctx.storage_backend)
    service = BatchRetrievalService(
        client_resolver=client_resolver,
        context_manager=context_manager,
        registry_manager_factory=registry_manager_factory,
        storage_backend=ctx.storage_backend,
        action_name=ctx.action_name,
    )
    target_dir = ctx.workflow_root / "agent_io" / "target" / ctx.action_name
    target_dir.mkdir(parents=True, exist_ok=True)
    result = service.retrieve_results(args.batch_id, str(target_dir))
    click.echo(result)
