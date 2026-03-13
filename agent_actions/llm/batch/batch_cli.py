"""CLI commands for batch processing operations."""

from pathlib import Path

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.llm.batch.service import BatchService


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
def status(batch_id: str = None, project_root: Path | None = None):
    """Checks the status of a running batch job."""
    from agent_actions.validation.batch_validator import BatchCommandArgs

    args = BatchCommandArgs(batch_id=batch_id)
    if not args.batch_id:
        raise click.UsageError("--batch-id is required.")
    service = BatchService()
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
def retrieve(batch_id: str = None, project_root: Path | None = None):
    """Retrieves the results of a completed batch job.

    Results are saved to the workflow's configured output directory to maintain
    consistency with the batch registry.
    """
    from agent_actions.validation.batch_validator import BatchCommandArgs

    args = BatchCommandArgs(batch_id=batch_id)
    if not args.batch_id:
        raise click.UsageError("--batch-id is required.")
    service = BatchService()
    result = service.retrieve_results(args.batch_id, str(project_root or Path.cwd()))
    click.echo(result)
