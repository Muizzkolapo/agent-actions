from agent_actions.core.agent_strategies import InitialStrategy, TerminalStrategy, IntermediateStrategy
from agent_actions.handlers.agent_handlers import AgentManager

class AgentRunner:
    def __init__(self, use_tools):
        self.use_tools = use_tools
        # Initialize strategies
        self.strategies = {
            'initial': InitialStrategy(),
            'terminal': TerminalStrategy(),
            'intermediate': IntermediateStrategy()
        }

    def run_agent(self, agent_config, agent_name, previous_agent_type, idx, total_agents):
        """
        Runs an agent with the appropriate strategy based on its position in the workflow.

        Args:
            agent_config (dict): Configuration for the agent
            agent_name (str): Name of the agent
            previous_agent_type (str): Type of the previous agent in workflow
            idx (int): Current agent's index in workflow
            total_agents (int): Total number of agents in workflow (not used anymore)

        Returns:
            str: Path to the output directory
        """
        try:
            # Determine the strategy based on position in workflow
            if idx == 0:
                strategy = self.strategies['initial']
            elif idx == -1:
                strategy = self.strategies['terminal']
            else:
                strategy = self.strategies['intermediate']

            # Process and generate output using the selected strategy
            output_folder = AgentManager.process_and_generate_for_agent(
                agent_config,
                agent_name,
                previous_agent_type,
                strategy
            )
            
            return output_folder

        except Exception as e:
            raise e
