"""CLI commands for batch processing operations."""

from pathlib import Path

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.config.path_config import resolve_project_root
from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
from agent_actions.llm.batch.infrastructure.context import BatchContextManager
from agent_actions.llm.batch.processing.preparator import BatchTaskPreparator
from agent_actions.llm.batch.service import create_registry_manager_factory
from agent_actions.llm.batch.services.retrieval import BatchRetrievalService
from agent_actions.llm.batch.services.submission import BatchSubmissionService


@click.group()
def batch():
    """CLI command group for batch processing operations."""


@batch.command()
@click.option(
    "--batch-id",
    help=("The ID of the batch job to check."),
)
@handles_user_errors("batch status")
@requires_project
def status(batch_id: str | None = None, project_root: Path | None = None):
    """Checks the status of a running batch job."""
    from agent_actions.validation.batch_validator import BatchCommandArgs

    args = BatchCommandArgs(batch_id=batch_id)
    if not args.batch_id:
        raise click.UsageError("--batch-id is required.")
    client_resolver = BatchClientResolver(client_cache={}, default_client=None)
    context_manager = BatchContextManager()
    registry_manager_factory = create_registry_manager_factory()
    task_preparator = BatchTaskPreparator()
    service = BatchSubmissionService(
        task_preparator=task_preparator,
        client_resolver=client_resolver,
        context_manager=context_manager,
        registry_manager_factory=registry_manager_factory,
    )
    output_dir = str(project_root) if project_root else None
    batch_status = service.check_status(args.batch_id, output_directory=output_dir)
    click.echo(f"Batch job status: {batch_status}")


@batch.command()
@click.option(
    "--batch-id",
    help=("The ID of the batch job to retrieve."),
)
@handles_user_errors("batch retrieve")
@requires_project
def retrieve(batch_id: str | None = None, project_root: Path | None = None):
    """Retrieves the results of a completed batch job.

    Results are saved to the workflow's configured output directory to maintain
    consistency with the batch registry.
    """
    from agent_actions.validation.batch_validator import BatchCommandArgs

    args = BatchCommandArgs(batch_id=batch_id)
    if not args.batch_id:
        raise click.UsageError("--batch-id is required.")
    client_resolver = BatchClientResolver(client_cache={}, default_client=None)
    context_manager = BatchContextManager()
    registry_manager_factory = create_registry_manager_factory()
    service = BatchRetrievalService(
        client_resolver=client_resolver,
        context_manager=context_manager,
        registry_manager_factory=registry_manager_factory,
    )
    result = service.retrieve_results(args.batch_id, str(resolve_project_root(project_root)))
    click.echo(result)
