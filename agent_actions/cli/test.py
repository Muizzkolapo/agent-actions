import click
from agent_actions.llm_invocation.realtime.cleaner import Cleaner
from agent_actions.validation.clean_validator import CleanCommandArgs
from agent_actions.cli.cli_decorators import requires_project
from pydantic import ValidationError

@click.command(name='clean', help='Remove temporary directories created by an agent. By default removes source and target directories only.')
@click.option('-a', '--agent', required=True, metavar='<agent>', help='Name of the agent whose workspace should be cleaned.')
@click.option('-f', '--force', is_flag=True, default=False, help='Skip interactive confirmation.')
@click.option('--all', is_flag=True, default=False, help='Remove all directories including staging.')
@requires_project
def clean_cli(agent: str, force: bool, all: bool) -> None:
    """
    CLI entrypoint for 'clean'.

    Delegates to Cleaner class to execute the cleaning workflow.
    Default behavior removes source and target directories.
    Use --all flag to also remove staging directory.
    """
    try:
        args = CleanCommandArgs(agent=agent, force=force, all=all)
        Cleaner(agent=args.agent, force=args.force, remove_all=args.all).run()
    except ValidationError as e:
        from agent_actions.core.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'clean', 'agent': agent})
        raise click.ClickException(error_message)