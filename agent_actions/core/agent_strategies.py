"""
Module defining strategy classes for different agent execution patterns.

These strategies implement various approaches for processing agent inputs
and generating outputs based on the agent's position in a workflow.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

from agent_actions.processors.staging_loader import generate_staging
from agent_actions.processors.target_loader import generate_target


class AgentStrategy(ABC):
    """
    Abstract base class for agent execution strategies.
    
    Defines the interface that all agent strategies must implement.
    """
    
    @abstractmethod
    def execute(self, 
               agent_config: Dict[str, Any], 
               agent_name: str, 
               file_path: str, 
               base_directory: str, 
               output_directory: str) -> str:
        """
        Execute the strategy for a specific agent and file.
        
        Args:
            agent_config: Configuration dictionary for the agent
            agent_name: Name of the agent
            file_path: Path to the file being processed
            base_directory: Base input directory
            output_directory: Directory where output should be written
            
        Returns:
            Path to the generated output file
        """
        pass


class InitialStrategy(AgentStrategy):
    """
    Strategy for the initial agent in a workflow.
    
    This strategy typically handles the initial loading and processing of data.
    """
    
    def execute(self, 
               agent_config: Dict[str, Any], 
               agent_name: str, 
               file_path: str, 
               base_directory: str, 
               output_directory: str) -> str:
        """
        Execute the initial agent strategy.
        
        Generates staging data from the input file.
        
        Args:
            agent_config: Configuration dictionary for the agent
            agent_name: Name of the agent
            file_path: Path to the file being processed
            base_directory: Base input directory
            output_directory: Directory where output should be written
            
        Returns:
            Path to the generated output file
        """
        return generate_staging(agent_config, agent_name, file_path, base_directory, output_directory)


class TerminalStrategy(AgentStrategy):
    """
    Strategy for the terminal (final) agent in a workflow.
    
    This strategy typically handles the final processing and output generation.
    """
    
    def execute(self, 
               agent_config: Dict[str, Any], 
               agent_name: str, 
               file_path: str, 
               base_directory: str, 
               output_directory: str) -> str:
        """
        Execute the terminal agent strategy.
        
        Generates final target data from the input file.
        
        Args:
            agent_config: Configuration dictionary for the agent
            agent_name: Name of the agent
            file_path: Path to the file being processed
            base_directory: Base input directory
            output_directory: Directory where output should be written
            
        Returns:
            Path to the generated output file
        """
        return generate_target(agent_config, agent_name, file_path, base_directory, output_directory)


class IntermediateStrategy(AgentStrategy):
    """
    Strategy for intermediate agents in a workflow.
    
    This strategy handles the processing of data between initial and terminal agents.
    """
    
    def execute(self, 
               agent_config: Dict[str, Any], 
               agent_name: str, 
               file_path: str, 
               base_directory: str, 
               output_directory: str) -> str:
        """
        Execute the intermediate agent strategy.
        
        Processes input data and generates intermediate target data.
        
        Args:
            agent_config: Configuration dictionary for the agent
            agent_name: Name of the agent
            file_path: Path to the file being processed
            base_directory: Base input directory
            output_directory: Directory where output should be written
            
        Returns:
            Path to the generated output file
        """
        return generate_target(agent_config, agent_name, file_path, base_directory, output_directory)