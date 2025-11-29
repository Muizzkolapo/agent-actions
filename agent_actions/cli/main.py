"""
Main entry point for the Agent Actions CLI.

This module provides the primary entry point for the CLI application,
handling command registration, initialization, and execution.
"""
import sys
import logging
import signal
from typing import Optional, Sequence, List
import click

from agent_actions.logging import LoggerFactory, LoggingConfig
from agent_actions.cli.test import clean_cli as clean
from agent_actions.cli.init import init
from agent_actions.cli.compile import render
from agent_actions.cli.run import run
from agent_actions.llm_invocation.batch.batch_cli import batch  # CLI command group for batch processing operations
from agent_actions.cli.status import status
from agent_actions.cli.list_udfs import list_udfs_cmd
from agent_actions.validation.validate_udfs import validate_udfs_cmd
from agent_actions.shared.exceptions import ProjectNotFoundError
__version__ = '1.0.0'

class CLI:
    """Agent Actions CLI application."""

    def __init__(self) -> None:
        """Initialize the CLI application."""
        # Use standard logger initially; will be replaced with LoggerFactory logger
        # after _configure_logging is called
        self.logger = logging.getLogger(__name__)
        self.click_group = self._create_click_group()
        self._register_commands()
        self._register_signal_handlers()

    def _create_click_group(self) -> click.Group:
        """Create the main click group with global options."""

        @click.group(name='agent-actions')
        @click.version_option(version=__version__)
        @click.option('--debug', is_flag=True, help='Enable debug mode with verbose logging and source file/line references (for developers)')
        @click.option('-v', '--verbose', is_flag=True, help='Enable verbose output')
        def group(debug: bool, verbose: bool) -> None:
            """Agent Actions CLI tool for managing and running agent workflows."""
            pass

        return group

    def _register_commands(self) -> None:
        """Register all available commands with the CLI."""
        self.logger.debug('Registering CLI commands')
        self.click_group.add_command(clean)
        self.click_group.add_command(init)
        self.click_group.add_command(render)
        self.click_group.add_command(run)
        self.click_group.add_command(batch)
        self.click_group.add_command(status)
        self.click_group.add_command(list_udfs_cmd)
        self.click_group.add_command(validate_udfs_cmd)

    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown."""
        try:
            signal.signal(signal.SIGINT, self._handle_termination)
            signal.signal(signal.SIGTERM, self._handle_termination)
            if hasattr(signal, 'SIGBREAK'):
                signal.signal(signal.SIGBREAK, self._handle_termination)
            self.logger.debug('Signal handlers registered successfully')
        except (AttributeError, ValueError) as e:
            self.logger.warning(f'Failed to register signal handlers: {str(e)}')

    def _handle_termination(self, signum: int, frame) -> None:
        """
        Handle termination signals gracefully.

        Args:
            signum: Signal number
            frame: Current stack frame (unused but required by signal handler signature)
        """
        signal_name = signal.Signals(signum).name
        self.logger.info(f'Received termination signal: {signal_name}')
        print(f'\nOperation interrupted by {signal_name}. Exiting gracefully...')
        sys.exit(130)

    def _configure_logging(self, argv: List[str]) -> None:
        """
        Configure logging based on command-line arguments.

        Uses LoggerFactory for centralized logging configuration with
        correlation context, structured formatting, and credential redaction.

        Args:
            argv: Command-line arguments
        """
        debug_mode = '--debug' in argv
        verbose_mode = '--verbose' in argv or '-v' in argv

        # Determine log level
        if debug_mode:
            level = 'DEBUG'
        elif verbose_mode:
            level = 'INFO'
        else:
            level = 'INFO'  # Default to INFO (not CRITICAL)

        # Determine source location setting (only in debug mode)
        include_source = debug_mode

        # Initialize LoggerFactory with configuration
        # This respects AGENT_ACTIONS_LOG_LEVEL env var if set
        config = LoggingConfig.from_environment()
        if debug_mode or verbose_mode:
            # CLI flags override environment - update both default and handler levels
            config.default_level = level
            for handler in config.handlers:
                handler.level = level

        # Set source location based on debug mode
        if debug_mode:
            config.include_source_location = include_source
            config.file_log_level = 'DEBUG'

        LoggerFactory.initialize(config=config, force=True)
        self.logger = LoggerFactory.get_logger('cli')

    def _show_version_and_exit(self) -> int:
        """Display version information and return exit code."""
        print(f'Agent Actions CLI v{__version__}')
        return 0

    def execute(self, argv: Optional[Sequence[str]]=None) -> int:
        """
        Execute the CLI application with the provided arguments.
        
        Args:
            argv: Command-line arguments (uses sys.argv if None)
            
        Returns:
            Exit code (0 for success, non-zero for failure)
        """
        try:
            if argv is None:
                argv = sys.argv[1:]
            if '--version' in argv or '-V' in argv:
                return self._show_version_and_exit()
            self._configure_logging(argv)
            self.logger.info('Starting agent-actions CLI', extra={'version': __version__, 'cli_args': argv})
            self.click_group.main(argv, standalone_mode=False)
            self.logger.info('CLI execution completed successfully')
            return 0
        except click.Abort:
            self.logger.info('Operation aborted by user')
            return 130
        except click.UsageError as e:
            self.logger.error(f'Usage error: {str(e)}')
            print(f'Error: {str(e)}', file=sys.stderr)
            return 2
        except ProjectNotFoundError as e:
            self.logger.info('Not in project directory')
            context = e.context if hasattr(e, 'context') else {}
            marker_file = context.get('marker_file', 'agent_actions.yml')
            search_path = context.get('search_path', 'unknown')
            solution_1 = context.get('solution_1', 'Navigate to your agent-actions project directory')
            solution_2 = context.get('solution_2', "Run 'agent-actions init' to create a new project")
            error_msg = f"Not in an agent-actions project\n\nCould not find '{marker_file}' in current directory or any parent directory.\n\nCurrent directory: {search_path}\n\nSolutions:\n  1. {solution_1}\n  2. {solution_2}"
            print(click.style('Error: ', fg='red', bold=True) + error_msg, file=sys.stderr)
            return 1
        except Exception as e:
            from agent_actions.shared.user_errors import format_user_error
            self.logger.error('CLI execution failed', extra={'error': str(e)}, exc_info=True)
            context = {'command': argv[0] if argv else 'agent-actions', 'operation': 'cli_execution'}
            error_message = format_user_error(e, context)
            print(f'Error: {error_message}', file=sys.stderr)
            if '--debug' in (argv or []):
                from agent_actions.utilities.safe_format import format_exception_chain_for_debug
                self.logger.debug("Debug Information:")
                self.logger.debug("Exception Chain:")
                self.logger.debug("%s", format_exception_chain_for_debug(e))
                self.logger.debug("Full Traceback:", exc_info=True)
            return 1

def _print_help_callback(ctx, param, value):
    """Callback to handle -h flag by printing help."""
    if value:
        click.echo(ctx.get_help())
        ctx.exit()

@click.group()
@click.version_option(version=__version__)
@click.option('--debug', is_flag=True, help='Enable debug mode with verbose logging and source file/line references (for developers)')
@click.option('-v', '--verbose', is_flag=True, help='Enable verbose output')
@click.option('-h', is_flag=True, expose_value=False, is_eager=True, callback=_print_help_callback, help='Show this message and exit.')
def cli(debug: bool, verbose: bool) -> None:
    """
    Agent Actions CLI tool for managing and running agent workflows.

    Use --help with any command for more information.
    """
    pass
cli.add_command(clean)
cli.add_command(init)
cli.add_command(render)
cli.add_command(run)
cli.add_command(batch)
cli.add_command(status)

def main_entrypoint(argv: Optional[Sequence[str]]=None) -> int:
    """
    Main entry point for the CLI application.
    
    Args:
        argv: Command-line arguments (uses sys.argv if None)
        
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    app = CLI()
    return app.execute(argv)

def main() -> None:
    """
    Entry point for the CLI tool when run from the command line.
    Exits with appropriate status code.
    """
    sys.exit(main_entrypoint())
if __name__ == '__main__':
    main()