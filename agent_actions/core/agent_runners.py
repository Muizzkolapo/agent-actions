import os
import sys
import json
import shutil
from agent_actions.handlers.agent_handlers import AgentManager
from agent_actions.handlers.config_handler import ConfigManager
from rich.console import Console
from rich.table import Table
from rich.live import Live



class AgentRunner:
    def __init__(self, use_tools):
        self.use_tools = use_tools
        self.failed = False

    def run_agent(self, agent_config, agent_name, previous_agent_type, idx, total_agents):
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


class OutputProcessor:
    def __init__(self, parent_output, constructor_path):
        self.parent_output = parent_output
        self.constructor_path = constructor_path
        self.failed = False

    def combine_json_arrays(self,dir_1, dir_2, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        
        files_dir_1 = set([f for f in os.listdir(dir_1) if f.endswith('.json')])
        files_dir_2 = set([f for f in os.listdir(dir_2) if f.endswith('.json')])
        
        common_files = files_dir_1.intersection(files_dir_2)
        
        for filename in common_files:
            file_path_1 = os.path.join(dir_1, filename)
            file_path_2 = os.path.join(dir_2, filename)
            
            with open(file_path_1, 'r') as f1:
                data1 = json.load(f1)
            with open(file_path_2, 'r') as f2:
                data2 = json.load(f2)
            
            combined_data = data1 + data2
            
            output_path = os.path.join(output_dir, filename)
            with open(output_path, 'w') as out_f:
                json.dump(combined_data, out_f, indent=2)
        
        files_only_in_dir_1 = files_dir_1 - common_files
        for filename in files_only_in_dir_1:
            file_path_1 = os.path.join(dir_1, filename)
            with open(file_path_1, 'r') as f:
                data = json.load(f)
            output_path = os.path.join(output_dir, filename)
            with open(output_path, 'w') as out_f:
                json.dump(data, out_f, indent=2)
            print(f"Copied {filename} from dir_1 to {output_path}")
        
        files_only_in_dir_2 = files_dir_2 - common_files
        for filename in files_only_in_dir_2:
            file_path_2 = os.path.join(dir_2, filename)
            with open(file_path_2, 'r') as f:
                data = json.load(f)
            output_path = os.path.join(output_dir, filename)
            with open(output_path, 'w') as out_f:
                json.dump(data, out_f, indent=2)
            print(f"Copied {filename} from dir_2 to {output_path}")


    def process_final_output(self, ephemeral_directories):
        if not ephemeral_directories:
            return None

        final_agent_output_folder = ephemeral_directories[-1]['output_folder']
        final_workflow_output = os.path.join(os.path.dirname(final_agent_output_folder), 'final_workflow_output')
        os.makedirs(final_workflow_output, exist_ok=True)

        side_output_dir = os.path.join(os.path.dirname(final_agent_output_folder), 'side_output')

        if os.path.exists(side_output_dir):
            self.combine_json_arrays(final_agent_output_folder, side_output_dir, final_workflow_output)
        else:
            pass
            # Option 1: Skip the combination step
            # shutil.copytree(final_agent_output_folder, final_workflow_output)
            
            # Option 2: Create the side_output_dir if it doesn't exist
            # os.makedirs(side_output_dir, exist_ok=True)
            # self.combine_json_arrays(final_agent_output_folder, side_output_dir, final_workflow_output)
   



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

                # Process final output
                self.output_processor.process_final_output(self.ephemeral_directories)

            # Move the completion message outside the 'with Live' block
            self.console.print("\n🎉 [bold green]Workflow Complete[/bold green]")
        except Exception as e:
            pass
            self.console.print(f"\n❌ [bold red]Workflow failed with error:[/bold red] {e}")
            self.failed = True
            raise
