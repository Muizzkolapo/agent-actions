"""
Clean command for the Agent Actions CLI.

This module provides the implementation of the 'clean' command,
which handles cleaning agent directories.
"""

import click
import logging
from pathlib import Path
from typing import List, Optional

from agent_actions.handlers.agent_handlers import AgentManager
from agent_actions.cli.exceptions import (
    AgentNotFoundError,
    PermissionError
)

logger = logging.getLogger(__name__)


class CleanCommand:
    """Implementation of the clean command."""
    
    def __init__(self, agent: str, force: bool = False):
        """
        Initialize the clean command.
        
        Args:
            agent: Name of the agent to clean.
            force: Whether to force cleaning even if warnings occur.
        """
        self.agent = agent
        self.force = force
        
    def _validate_agent_exists(self) -> None:
        """
        Validate that the specified agent exists.
        
        Raises:
            AgentNotFoundError: If the agent does not exist.
        """
        logger.debug(f"Validating agent existence: {self.agent}")
        # This would need to be implemented in AgentManager
        if not AgentManager.agent_exists(self.agent):
            logger.error(f"Agent does not exist: {self.agent}")
            raise AgentNotFoundError(f"Agent '{self.agent}' does not exist")
    
    def _get_directories_to_clean(self) -> List[Path]:
        """
        Get the list of directories to clean for the agent.
        
        Returns:
            List of directories to clean.
        """
        logger.debug(f"Getting directories to clean for agent: {self.agent}")
        # This would need to be implemented in AgentManager
        return AgentManager.get_agent_directories(self.agent)
    
    def _confirm_cleaning(self, directories: List[Path]) -> bool:
        """
        Confirm with the user whether to proceed with cleaning.
        
        Args:
            directories: List of directories to clean.
            
        Returns:
            True if cleaning is confirmed, False otherwise.
        """
        if self.force:
            return True
            
        # Print directories to be cleaned
        click.echo(f"The following directories for agent '{self.agent}' will be cleaned:")
        for directory in directories:
            click.echo(f"  - {directory}")
            
        # Ask for confirmation
        return click.confirm("Do you want to proceed?", default=False)
    
    def execute(self) -> None:
        """
        Execute the clean command.
        
        Raises:
            Various exceptions depending on what fails.
        """
        logger.info(f"Starting clean command for agent: {self.agent}")
        
        try:
            # Validate that the agent exists
            self._validate_agent_exists()
            
            # Get directories to clean
            directories = self._get_directories_to_clean()
            
            # If no directories to clean, exit early
            if not directories:
                logger.info(f"No directories to clean for agent: {self.agent}")
                click.echo(f"No directories to clean for agent: {self.agent}")
                return
            
            # Confirm cleaning with user (if not forced)
            if not self._confirm_cleaning(directories):
                logger.info("Cleaning canceled by user")
                click.echo("Cleaning canceled.")
                return
            
            # Perform the cleaning
            logger.info(f"Cleaning directories for agent: {self.agent}")
            AgentManager.clean_agent_directories(self.agent)
            
            logger.info(f"Successfully cleaned directories for agent: {self.agent}")
            click.echo(f"Successfully cleaned directories for agent: {self.agent}")
            
        except AgentNotFoundError as e:
            logger.error(f"Agent not found: {str(e)}")
            raise click.ClickException(f"Agent not found: {str(e)}")
            
        except PermissionError as e:
            logger.error(f"Permission denied: {str(e)}")
            raise click.ClickException(f"Permission denied: {str(e)}")
            
        except Exception as e:
            logger.error(f"Failed to clean directories for agent {self.agent}: {str(e)}", 
                         exc_info=True)
            raise click.ClickException(
                f"Failed to clean directories for agent {self.agent}: {str(e)}"
            )


@click.command()
@click.option('-a', '--agent', required=True,
              help="Agent name")
@click.option('-f', '--force', is_flag=True, default=False,
              help="Force cleaning without confirmation")
def clean(agent: str, force: bool = False) -> None:
    """
    Clean agent directories.

    This command removes temporary files and directories associated
    with the specified agent, freeing up disk space and removing
    any artifacts from previous runs.

    Examples:
        agent-actions clean -a my_agent
        agent-actions clean -a my_agent --force
    """
    command = CleanCommand(agent, force)
    command.execute()
