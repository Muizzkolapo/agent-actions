import os
import sys
import json
import yaml
import shutil
from collections import OrderedDict
from agent_actions.core.utils import Utils
from agent_actions.handlers.agent_handlers import AgentManager
from agent_actions.handlers.config_handler import ConfigValidator
from agent_actions.handlers.file_handler import FileHandler
from agent_actions.logging_setup import setup_logging
from rich.console import Console
from rich.table import Table
from time import sleep  # Simulate time for agent processing

logger = setup_logging()


class ConfigManager:
    def __init__(self, constructor_path, default_path):
        self.constructor_path = constructor_path
        self.default_path = default_path
        self.user_config = None
        self.default_config = None
        self.agent_name = None
        self.agent_configs = {}
        self.execution_order = []
        self.child_pipeline = None
        self.logs = []

    def _log(self, message, level='info'):
        self.logs.append((level, message))

    def load_configs(self):
        try:
            with open(self.constructor_path, 'r', encoding='utf-8') as file:
                self.user_config = yaml.safe_load(file)
        except Exception as e:
            self._log(f"Error loading constructor config: {self.constructor_path}, Error: {e}", level='error')
            raise

        try:
            with open(self.default_path, 'r', encoding='utf-8') as file:
                self.default_config = yaml.safe_load(file)
        except Exception as e:
            self._log(f"Error loading default config: {self.default_path}, Error: {e}", level='error')
            raise

    def validate_agent_name(self):
        self.agent_name = ConfigValidator.find_agent_name(self.user_config)
        config_filename = os.path.splitext(os.path.basename(self.constructor_path))[0]
        if self.agent_name != config_filename:
            error_msg = f"Top-level key '{self.agent_name}' does not match the filename '{config_filename}'"
            self._log(error_msg, level='error')
            raise ValueError(error_msg)

    def check_child_pipeline(self):
        for item in self.user_config[self.agent_name]:
            if isinstance(item, dict) and 'child' in item:
                self.child_pipeline = item['child'][0]
                return
        self.child_pipeline = None

    def get_user_agents(self):
        agents_section = self.user_config[self.agent_name]
        if 'agents' in agents_section:
            user_agents = agents_section['agents']
        else:
            user_agents = [agent for agent in agents_section if isinstance(agent, dict) and 'agent_type' in agent]
        return user_agents

    def merge_agent_configs(self, user_agents):
        default_agent_config = self.default_config['default_agent_config']
        for agent in user_agents:
            agent_type = agent.get('agent_type')
            if agent_type:
                merged_agent_config = default_agent_config.copy()
                merged_agent_config.update(agent)
                self.agent_configs[agent_type] = merged_agent_config

    def determine_execution_order(self, user_agents):
        dependency_graph = {
            agent['agent_type']: agent.get('dependencies', [])
            for agent in user_agents if 'agent_type' in agent
        }
        self.execution_order = Utils.topological_sort(dependency_graph)


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
        self.agent_status = {agent: "⏳ Loading" for agent in self.execution_order}

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

    def print_table(self):
        self.console.clear()
        table = Table(title="Workflow Execution Status")
        table.add_column("#", justify="center")
        table.add_column("Agent Name", justify="left")
        table.add_column("Status", justify="center")

        for idx, (agent_name, status) in enumerate(self.agent_status.items(), start=1):
            table.add_row(str(idx), agent_name, status)

        self.console.print(table)

    def run(self):
        try:
            total_agents = len(self.execution_order)
            self.print_table()  # Initial display

            for idx, agent_type in enumerate(self.execution_order):
                agent_config = self.agent_configs[agent_type]
                self.agent_status[agent_type] = "⏳ Running"
                self.print_table()  # Show agent as running

                sleep(1)  # Replace with actual processing

                self.agent_status[agent_type] = "✅ Completed"
                self.print_table()  # Show completion

                output_folder = self.agent_runner.run_agent(
                    agent_config, self.agent_name, self.previous_agent_type, idx, total_agents
                )
                self.previous_agent_type = agent_type
                self.ephemeral_directories.append({
                    'output_folder': output_folder,
                    'ephemeral': agent_config.get('ephemeral', False)
                })

            self.output_processor.process_final_output(self.ephemeral_directories)
            self.console.print("\n🎉 Workflow Complete")
        except Exception as e:
            self.failed = True
            for level, message in self.logs:
                getattr(logger, level)(message)
            logger.error(f"Workflow failed with error: {e}")
            raise
