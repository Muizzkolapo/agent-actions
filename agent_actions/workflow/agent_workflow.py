import sys
from agent_actions.handlers.config_handler import ConfigManager
from agent_actions.core.agent_runner import AgentRunner
from agent_actions.processors.output_processor import OutputProcessor
from rich.console import Console
from rich.table import Table
from rich.live import Live


class AgentWorkflow:
    def __init__(self, constructor_path, user_code_path, default_path, use_tools,
                 parent_output=None, parent_source=None, parent_pipeline=None):
        self.constructor_path = constructor_path
        self.user_code_path = user_code_path
        self.default_path = default_path
        self.use_tools = use_tools
        self.parent_output = parent_output
        self.parent_source = parent_source
        self.parent_pipeline = parent_pipeline

        self.current_agent_idx = 0
        self.previous_agent_type = None
        self.ephemeral_directories = []
        self.failed = False

        if self.user_code_path and self.user_code_path not in sys.path:
            sys.path.insert(0, self.user_code_path)

        # Initialize components
        self.config_manager = ConfigManager(self.constructor_path, self.default_path)
        self.agent_runner = AgentRunner(self.use_tools)
        self.output_processor = OutputProcessor(self.parent_output, self.constructor_path)

        # Load configurations and setup agents dynamically
        self._load_configs()

        # For real-time status updates in the console
        self.console = Console()
        self.agent_status = {agent: {"status": "⏳ Pending", "prompt": ""} for agent in self.execution_order}
        self.live_display = None

    def _load_configs(self):
        self.config_manager.load_configs()
        self.config_manager.validate_agent_name()
        self.config_manager.check_child_pipeline()
        user_agents = self.config_manager.get_user_agents()
        self.config_manager.merge_agent_configs(user_agents)
        self.config_manager.determine_execution_order(user_agents)
        self.agent_name = self.config_manager.agent_name
        self.execution_order = self.config_manager.execution_order
        self.agent_configs = self.config_manager.agent_configs
        self.child_pipeline = self.config_manager.child_pipeline
        

    def create_status_table(self):
        table = Table(title="Workflow Execution Status")
        table.add_column("#", justify="center", style="cyan")
        table.add_column("Agent Name", justify="left", style="green")
        table.add_column("Status", justify="center", style="yellow")
        table.add_column("Prompt", justify="left", style="blue", max_width=60)
        table.add_column("Schema", justify="left", style="magenta", max_width=40)

        for idx, (agent_name, details) in enumerate(self.agent_status.items(), start=1):
            agent_config = self.agent_configs[agent_name]
            schema = str(agent_config.get('schema_name', 'No schema specified'))

            table.add_row(
                str(idx),
                agent_name,
                details["status"],
                details["prompt"],
                schema
            )

        return table

    def run(self):
        try:
            with Live(self.create_status_table(), refresh_per_second=2, console=self.console) as live:
                for idx, agent_type in enumerate(self.execution_order):
                    agent_config = self.agent_configs[agent_type]
                    self.agent_status[agent_type]["status"] = "⏳ Running"
                    self.agent_status[agent_type]["prompt"] = agent_config.get('prompt', 'No prompt specified')

                    # Update live display
                    live.update(self.create_status_table())

                    # Agent processing
                    output_folder = self.agent_runner.run_agent(
                        agent_config, 
                        self.agent_name, 
                        self.previous_agent_type, 
                        -1 if idx == len(self.execution_order) - 1 else idx
                    )

                    self.agent_status[agent_type]["status"] = "✅ Completed"
                    live.update(self.create_status_table())

                    self.previous_agent_type = agent_type
                    self.ephemeral_directories.append({
                        'output_folder': output_folder,
                        'ephemeral': agent_config.get('ephemeral', False)
                    })

                # Process final output
                self.output_processor.process_final_output(self.ephemeral_directories)

            # Move the completion message outside the 'with Live' block
            self.console.print("\n🎉 [bold green]Workflow Complete[/bold green]")
        except Exception as e:
            pass
            self.console.print(f"\n❌ [bold red]Workflow failed with error:[/bold red] {e}")
            self.failed = True
            raise
