"""
Documentation command for the Agent Actions CLI.

This module provides the implementation of the 'docs' command,
which handles running the documentation server.
"""

import click
import socket
from typing import Optional
import webbrowser

from agent_actions.docs.app import run_app
from agent_actions.core.exceptions import FileSystemError
from agent_actions.agents.validators.docs_validator import DocsCommandArgs
from agent_actions.core.cli_decorators import requires_project
from pydantic import ValidationError


class DocsCommand:
    """Implementation of the docs command."""
    
    def __init__(self, args: DocsCommandArgs):
        """
        Initialize the docs command.
        
        Args:
            args: Pydantic model containing the command arguments.
        """
        self.args = args
    
    def _validate_port_available(self) -> bool:
        """
        Check if the specified port is available.
        
        Returns:
            True if the port is available, False otherwise.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((self.args.host, self.args.port))
                return True
        except socket.error:
            return False
    
    def _find_available_port(self, start_port: int, max_attempts: int = 10) -> Optional[int]:
        """
        Find an available port starting from the specified port.
        
        Args:
            start_port: Port to start checking from.
            max_attempts: Maximum number of ports to check.
            
        Returns:
            Available port if found, None otherwise.
        """
        for port in range(start_port, start_port + max_attempts):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind((self.args.host, port))
                    return port
            except socket.error:
                continue
        return None
    
    def _open_browser_tab(self, url: str) -> None:
        """
        Open a browser tab with the given URL.
        
        Args:
            url: URL to open.
        """
        try:
            webbrowser.open_new_tab(url)
        except Exception as e:
            click.echo(f"Warning: Failed to open browser: {str(e)}")
    
    def execute(self) -> None:
        """
        Execute the docs command.
        
        Raises:
            Various exceptions depending on what fails.
        """
        try:
            # Check if port is available
            if not self._validate_port_available():
                alternative_port = self._find_available_port(self.args.port + 1)
                if alternative_port:
                    click.echo(
                        f"Port {self.args.port} is not available, using port {alternative_port} instead"
                    )
                    self.args.port = alternative_port
                else:
                    raise click.ClickException(
                        f"Port {self.args.port} is not available. Please specify a different port."
                    )
            
            # Construct the URL
            url = f"http://{self.args.host if self.args.host != '0.0.0.0' else 'localhost'}:{self.args.port}"
            
            # Print out information
            click.echo(f"Starting documentation server at {url}")
            click.echo("Press Ctrl+C to stop the server")
            
            # Open browser if requested
            if self.args.open_browser:
                self._open_browser_tab(url)
            
            # Run the documentation server
            run_app(self.args.host, self.args.port, self.args.debug)
            
        except FileSystemError as e:
            from agent_actions.core.user_errors import format_user_error
            error_message = format_user_error(e, {'command': 'docs serve'})
            raise click.ClickException(error_message)

        except Exception as e:
            from agent_actions.core.user_errors import format_user_error
            error_message = format_user_error(e, {'command': 'docs serve'})
            raise click.ClickException(error_message)


@click.command()
@click.option('--host', default='0.0.0.0', help='Host for the documentation server.')
@click.option('--port', default=8000, type=int, help='Port for the documentation server.')
@click.option('--debug', is_flag=True, default=False, help='Run the server in debug mode.')
@click.option('--open', 'open_browser', is_flag=True, default=True,
              help='Open the browser automatically when the server starts.')
@requires_project
def docs(host: str, port: int, debug: bool, open_browser: bool) -> None:
    """
    Generate or display agent documentation.

    This command starts a web server that serves the generated
    documentation for all agents in the project. The documentation
    includes configuration details, schemas, and usage examples.

    Examples:
        agent-actions docs
        agent-actions docs --port 9000
        agent-actions docs --no-open
    """
    try:
        args = DocsCommandArgs(host=host, port=port, debug=debug, open_browser=open_browser)
        command = DocsCommand(args)
        command.execute()
    except ValidationError as e:
        from agent_actions.core.user_errors import format_user_error
        error_message = format_user_error(e, {'command': 'docs'})
        raise click.ClickException(error_message)
