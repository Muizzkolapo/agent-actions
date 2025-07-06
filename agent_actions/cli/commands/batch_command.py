import click
from agent_actions.services.batch_service import BatchService
from agent_actions.cli.validators.batch_validator import BatchCommandArgs
from pydantic import ValidationError

@click.group()
def batch():
    """Manages the lifecycle of batch processing jobs."""
    pass

@batch.command()
@click.option('--batch-id', help='The ID of the batch job to check. If not provided, the last submitted job ID will be used.')
def status(batch_id: str = None):
    """Checks the status of a running batch job."""
    try:
        args = BatchCommandArgs(batch_id=batch_id)
        service = BatchService()
        if not args.batch_id:
            args.batch_id = service._get_last_batch_job_id()
            if not args.batch_id:
                click.echo("No batch ID provided and no previous batch job found.")
                return
        
        status = service.check_status(args.batch_id)
        click.echo(f"Batch job status: {status}")
    except ValidationError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)

@batch.command()
@click.option('--batch-id', help='The ID of the batch job to retrieve. If not provided, the last submitted job ID will be used.')
@click.option('--output-dir', '-o', default='.', type=click.Path(), help='Directory to save the retrieved results.')
def retrieve(batch_id: str = None, output_dir: str = '.'):
    """Retrieves the results of a completed batch job."""
    try:
        args = BatchCommandArgs(batch_id=batch_id, output_dir=output_dir)
        service = BatchService()
        if not args.batch_id:
            args.batch_id = service._get_last_batch_job_id()
            if not args.batch_id:
                click.echo("No batch ID provided and no previous batch job found.")
                return
        
        result = service.retrieve_results(args.batch_id, str(args.output_dir))
        click.echo(result)
    except ValidationError as e:
        raise click.ClickException(str(e))
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
