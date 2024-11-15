import os
import sys
import shutil
from agent_actions.handlers.agent_handlers import AgentManager
from agent_actions.handlers.config_handler import ConfigManager
from agent_actions.logging_setup import setup_logging
from rich.console import Console
from rich.table import Table
from rich.live import Live
from time import sleep

logger = setup_logging()


class AgentRunner:
    def __init__(self, use_tools):
        self.use_tools = use_tools
        self.logs = []
        self.failed = False

    def _log(self, message, level='info'):
        self.logs.append((level, message))

    def run_agent(self, agent_config, agent_name, previous_agent_type, idx, total_agents):
        try:
            loader = 'staging_loader' if idx == 0 else 'target_loader'
            function_name = 'generate_staging' if idx == 0 else 'generate_target'

            output_folder = AgentManager.process_and_generate_for_agent(
                agent_config, agent_name, previous_agent_type, loader, function_name
            )
            return output_folder
        except Exception as e:
            self._log(f"Error in agent {agent_config['agent_type']}: {str(e)}", level='error')
            self.failed = True
            raise


class OutputProcessor:
    def __init__(self, parent_output, constructor_path):
        self.parent_output = parent_output
        self.constructor_path = constructor_path
        self.logs = []
        self.failed = False

    def _log(self, message, level='info'):
        self.logs.append((level, message))

    def process_final_output(self, ephemeral_directories):
        if not ephemeral_directories:
            self._log("No agents were executed. No final output generated.", level='warning')
            return None

        final_output_folder = ephemeral_directories[-1]['output_folder']
        final_workflow_output = os.path.join(os.path.dirname(final_output_folder), 'final_workflow_output')
        os.makedirs(final_workflow_output, exist_ok=True)
        self.copy_output_files(final_output_folder, final_workflow_output)

        if self.parent_output:
            self.copy_to_parent_output(final_workflow_output, self.parent_output)

        return final_workflow_output

    def copy_output_files(self, source_dir, destination_dir):
        for file in os.listdir(source_dir):
            shutil.copy(os.path.join(source_dir, file), destination_dir)

    def copy_to_parent_output(self, final_workflow_output, parent_output):
        for item in os.listdir(final_workflow_output):
            src = os.path.join(final_workflow_output, item)
            dst = os.path.join(parent_output, item)
            if os.path.isfile(src):
                shutil.copy2(src, dst)
            elif os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)


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
        self.logs = []
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

    def _log(self, message, level='info'):
        self.logs.append((level, message))

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
            total_agents = len(self.execution_order)

            with Live(self.create_status_table(), refresh_per_second=2, console=self.console) as live:
                for idx, agent_type in enumerate(self.execution_order):
                    agent_config = self.agent_configs[agent_type]
                    self.agent_status[agent_type]["status"] = "⏳ Running"
                    self.agent_status[agent_type]["prompt"] = agent_config.get('prompt', 'No prompt specified')

                    # Update live display
                    live.update(self.create_status_table())

                    # Agent processing
                    output_folder = self.agent_runner.run_agent(
                        agent_config, self.agent_name, self.previous_agent_type, idx, total_agents
                    )

                    self.agent_status[agent_type]["status"] = "✅ Completed"
                    live.update(self.create_status_table())

                    self.previous_agent_type = agent_type
                    self.ephemeral_directories.append({
                        'output_folder': output_folder,
                        'ephemeral': agent_config.get('ephemeral', False)
                    })

            # Move the completion message outside the 'with Live' block
            self.console.print("\n🎉 [bold green]Workflow Complete[/bold green]")
        except Exception as e:
            self.failed = True
            for level, message in self.logs:
                getattr(logger, level)(message)
            logger.error(f"Workflow failed with error: {e}")
            self.console.print(f"\n❌ [bold red]Workflow failed with error:[/bold red] {e}")
            raise
