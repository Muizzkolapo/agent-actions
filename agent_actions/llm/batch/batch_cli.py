"""CLI commands for batch processing operations."""

from pathlib import Path

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.path_config import resolve_project_root
from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.service import create_registry_manager_factory
from agent_actions.llm.batch.services.retrieval import BatchRetrievalService
from agent_actions.llm.batch.services.submission import BatchSubmissionService
from agent_actions.storage import get_storage_backend
from agent_actions.storage.backend import StorageBackend

_BATCH_REGISTRY_PREFIX = "batch_registry:"


def _resolve_workflow(project_root: Path, agent_name: str | None) -> tuple[str, Path]:
    """Return (workflow_name, workflow_root) for the given (optional) agent name.

    Auto-selects the single workflow when only one exists; raises UsageError on
    ambiguity or unknown name.
    """
    workflows_dir = project_root / "agent_workflow"
    if not workflows_dir.is_dir():
        raise click.UsageError(
            f"No workflows found under {workflows_dir}. Run `agac init` to scaffold one."
        )

    candidates = sorted(p.name for p in workflows_dir.iterdir() if p.is_dir())
    if not candidates:
        raise click.UsageError(
            f"No workflows found under {workflows_dir}. Run `agac init` to scaffold one."
        )

    if agent_name is None:
        if len(candidates) == 1:
            agent_name = candidates[0]
        else:
            raise click.UsageError(
                f"Multiple workflows found; pass -a <workflow_name>. "
                f"Available: {', '.join(candidates)}"
            )
    elif agent_name not in candidates:
        raise click.UsageError(
            f"Workflow '{agent_name}' not found. Available: {', '.join(candidates)}"
        )

    agent_config_dir, _ = ProjectPathsFactory.get_agent_paths(agent_name, project_root)
    return agent_name, agent_config_dir.parent


def _resolve_action(
    storage_backend: StorageBackend, agent_name: str, action_name: str | None
) -> str:
    """Return action_name, auto-selecting when unambiguous; UsageError otherwise."""
    keys = storage_backend.list_metadata_prefix(_BATCH_REGISTRY_PREFIX)
    actions = [k.removeprefix(_BATCH_REGISTRY_PREFIX) for k in keys]

    if action_name is None:
        if len(actions) == 1:
            return actions[0]
        if not actions:
            raise click.UsageError(f"No batch jobs found for workflow '{agent_name}'.")
        raise click.UsageError(
            f"Multiple batch actions in workflow '{agent_name}'; "
            f"pass --action <action_name>. Available: {', '.join(actions)}"
        )

    if action_name not in actions:
        available = ", ".join(actions) if actions else "(none)"
        raise click.UsageError(
            f"No batch job for action '{action_name}' in workflow '{agent_name}'. "
            f"Available: {available}"
        )
    return action_name


def _build_storage_backend(workflow_root: Path, workflow_name: str) -> StorageBackend:
    backend = get_storage_backend(
        workflow_path=str(workflow_root),
        workflow_name=workflow_name,
        backend_type="sqlite",
    )
    backend.initialize()
    return backend


@click.group()
def batch():
    """CLI command group for batch processing operations."""


@batch.command()
@click.option(
    "-a",
    "--agent",
    "agent_name",
    required=False,
    help="Workflow name (required in multi-workflow projects).",
)
@click.option(
    "--action",
    "action_name",
    required=False,
    help="Action name (required when a workflow has multiple batch actions).",
)
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

    root = resolve_project_root(project_root)
    workflow_name, workflow_root = _resolve_workflow(root, agent_name)
    storage_backend = _build_storage_backend(workflow_root, workflow_name)
    resolved_action = _resolve_action(storage_backend, workflow_name, action_name)

    client_resolver = BatchClientResolver(client_cache={}, default_client=None)
    context_manager = BatchContextManager()
    registry_manager_factory = create_registry_manager_factory(storage_backend)
    task_preparator = BatchTaskPreparator()
    service = BatchSubmissionService(
        task_preparator=task_preparator,
        client_resolver=client_resolver,
        context_manager=context_manager,
        registry_manager_factory=registry_manager_factory,
        storage_backend=storage_backend,
    )
    batch_status = service.check_status(
        args.batch_id, output_directory=str(workflow_root), action_name=resolved_action
    )
    click.echo(f"Batch job status: {batch_status}")


@batch.command()
@click.option(
    "-a",
    "--agent",
    "agent_name",
    required=False,
    help="Workflow name (required in multi-workflow projects).",
)
@click.option(
    "--action",
    "action_name",
    required=False,
    help="Action name (required when a workflow has multiple batch actions).",
)
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

    root = resolve_project_root(project_root)
    workflow_name, workflow_root = _resolve_workflow(root, agent_name)
    storage_backend = _build_storage_backend(workflow_root, workflow_name)
    resolved_action = _resolve_action(storage_backend, workflow_name, action_name)

    client_resolver = BatchClientResolver(client_cache={}, default_client=None)
    context_manager = BatchContextManager()
    registry_manager_factory = create_registry_manager_factory(storage_backend)
    service = BatchRetrievalService(
        client_resolver=client_resolver,
        context_manager=context_manager,
        registry_manager_factory=registry_manager_factory,
        storage_backend=storage_backend,
        action_name=resolved_action,
    )
    result = service.retrieve_results(args.batch_id, str(workflow_root))
    click.echo(result)
