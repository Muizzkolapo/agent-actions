"""CLI commands for batch processing operations."""

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.llm_invocation.batch.infrastructure.batch_job_manager import BatchJobManager
from agent_actions.llm_invocation.batch.infrastructure.batch_client_resolver import (
    BatchClientResolver,
)
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
        # pylint: disable=protected-access,no-member
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
        # pylint: disable=protected-access,no-member
        args.batch_id = service._get_last_batch_job_id()
        if not args.batch_id:
            click.echo("No batch ID provided and no previous batch job found.")
            return
    result = service.retrieve_results(args.batch_id, str(args.output_dir))
    click.echo(result)


@batch.command()
@click.option(
    "--batch-id",
    required=True,
    help="The ID of the batch job to retry.",
)
@click.option(
    "--max-attempts",
    "-n",
    default=3,
    type=int,
    help="Maximum number of retry attempts (default: 3).",
)
@click.option(
    "--output-dir",
    "-o",
    default=".",
    type=click.Path(),
    help="Directory containing the batch registry.",
)
@handles_user_errors("batch retry")
@requires_project
def retry(batch_id: str, max_attempts: int = 3, output_dir: str = "."):
    """Retry failed records from a completed batch job.

    Triggers automatic retry for any missing/failed records in the batch.
    Continues retrying until all records succeed or max attempts is reached.
    """
    service = BatchService()
    click.echo(f"Retrying batch {batch_id} (max attempts: {max_attempts})...")

    retry_batch_id = service.retry_batch_job(
        batch_id=batch_id,
        output_directory=output_dir,
        max_attempts=max_attempts,
    )

    if retry_batch_id:
        click.echo(f"Retry complete. Final retry batch: {retry_batch_id}")
    else:
        click.echo("No missing records found - retry not needed.")


@batch.command("chain-status")
@click.option(
    "--batch-id",
    required=True,
    help="Any batch ID in the retry chain.",
)
@click.option(
    "--output-dir",
    "-o",
    default=".",
    type=click.Path(),
    help="Directory containing the batch registry.",
)
@handles_user_errors("batch chain-status")
@requires_project
def chain_status(batch_id: str, output_dir: str = "."):
    """Show the status of a batch retry chain.

    Displays the full retry chain from original batch through all retries,
    including status of each batch and overall progress.
    """
    client_resolver = BatchClientResolver()
    job_manager = BatchJobManager(client_resolver=client_resolver)

    chain_result = job_manager.get_retry_chain_status(batch_id, output_dir)

    if chain_result.current_status == "unknown":
        click.echo(f"Batch {batch_id} not found in registry.")
        return

    click.echo(f"Batch Chain Status for {chain_result.original_batch_id}")
    click.echo("-" * 50)
    click.echo(f"Total retry attempts: {chain_result.total_attempts}")
    click.echo(f"Current status: {chain_result.current_status}")
    click.echo(f"Total records: {chain_result.total_records}")

    if chain_result.has_retries:
        click.echo("\nRetry Chain:")
        lineage = job_manager.get_batch_lineage(batch_id, output_dir)
        for i, entry in enumerate(lineage):
            prefix = "  " if i == 0 else f"  {'  ' * i}"
            arrow = "" if i == 0 else "-> "
            retry_info = (
                f" (retry {entry.retry_attempt})" if entry.retry_attempt > 0 else " (original)"
            )
            records_info = f", {entry.record_count} records" if entry.record_count else ""
            click.echo(f"{prefix}{arrow}{entry.batch_id}: {entry.status}{retry_info}{records_info}")
