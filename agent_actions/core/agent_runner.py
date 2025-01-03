from agent_actions.handlers.agent_handlers import AgentManager

class AgentRunner:
    def __init__(self, use_tools):
        self.use_tools = use_tools
        self.failed = False

    def run_agent(self, agent_config, agent_name, previous_agent_type, idx):
        try:
            loader = 'staging_loader' if idx == 0 else 'target_loader'
            function_name = 'generate_staging' if idx == 0 else 'generate_target'

            output_folder = AgentManager.process_and_generate_for_agent(
                agent_config, agent_name, previous_agent_type, loader, function_name
            )
            return output_folder
        except Exception as e:
            self.failed = True
            raise
