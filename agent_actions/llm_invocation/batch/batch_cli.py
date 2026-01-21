"""CLI commands for batch processing operations."""

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.llm_invocation.batch.batch_service import BatchService
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
    help=(
        "The ID of the batch job to check. If not provided, the last submitted job ID will be used."
    ),
)
@handles_user_errors("batch status")
@requires_project
def status(batch_id: str = None):
    """Checks the status of a running batch job."""
    args = BatchCommandArgs(batch_id=batch_id)
    service = BatchService()
    if not args.batch_id:
        args.batch_id = service._get_last_batch_job_id()
        if not args.batch_id:
            click.echo("No batch ID provided and no previous batch job found.")
            return
    batch_status = service.check_status(args.batch_id)
    click.echo(f"Batch job status: {batch_status}")


@batch.command()
@click.option(
    "--batch-id",
    help=(
        "The ID of the batch job to retrieve. "
        "If not provided, the last submitted job ID will be used."
    ),
)
@click.option(
    "--output-dir",
    "-o",
    default=".",
    type=click.Path(),
    help="Directory to save the retrieved results.",
)
@handles_user_errors("batch retrieve")
@requires_project
def retrieve(batch_id: str = None, output_dir: str = "."):
    """Retrieves the results of a completed batch job."""
    args = BatchCommandArgs(batch_id=batch_id, output_dir=output_dir)
    service = BatchService()
    if not args.batch_id:
        args.batch_id = service._get_last_batch_job_id()
        if not args.batch_id:
            click.echo("No batch ID provided and no previous batch job found.")
            return
    result = service.retrieve_results(args.batch_id, str(args.output_dir))
    click.echo(result)
