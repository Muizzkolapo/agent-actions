from abc import ABC, abstractmethod
from agent_actions.processors.staging_loader import generate_staging
from agent_actions.processors.target_loader import generate_target

class AgentStrategy(ABC):
    @abstractmethod
    def execute(self, agent_config, agent_name, file_path, base_directory, output_directory):
        pass

class InitialStrategy(AgentStrategy):
    def execute(self, agent_config, agent_name, file_path, base_directory, output_directory):
        return generate_staging(agent_config, agent_name, file_path, base_directory, output_directory)

class TerminalStrategy(AgentStrategy):
    def execute(self, agent_config, agent_name, file_path, base_directory, output_directory):
        return generate_target(agent_config, agent_name, file_path, base_directory, output_directory)

class IntermediateStrategy(AgentStrategy):
    def execute(self, agent_config, agent_name, file_path, base_directory, output_directory):
        # Similar to TerminalStrategy but might have different processing logic
        return generate_target(agent_config, agent_name, file_path, base_directory, output_directory) 