"""
Main entry point for the Agent Actions CLI.

This module provides the primary entry point for the CLI application,
handling command registration, initialization, and execution.
"""

import sys
import logging
import signal
from typing import Optional, Sequence, List, Any

import click

# Import commands
from agent_actions.tasks.test import clean_cli as clean
from agent_actions.tasks.docs import docs
from agent_actions.tasks.init import init
from agent_actions.tasks.compile import render
from agent_actions.tasks.run import run
from agent_actions.tasks.batch import batch
from agent_actions.tasks.status import status

# Version information
__version__ = '1.0.0'


class CLI:
    """Agent Actions CLI application."""
    
    def __init__(self) -> None:
        """Initialize the CLI application."""
        self.logger = logging.getLogger(__name__)
        self.click_group = click.Group(name='agent-actions')
        self._register_commands()
        self._register_signal_handlers()
    
    def _register_commands(self) -> None:
        """Register all available commands with the CLI."""
        self.logger.debug("Registering CLI commands")
        self.click_group.add_command(clean)
        self.click_group.add_command(docs)
        self.click_group.add_command(init)
        self.click_group.add_command(render)
        self.click_group.add_command(run)
        self.click_group.add_command(batch)
        self.click_group.add_command(status)
    
    def _register_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown."""
        try:
            signal.signal(signal.SIGINT, self._handle_termination)
            signal.signal(signal.SIGTERM, self._handle_termination)
            # SIGBREAK is Windows-specific (Ctrl+Break)
            if hasattr(signal, 'SIGBREAK'):
                signal.signal(signal.SIGBREAK, self._handle_termination)
            self.logger.debug("Signal handlers registered successfully")
        except (AttributeError, ValueError) as e:
            # This might happen in environments where signals aren't available
            self.logger.warning(f"Failed to register signal handlers: {str(e)}")
    
    def _handle_termination(self, signum: int, frame: Any) -> None:
        """
        Handle termination signals gracefully.
        
        Args:
            signum: Signal number
            frame: Current stack frame
        """
        signal_name = signal.Signals(signum).name
        self.logger.info(f"Received termination signal: {signal_name}")
        print(f"\nOperation interrupted by {signal_name}. Exiting gracefully...")
        sys.exit(130)  # Standard exit code for termination by Ctrl+C
    
    def _configure_logging(self, argv: List[str]) -> None:
        """
        Configure logging based on command-line arguments.
        
        Args:
            argv: Command-line arguments
        """
        # Extract log level from arguments
        debug_mode = '--debug' in argv
        verbose_mode = '--verbose' in argv or '-v' in argv

        if debug_mode:
            level = logging.DEBUG
        elif verbose_mode:
            level = logging.INFO
        else:
            level = logging.CRITICAL  # Only show critical system errors to users

        logging.basicConfig(level=level)
        self.logger.setLevel(level)
        

    
    def _show_version_and_exit(self) -> int:
        """Display version information and return exit code."""
        print(f"Agent Actions CLI v{__version__}")
        return 0
    
    def execute(self, argv: Optional[Sequence[str]] = None) -> int:
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
            
            # Handle version flag
            if '--version' in argv or '-V' in argv:
                return self._show_version_and_exit()
            
            # Set up logging before any other operations
            self._configure_logging(argv)
            
            # Log startup information
            self.logger.info("Starting agent-actions CLI", extra={
                'version': __version__,
                'args': argv
            })
            
            # Execute command with standalone_mode=False to avoid SystemExit
            self.click_group.main(argv, standalone_mode=False)
            
            self.logger.info("CLI execution completed successfully")
            return 0
            
        except click.Abort:
            # User initiated abort (e.g., via Ctrl+C in an interactive prompt)
            self.logger.info("Operation aborted by user")
            return 130
            
        except click.UsageError as e:
            # Command-line usage error
            self.logger.error(f"Usage error: {str(e)}")
            print(f"Error: {str(e)}", file=sys.stderr)
            return 2
            
        except Exception as e:
            # Unexpected error - use user-friendly formatting
            from agent_actions.core.user_errors import format_user_error

            self.logger.error("CLI execution failed", extra={'error': str(e)}, exc_info=True)

            # Format user-friendly error message
            context = {
                'command': argv[0] if argv else 'agent-actions',
                'operation': 'cli_execution'
            }

            error_message = format_user_error(e, context)
            print(f"Error: {error_message}", file=sys.stderr)

            # Show debug info if requested
            if '--debug' in (argv or []):
                print("\n--- Debug Information ---", file=sys.stderr)
                import traceback
                traceback.print_exc()

            return 1


def _print_help_callback(ctx, param, value):
    """Callback to handle -h flag by printing help."""
    if value:
        click.echo(ctx.get_help())
        ctx.exit()


@click.group()
@click.version_option(version=__version__)
@click.option('--debug', is_flag=True, help='Enable debug mode with verbose logging')
@click.option('-v', '--verbose', is_flag=True, help='Enable verbose output')
@click.option('-h', is_flag=True, expose_value=False, is_eager=True, callback=_print_help_callback, help='Show this message and exit.')
def cli(debug: bool, verbose: bool) -> None:
    """
    Agent Actions CLI tool for managing and running agent workflows.

    Use --help with any command for more information.
    """
    pass


# Register commands with the main cli group
cli.add_command(clean)
cli.add_command(docs)
cli.add_command(init)
cli.add_command(render)
cli.add_command(run)
cli.add_command(batch)
cli.add_command(status)


def main_entrypoint(argv: Optional[Sequence[str]] = None) -> int:
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


if __name__ == "__main__":
    main()