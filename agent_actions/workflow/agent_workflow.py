import sys
from pathlib import Path
from agent_actions.handlers.config_handler import ConfigManager
from agent_actions.core.agent_runner import AgentRunner
from agent_actions.processors.output_processor.output_processor import OutputProcessor
from agent_actions.services.batch_service import BatchService
from agent_actions.constants import PROMPT_KEY, SCHEMA_NAME_KEY

from rich.console import Console
from rich.table import Table
from rich.live import Live


class AgentWorkflow:
    def __init__(self, constructor_path, user_code_path, default_path, use_tools,
                 parent_output=None, parent_source=None, parent_pipeline=None, batch_continue=False):
        self.constructor_path = constructor_path
        self.user_code_path = user_code_path
        self.default_path = default_path
        self.use_tools = use_tools
        self.parent_output = parent_output
        self.parent_source = parent_source
        self.parent_pipeline = parent_pipeline
        self.batch_continue = batch_continue

        self.current_agent_idx = 0
        self.previous_agent_type = None
        self.ephemeral_directories = []
        self.failed = False

        if self.user_code_path:
            abs_user_code_path = str(Path(self.user_code_path).resolve())
            if abs_user_code_path not in sys.path:
                sys.path.insert(0, abs_user_code_path)

        # Initialize components
        self.config_manager = ConfigManager(self.constructor_path, self.default_path)
        self.agent_runner = AgentRunner(self.use_tools)
        self.output_processor = OutputProcessor(self.parent_output, self.constructor_path)
        self.batch_service = BatchService()

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
        table.add_column("Schema", justify="left", style="magenta", max_width=40)

        for idx, (agent_name, details) in enumerate(self.agent_status.items(), start=1):
            agent_config = self.agent_configs[agent_name]
            schema = str(agent_config.get(SCHEMA_NAME_KEY, 'No schema specified'))

            table.add_row(
                str(idx),
                agent_name,
                details["status"],
                schema
            )

        return table

    def _handle_batch_agent(self, agent_config, agent_type, idx):
        """Handle batch agent processing during workflow execution."""
        # Generate the expected output directory for this agent
        agent_io_path = Path(self.config_manager.agent_name) / "agent_io"
        output_directory = agent_io_path / "target" / f"node_{idx}_{agent_type}"
        
        # Check if there's a completed batch for this specific agent
        processed_files = self.batch_service.check_and_process_completed_batches(
            str(output_directory),
            str(agent_io_path)
        )
        
        if processed_files:
            self.console.print(f"[green]✅ Processed batch results for {agent_type}[/green]")
            return str(output_directory)
        else:
            # Check if there's an in-flight batch job
            batch_id = self.batch_service._get_last_batch_job_id(str(output_directory))
            if batch_id:
                try:
                    status = self.batch_service.check_status(batch_id)
                    if status in ['validating', 'in_progress', 'finalizing']:
                        self.console.print(f"[yellow]Batch job {batch_id} still {status} for {agent_type}[/yellow]")
                        return None  # Batch not ready
                    elif status == 'completed':
                        # Try processing again
                        processed_files = self.batch_service.check_and_process_completed_batches(
                            str(output_directory),
                            str(agent_io_path)
                        )
                        if processed_files:
                            self.console.print(f"[green]✅ Processed completed batch for {agent_type}[/green]")
                            return str(output_directory)
                except Exception as e:
                    self.console.print(f"[red]Error checking batch status: {e}[/red]")
            
            # No batch found or batch failed - run normally
            is_last_agent = idx == len(self.execution_order) - 1
            return self.agent_runner.run_agent(
                agent_config, 
                self.agent_name, 
                self.previous_agent_type,
                idx,
                is_last_agent
            )

    def run(self):
        try:
            with Live(self.create_status_table(), refresh_per_second=2, console=self.console) as live:
                # Get total number of agents
                total_agents = len(self.execution_order)

                for idx, agent_type in enumerate(self.execution_order):
                    agent_config = self.agent_configs[agent_type]
                    self.agent_status[agent_type]["status"] = "⏳ Running"
                    self.agent_status[agent_type]["prompt"] = agent_config.get(PROMPT_KEY, 'No prompt specified')

                    # Update live display
                    live.update(self.create_status_table())

                    # Check if this is a batch agent and we're in batch_continue mode
                    if self.batch_continue and agent_config.get('run_mode') == 'batch':
                        output_folder = self._handle_batch_agent(agent_config, agent_type, idx)
                        if output_folder is None:
                            # Batch not ready, skip this agent for now
                            self.agent_status[agent_type]["status"] = "⏸️ Batch Pending"
                            live.update(self.create_status_table())
                            # Don't add to ephemeral_directories, but do update previous_agent_type
                            self.previous_agent_type = agent_type
                            continue
                    else:
                        # Check if this is the last agent
                        is_last_agent = idx == total_agents - 1

                        # Regular agent processing (or batch agent in normal mode)
                        output_folder = self.agent_runner.run_agent(
                            agent_config, 
                            self.agent_name, 
                            self.previous_agent_type,
                            idx,  # Current index
                            is_last_agent  # Flag indicating if this is the last agent
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
            self.console.print(f"\n❌ [bold red]Workflow failed with error:[/bold red] {e}")
            self.failed = True
            raise