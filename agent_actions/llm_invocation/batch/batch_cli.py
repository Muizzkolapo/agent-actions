import click
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.validation.batch_validator import BatchCommandArgs
from agent_actions.cli.cli_decorators import requires_project
from pydantic import ValidationError

@click.group()
def batch():
    """
    CLI command group for batch processing operations.

    Manages the lifecycle of batch processing jobs including submission,
    status checking, and result retrieval.
    """
    pass

@batch.command()
@click.option('--batch-id', help='The ID of the batch job to check. If not provided, the last submitted job ID will be used.')
@requires_project
def status(batch_id: str=None):
    """Checks the status of a running batch job."""
    try:
        args = BatchCommandArgs(batch_id=batch_id)
        service = BatchService()
        if not args.batch_id:
            args.batch_id = service._get_last_batch_job_id()
            if not args.batch_id:
                click.echo('No batch ID provided and no previous batch job found.')
                return
        status = service.check_status(args.batch_id)
        click.echo(f'Batch job status: {status}')
    except ValidationError as e:
        from agent_actions.shared.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'batch status'})
        raise click.ClickException(error_message)
    except Exception as e:
        from agent_actions.shared.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'batch status'})
        click.echo(f'Error: {error_message}', err=True)

@batch.command()
@click.option('--batch-id', help='The ID of the batch job to retrieve. If not provided, the last submitted job ID will be used.')
@click.option('--output-dir', '-o', default='.', type=click.Path(), help='Directory to save the retrieved results.')
@requires_project
def retrieve(batch_id: str=None, output_dir: str='.'):
    """Retrieves the results of a completed batch job."""
    try:
        args = BatchCommandArgs(batch_id=batch_id, output_dir=output_dir)
        service = BatchService()
        if not args.batch_id:
            args.batch_id = service._get_last_batch_job_id()
            if not args.batch_id:
                click.echo('No batch ID provided and no previous batch job found.')
                return
        result = service.retrieve_results(args.batch_id, str(args.output_dir))
        click.echo(result)
    except ValidationError as e:
        from agent_actions.shared.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'batch retrieve'})
        raise click.ClickException(error_message)
    except Exception as e:
        from agent_actions.shared.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'batch retrieve'})
        click.echo(f'Error: {error_message}', err=True)