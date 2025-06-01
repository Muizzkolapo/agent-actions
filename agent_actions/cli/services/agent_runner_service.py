"""
Agent runner service.

This module provides services for running agent workflows and
managing agent execution.
"""

import os
import logging
import traceback
from pathlib import Path
from typing import Optional, Dict, Any, List, Union, Tuple
from contextlib import contextmanager

from agent_actions.handlers.file_handler import FileHandler
from agent_actions.workflow.agent_workflow import AgentWorkflow

from agent_actions.cli.exceptions import (
    FileNotFoundError,
    AgentExecutionError,
    ConfigurationError
)
from agent_actions.cli.validators.path_validator import PathValidator

logger = logging.getLogger(__name__)


class AgentRunnerService:
    """Service for running agents."""
    
    @staticmethod
    def find_config_file(agent_config_dir: Path, filename: str) -> Optional[Path]:
        """
        Find the configuration file path.

        Args:
            agent_config_dir: Directory containing agent configurations.
            filename: Configuration filename.

        Returns:
            Path to the configuration file if found, None otherwise.
            
        Raises:
            FileNotFoundError: If there's an error accessing the directory.
        """
        logger.debug(f"Searching for config file: {filename} in {agent_config_dir}")
        
        # Validate inputs
        if not agent_config_dir.exists():
            raise FileNotFoundError(f"Agent configuration directory does not exist: {agent_config_dir}")
            
        if not agent_config_dir.is_dir():
            raise FileNotFoundError(f"Agent configuration path is not a directory: {agent_config_dir}")
            
        if not os.access(agent_config_dir, os.R_OK):
            raise FileNotFoundError(f"Agent configuration directory is not readable: {agent_config_dir}")
        
        try:
            full_path_str = FileHandler.find_config_file(str(agent_config_dir), filename)
            
            if full_path_str:
                logger.debug(f"Found config file at: {full_path_str}")
                
                # Verify the file is readable
                config_path = Path(full_path_str)
                if not os.access(config_path, os.R_OK):
                    raise FileNotFoundError(f"Config file is not readable: {config_path}")
                    
                return config_path
                
            logger.debug("Config file not found")
            return None
            
        except Exception as e:
            if isinstance(e, FileNotFoundError):
                raise
                
            logger.error(f"Error finding config file: {str(e)}")
            raise FileNotFoundError(f"Error finding config file: {str(e)}") from e

    @staticmethod
    def validate_user_code_path(user_code: Optional[str]) -> Optional[str]:
        """
        Validate the user code path if provided.
        
        Args:
            user_code: Path to user-defined functions directory.
            
        Returns:
            Validated user code path if provided and valid, None otherwise.
            
        Raises:
            ValidationError: If the user code path is invalid.
        """
        instance = PathValidator()
        return instance.validate(user_code)
    
    @contextmanager
    def _execution_context(agent_name: str):
        """
        Context manager for agent execution to handle cleanup.
        
        Args:
            agent_name: Name of the agent.
            
        Yields:
            None
        """
        logger.debug(f"Setting up execution context for agent: {agent_name}")
        
        try:
            # Any setup steps would go here
            yield
            
        finally:
            # Any cleanup steps would go here
            logger.debug(f"Cleaning up execution context for agent: {agent_name}")

    @staticmethod
    def run_agent_workflow(
        agent_name: str,
        full_path: Path,
        default_config_path: Path,
        user_code: Optional[str],
        parent_pipeline: Optional[str]
    ) -> Dict[str, Any]:
        """
        Run the agent workflow.

        Args:
            agent_name: Name of the agent.
            full_path: Path to the agent configuration file.
            default_config_path: Path to the default configuration file.
            user_code: Path to user-defined functions directory.
            parent_pipeline: Name of the parent pipeline.
            
        Returns:
            Dictionary containing the execution results.
            
        Raises:
            FileNotFoundError: If required files are not found.
            ValidationError: If input validation fails.
            AgentExecutionError: If the agent execution fails.
        """
        logger.info(f"Starting agent workflow for: {agent_name}", extra={
            'agent_name': agent_name,
            'config_path': str(full_path),
            'parent_pipeline': parent_pipeline
        })
        
        # Validate configuration file paths
        if not full_path.exists():
            raise FileNotFoundError(f"Agent configuration file not found: {full_path}")
            
        if not default_config_path.exists():
            raise FileNotFoundError(f"Default configuration file not found: {default_config_path}")
            
        # Validate user code path
        validated_user_code = AgentRunnerService.validate_user_code_path(user_code)
        use_tools = validated_user_code is not None
        
        logger.debug(f"Workflow configuration - Use tools: {use_tools}, Parent pipeline: {parent_pipeline}")
        
        try:
            # Create context for the agent execution
            with AgentRunnerService._execution_context(agent_name):
                workflow = AgentWorkflow(
                    constructor_path=str(full_path),
                    user_code_path=user_code,
                    default_path=str(default_config_path),
                    use_tools=use_tools,
                    parent_pipeline=parent_pipeline
                )
                
                logger.info("Initializing workflow execution...")
                
                # Execute the workflow
                result = workflow.run()
                
                logger.info(f"Successfully completed agent workflow for: {agent_name}")
                return result or {}
                
        except Exception as e:
            # PromptLoader.load_prompt raises ValueError for file not found or format issues.
            # StagingProcessor wraps this in RuntimeError.
            # If the error message from PromptLoader is specific enough, we can catch ValueError here
            # or rely on the RuntimeError from StagingProcessor.
            if isinstance(e, ValueError) and ("Prompt file" in str(e) and "not found" in str(e) or "Prompt directory not found" in str(e) or "Invalid prompt format" in str(e)):
                logger.error(f"Prompt loading error in workflow: {str(e)}", extra={'agent_name': agent_name})
                raise AgentExecutionError(f"Prompt loading failed: {str(e)}") from e # Chain original ValueError

            error_details = {
                'agent_name': agent_name,
                'error': str(e),
                'traceback': traceback.format_exc()
            }

            logger.error(f"Failed to run agent workflow for {agent_name}: {str(e)}",
                         extra=error_details, exc_info=True)

            raise AgentExecutionError(f"Failed to run agent workflow for {agent_name}: {str(e)}") from e
        

  
    @staticmethod
    def get_parent_pipeline(agent_config: List[Dict[str, Any]]) -> Optional[str]:
        """
        Get the parent pipeline from the agent configuration.

        Args:
            agent_config: Agent configuration data.

        Returns:
            Parent pipeline name if found, None otherwise.
            
        Raises:
            ConfigurationError: If the configuration format is invalid or cannot be parsed.
        """
        logger.debug("Starting parent pipeline extraction from agent config")
        
        # Basic validation
        if not isinstance(agent_config, list):
            raise ConfigurationError("Agent configuration must be a list")
        
        try:
            for item in agent_config:
                if not isinstance(item, dict):
                    logger.warning("Non-dictionary item found in agent configuration")
                    continue
                    
                if 'parent' in item:
                    parent_list = item.get('parent')
                    
                    if parent_list is None:
                        logger.warning("Empty parent field found in configuration")
                        continue
                        
                    if not isinstance(parent_list, list):
                        logger.warning(f"Parent field is not a list: {type(parent_list)}")
                        continue
                        
                    if not parent_list:
                        logger.warning("Parent list is empty")
                        continue
                        
                    parent = parent_list[0]
                    if not isinstance(parent, str):
                        logger.warning(f"Parent is not a string: {type(parent)}")
                        continue
                        
                    logger.debug(f"Found parent pipeline: {parent}")
                    return parent
                    
            logger.debug("No parent pipeline found in configuration")
            return None
            
        except Exception as e:
            logger.error(f"Error parsing parent pipeline from config: {str(e)}")
            raise ConfigurationError(f"Failed to parse parent pipeline: {str(e)}") from e
    
