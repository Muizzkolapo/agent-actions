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
from agent_actions.cli.exceptions import PermissionError


class DocsCommand:
    """Implementation of the docs command."""
    
    def __init__(self, host: str, port: int, debug: bool, open_browser: bool):
        """
        Initialize the docs command.
        
        Args:
            host: Host address to serve documentation.
            port: Port number to serve documentation.
            debug: Whether to run the server in debug mode.
            open_browser: Whether to open the browser automatically.
        """
        self.host = host
        self.port = port
        self.debug = debug
        self.open_browser = open_browser
    
    def _validate_port_available(self) -> bool:
        """
        Check if the specified port is available.
        
        Returns:
            True if the port is available, False otherwise.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((self.host, self.port))
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
                    s.bind((self.host, port))
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
                alternative_port = self._find_available_port(self.port + 1)
                if alternative_port:
                    click.echo(
                        f"Port {self.port} is not available, using port {alternative_port} instead"
                    )
                    self.port = alternative_port
                else:
                    raise click.ClickException(
                        f"Port {self.port} is not available. Please specify a different port."
                    )
            
            # Construct the URL
            url = f"http://{self.host if self.host != '0.0.0.0' else 'localhost'}:{self.port}"
            
            # Print out information
            click.echo(f"Starting documentation server at {url}")
            click.echo("Press Ctrl+C to stop the server")
            
            # Open browser if requested
            if self.open_browser:
                self._open_browser_tab(url)
            
            # Run the documentation server
            run_app(self.host, self.port, self.debug)
            
        except PermissionError as e:
            raise click.ClickException(f"Permission denied: {str(e)}")
            
        except Exception as e:
            raise click.ClickException(f"Failed to run documentation server: {str(e)}")


@click.command()
@click.option('--host', default='0.0.0.0', help='Host for the documentation server.')
@click.option('--port', default=8000, type=int, help='Port for the documentation server.')
@click.option('--debug', is_flag=True, default=False, help='Run the server in debug mode.')
@click.option('--open', 'open_browser', is_flag=True, default=True, 
              help='Open the browser automatically when the server starts.')
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
    command = DocsCommand(host, port, debug, open_browser)
    command.execute()