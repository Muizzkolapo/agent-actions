"""
Documentation command for the Agent Actions CLI.
"""

import click
from agent_actions.docs.app import run_app


@click.command()
@click.option('--host', default='0.0.0.0', help='Host for the documentation server.')
@click.option('--port', default=8000, type=int, help='Port for the documentation server.')
@click.option('--debug', is_flag=True, default=False, help='Run the server in debug mode.')
def docs(host: str, port: int, debug: bool) -> None:
    """
    Generate or display agent documentation.

    Args:
        host: Host address to serve documentation.
        port: Port number to serve documentation.
        debug: Whether to run the server in debug mode.
    """
    try:
        run_app(host, port, debug)
    except Exception as e:
        raise ValueError(f"Failed to run documentation server: {str(e)}")