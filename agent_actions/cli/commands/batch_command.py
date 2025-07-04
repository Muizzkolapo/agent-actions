import click
from agent_actions.services.batch_service import BatchService

@click.group()
def batch():
    """Manages the lifecycle of batch processing jobs."""
    pass

@batch.command()
@click.option('--batch-id', help='The ID of the batch job to check. If not provided, the last submitted job ID will be used.')
def status(batch_id: str = None):
    """Checks the status of a running batch job."""
    service = BatchService()
    if not batch_id:
        batch_id = service._get_last_batch_job_id()
        if not batch_id:
            click.echo("No batch ID provided and no previous batch job found.")
            return
    try:
        status = service.check_status(batch_id)
        click.echo(f"Batch job status: {status}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@batch.command()
@click.option('--batch-id', help='The ID of the batch job to retrieve. If not provided, the last submitted job ID will be used.')
@click.option('--output-dir', '-o', default='.', type=click.Path(), help='Directory to save the retrieved results.')
def retrieve(batch_id: str = None, output_dir: str = '.'):
    """Retrieves the results of a completed batch job."""
    service = BatchService()
    if not batch_id:
        batch_id = service._get_last_batch_job_id()
        if not batch_id:
            click.echo("No batch ID provided and no previous batch job found.")
            return
    try:
        result = service.retrieve_results(batch_id, output_dir)
        click.echo(result)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
