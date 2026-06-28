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
    """Return workflow names — directories under `agent_workflow/` that contain
    an `agent_config/` subdir. Hidden entries (`.<name>`) are skipped."""
    workflows_dir = project_root / "agent_workflow"
    if not workflows_dir.is_dir():
        return []
    return sorted(
        p.name
        for p in workflows_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".") and (p / "agent_config").is_dir()
    )


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
    storage_backend: StorageBackend, workflow_name: str, action_name: str | None
) -> str:
    """Return the action name to use.

    When `--action` is given, it's accepted verbatim — the service layer will
    surface a clearer error if the batch is unknown to the provider. This keeps
    recovery scenarios working (e.g. after `--fresh` wiped the local registry
    but a batch is still live at the provider).

    When `--action` is omitted, auto-select from the local registry.
    """
    if action_name is not None:
        return action_name

    actions = BatchRegistryManager.list_action_names(storage_backend)
    if len(actions) == 1:
        return actions[0]
    if not actions:
        raise click.UsageError(
            f"No batch jobs found for workflow '{workflow_name}'; "
            "pass --action <action_name> to address a specific action."
        )
    raise click.UsageError(
        f"Multiple batch actions in workflow '{workflow_name}'; "
        f"pass --action <action_name>. Available: {', '.join(actions)}"
    )


def _build_storage_backend(workflow_root: Path, workflow_name: str) -> StorageBackend:
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
) -> _BatchContext:
    root = resolve_project_root(project_root)
    workflow_name, workflow_root = _resolve_workflow(root, agent_name)
    storage_backend = _build_storage_backend(workflow_root, workflow_name)
    resolved_action = _resolve_action(storage_backend, workflow_name, action_name)
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
    from agent_actions.validation.batch_validator import BatchCommandArgs

    args = BatchCommandArgs(batch_id=batch_id)
    if not args.batch_id:
        raise click.UsageError("--batch-id is required.")

    ctx = _prepare_batch_context(project_root, agent_name, action_name)

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

    Results are saved to the workflow's configured output directory to maintain
    consistency with the batch registry.
    """
    from agent_actions.validation.batch_validator import BatchCommandArgs

    args = BatchCommandArgs(batch_id=batch_id)
    if not args.batch_id:
        raise click.UsageError("--batch-id is required.")

    ctx = _prepare_batch_context(project_root, agent_name, action_name)

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
    result = service.retrieve_results(args.batch_id, str(ctx.workflow_root))
    click.echo(result)
