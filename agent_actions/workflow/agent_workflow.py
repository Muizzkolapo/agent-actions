import sys
import json
import asyncio  # Added for async processing
from pathlib import Path
from datetime import datetime
from agent_actions.handlers.config_handler import ConfigManager
from agent_actions.core.agent_runner import AgentRunner
from agent_actions.processors.output_processor.output_processor import OutputProcessor
from agent_actions.services.batch_service import BatchService
from agent_actions.constants import PROMPT_KEY, SCHEMA_NAME_KEY

from rich.console import Console


class AgentWorkflow:
    async def async_run(self, concurrency_limit=None):
        """
        Run agents in parallel using asyncio. Optionally limit concurrency.
        """
        semaphore = asyncio.Semaphore(concurrency_limit) if concurrency_limit else None
        total_agents = len(self.execution_order)
        self.console.print(f"[async] Found {total_agents} agents to run.")
        results = []
        exceptions = []

        async def run_single_agent(idx, agent_name):
            agent_config = self.agent_configs[agent_name]
            status_details = self.agent_status.get(agent_name, {})
            current_status = status_details.get('status', 'pending')
            start_time = datetime.now()
            self.console.print(f"[async] {start_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} START agent: [bold]{agent_name}[/bold]...")
            if current_status == 'completed':
                self.previous_agent_type = agent_name
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                self.console.print(f"[async] {end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} [yellow]SKIP[/yellow] [bold]{agent_name}[/bold] in {duration:.2f}s")
                return 'completed'
            try:
                if semaphore:
                    async with semaphore:
                        output_folder = await asyncio.to_thread(
                            self.agent_runner.run_agent,
                            agent_config, self.agent_name, self.previous_agent_type, idx, idx == len(self.execution_order) - 1
                        )
                else:
                    output_folder = await asyncio.to_thread(
                        self.agent_runner.run_agent,
                        agent_config, self.agent_name, self.previous_agent_type, idx, idx == len(self.execution_order) - 1
                    )
                self._update_status(agent_name, 'completed')
                self.previous_agent_type = agent_name
                self.ephemeral_directories.append({'output_folder': output_folder, 'ephemeral': agent_config.get('ephemeral', False)})
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                self.console.print(f"[async] {end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} [green]OK[/green] [bold]{agent_name}[/bold] in {duration:.2f}s")
                return 'completed'
            except Exception as e:
                self.console.print(f"[async] [red]Agent '{agent_name}' failed with error: {e}[/red]")
                self._update_status(agent_name, 'failed')
                exceptions.append((agent_name, e))
                return 'failed'

        tasks = [run_single_agent(idx, agent_name) for idx, agent_name in enumerate(self.execution_order)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        self.console.print("\n[bold][async] Workflow Summary:[/bold]")
        for idx, agent_name in enumerate(self.execution_order):
            status = self.agent_status[agent_name]['status']
            color = "green" if status == "completed" else "red" if status == "failed" else "yellow"
            self.console.print(f"- {agent_name}: [{color}]{status}[/{color}]")
        self.output_processor.process_final_output(self.ephemeral_directories)
        self.console.print("\n🎉 [bold green][async] Workflow Complete[/bold green]")
        self.console.print("Done.")
        if exceptions:
            raise Exception(f"Some agents failed: {exceptions}")

    # (rest of class unchanged)

    def __init__(self, constructor_path, user_code_path, default_path, use_tools,
                 parent_output=None, parent_source=None, parent_pipeline=None):
        self.constructor_path = constructor_path
        self.user_code_path = user_code_path
        self.default_path = default_path
        self.use_tools = use_tools
        self.parent_output = parent_output
        self.parent_source = parent_source
        self.parent_pipeline = parent_pipeline

        self.previous_agent_type = None
        self.ephemeral_directories = []
        self.failed = False

        self.config_manager = ConfigManager(self.constructor_path, self.default_path)
        self._load_configs()

        if self.user_code_path:
            abs_user_code_path = str(Path(self.user_code_path).resolve())
            if abs_user_code_path not in sys.path:
                sys.path.insert(0, abs_user_code_path)
        elif self.config_manager.tool_path:
            for path in self.config_manager.tool_path:
                abs_tool_path = str(Path(path).resolve())
                if abs_tool_path not in sys.path:
                    sys.path.insert(0, abs_tool_path)

        self.agent_runner = AgentRunner(self.use_tools)
        self.output_processor = OutputProcessor(self.parent_output, self.constructor_path)
        self.batch_service = BatchService()

        self.status_file = Path(self.agent_runner.get_agent_folder(self.agent_name)) / ".agent_status.json"
        self._load_status()

        self.console = Console()

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

    def _load_status(self):
        if self.status_file.exists():
            with open(self.status_file, 'r') as f:
                self.agent_status = json.load(f)
        else:
            self.agent_status = {agent: {"status": "pending"} for agent in self.execution_order}

    def _save_status(self):
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.status_file, 'w') as f:
            json.dump(self.agent_status, f, indent=4)

    def _update_status(self, agent_name, status):
        if agent_name not in self.agent_status:
            self.agent_status[agent_name] = {}
        self.agent_status[agent_name]['status'] = status
        self._save_status()

    def _handle_batch_agent(self, agent_name, idx):
        agent_io_path = Path(self.agent_runner.get_agent_folder(self.agent_name))
        output_directory = agent_io_path / "target" / f"node_{idx}_{agent_name}"
        
        # Check overall batch registry status - this is the single source of truth
        registry_status = self.batch_service._get_batch_registry_status(str(output_directory))
        
        if registry_status == 'completed':
            self.console.print(f"[green]All batch jobs are completed. Processing results...[/green]")
            # Process all completed batch jobs in the registry
            self._process_all_batch_results(str(output_directory))
            self.console.print(f"[green]✅ Processed all batch results for {agent_name}[/green]")
            return str(output_directory), 'completed'
        elif registry_status in ['in_progress', 'partial_failed']:
            # Check if all jobs are actually done (some might have completed since last check)
            if self.batch_service._are_all_batch_jobs_completed(str(output_directory)):
                self.console.print(f"[green]All batch jobs are now completed. Processing results...[/green]")
                self._process_all_batch_results(str(output_directory))
                self.console.print(f"[green]✅ Processed all batch results for {agent_name}[/green]")
                return str(output_directory), 'completed'
            else:
                return None, 'in_progress'
        elif registry_status == 'no_batches':
            # No batch registry found - this means the agent didn't submit any batch jobs
            self.console.print(f"[yellow]No batch jobs found for {agent_name}[/yellow]")
            return None, 'failed'
        else:
            return None, 'failed'

    def _process_all_batch_results(self, output_directory):
        """Process all completed batch jobs in the registry together as one dataset."""
        try:
            # Use the new combined processing method
            self.batch_service.process_all_batch_results_to_workflow_output(output_directory)
        except Exception as e:
            self.console.print(f"[yellow]Warning: Could not process batch results: {e}[/yellow]")

    def run(self):
        try:
            workflow_complete = True
            total_agents = len(self.execution_order)
            self.console.print(f"Found {total_agents} agents to run.")

            for idx, agent_name in enumerate(self.execution_order):
                agent_config = self.agent_configs[agent_name]
                status_details = self.agent_status.get(agent_name, {})
                current_status = status_details.get('status', 'pending')

                start_time = datetime.now()
                self.console.print(f"{start_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} START agent: [bold]{agent_name}[/bold]...")

                if current_status == 'completed':
                    self.previous_agent_type = agent_name
                    end_time = datetime.now()
                    duration = (end_time - start_time).total_seconds()
                    self.console.print(f"{end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} [yellow]SKIP[/yellow] [bold]{agent_name}[/bold] in {duration:.2f}s")
                    continue

                workflow_complete = False
                
                if current_status == 'batch_submitted':
                    self._update_status(agent_name, 'checking_batch')
                    
                    output_folder, batch_status = self._handle_batch_agent(agent_name, idx)
                    
                    end_time = datetime.now()
                    duration = (end_time - start_time).total_seconds()

                    if batch_status == 'completed':
                        self._update_status(agent_name, 'completed')
                        self.previous_agent_type = agent_name
                        self.ephemeral_directories.append({'output_folder': output_folder, 'ephemeral': agent_config.get('ephemeral', False)})
                        workflow_complete = True
                        self.console.print(f"{end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} [green]OK[/green] [bold]{agent_name}[/bold] (batch) in {duration:.2f}s")
                        continue
                    elif batch_status == 'in_progress':
                        self._update_status(agent_name, 'batch_submitted')
                        self.console.print(f"\n[yellow]Batch job for '{agent_name}' is still in progress. Run 'agent run' again later.[/yellow]")
                        self.console.print(f"{end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} [yellow]IN PROGRESS[/yellow] [bold]{agent_name}[/bold] (batch) in {duration:.2f}s")
                        break
                    else:
                        self._update_status(agent_name, 'failed')
                        self.console.print(f"\n[red]Batch job for '{agent_name}' failed.[/red]")
                        self.console.print(f"{end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} [red]FAIL[/red] [bold]{agent_name}[/bold] (batch) in {duration:.2f}s")
                        break
                
                self._update_status(agent_name, 'running')

                output_folder = self.agent_runner.run_agent(
                    agent_config, self.agent_name, self.previous_agent_type, idx, idx == len(self.execution_order) - 1
                )

                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()

                if agent_config.get('run_mode') == 'batch':
                    agent_io_path = Path(self.agent_runner.get_agent_folder(self.agent_name))
                    node_output_dir = agent_io_path / "target" / f"node_{idx}_{agent_name}"
                    
                    # Check if batch registry exists to confirm batch jobs were submitted
                    registry_file = Path(node_output_dir) / "batch" / ".batch_registry.json"
                    if registry_file.exists():
                        self._update_status(agent_name, 'batch_submitted')
                        self.console.print(f"\n[yellow]Batch jobs submitted for '{agent_name}'. Run 'agent run' again to check status.[/yellow]")
                        self.console.print(f"{end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} [yellow]SUBMITTED[/yellow] [bold]{agent_name}[/bold] (batch) in {duration:.2f}s")
                    else:
                        self._update_status(agent_name, 'failed')
                        self.console.print(f"\n[red]Agent '{agent_name}' was configured for batch mode, but no batch jobs were found after execution.[/red]")
                        self.console.print(f"{end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} [red]FAIL[/red] [bold]{agent_name}[/bold] in {duration:.2f}s")
                    break
                else:
                    self._update_status(agent_name, 'completed')
                    self.previous_agent_type = agent_name
                    self.ephemeral_directories.append({'output_folder': output_folder, 'ephemeral': agent_config.get('ephemeral', False)})
                    workflow_complete = True
                    self.console.print(f"{end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} [green]OK[/green] [bold]{agent_name}[/bold] in {duration:.2f}s")

            if workflow_complete and any(d['status'] != 'completed' for d in self.agent_status.values()):
                pass
            elif workflow_complete:
                self.console.print("\n[bold]Workflow Summary:[/bold]")
                for idx, agent_name in enumerate(self.execution_order):
                    status = self.agent_status[agent_name]['status']
                    color = "green" if status == "completed" else "red" if status == "failed" else "yellow"
                    self.console.print(f"- {agent_name}: [{color}]{status}[/{color}]")
                
                self.output_processor.process_final_output(self.ephemeral_directories)
                self.console.print("\n🎉 [bold green]Workflow Complete[/bold green]")
                self.console.print("Done.")

        except Exception as e:
            self.console.print(f"\n❌ [bold red]Workflow failed with error:[/bold red] {e}")
            self.failed = True
            try:
                running_agent = next(agent for agent, details in self.agent_status.items() if details['status'] in ['running', 'checking_batch'])
                self._update_status(running_agent, 'failed')
            except StopIteration:
                pass
            raise