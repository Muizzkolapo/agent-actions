"""CLI commands for batch processing operations."""

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.llm.batch.service import BatchService
from agent_actions.validation.batch_validator import BatchCommandArgs


@click.group()
def batch():
    """
    CLI command group for batch processing operations.

    Manages the lifecycle of batch processing jobs including submission,
    status checking, and result retrieval.
    """


@batch.command()
@click.option(
    "--batch-id",
    help=("The ID of the batch job to check."),
)
@handles_user_errors("batch status")
@requires_project
def status(batch_id: str = None):
    """Checks the status of a running batch job."""
    args = BatchCommandArgs(batch_id=batch_id)
    if not args.batch_id:
        raise click.UsageError("--batch-id is required.")
    service = BatchService()
    batch_status = service.check_status(args.batch_id)
    click.echo(f"Batch job status: {batch_status}")


@batch.command()
@click.option(
    "--batch-id",
    help=("The ID of the batch job to retrieve."),
)
@handles_user_errors("batch retrieve")
@requires_project
def retrieve(batch_id: str = None):
    """Retrieves the results of a completed batch job.

    Results are saved to the workflow's configured output directory to maintain
    consistency with the batch registry.
    """
    args = BatchCommandArgs(batch_id=batch_id)
    if not args.batch_id:
        raise click.UsageError("--batch-id is required.")
    service = BatchService()
    # @requires_project changes CWD to project root before this runs.
    # The batch registry lives at {project_root}/batch/.batch_registry.json,
    # so "." correctly resolves to the project root where the registry lives.
    result = service.retrieve_results(args.batch_id, ".")
    click.echo(result)
