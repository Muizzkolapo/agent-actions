import sys
import json
import os
import asyncio  # Added for async processing
from pathlib import Path
from datetime import datetime
from agent_actions.handlers.config_handler import ConfigManager
from agent_actions.core.agent_runner import AgentRunner
from agent_actions.generators.output.output_processor import OutputProcessor
from agent_actions.services.batch_service import BatchService
from agent_actions.constants import PROMPT_KEY, SCHEMA_NAME_KEY
from agent_actions.artifacts.manager import ArtifactManager
from agent_actions.artifacts.manifest import ManifestArtifact
from agent_actions.artifacts.base import SecurityError
from agent_actions.artifacts import context as artifact_context

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
        
        # ARTIFACT SYSTEM INTEGRATION: Initialize artifact manager
        try:
            # Check if artifacts are enabled via environment variable for performance
            enable_artifacts = os.getenv('AGENT_ACTIONS_ENABLE_ARTIFACTS', 'true').lower() == 'true'
            
            if enable_artifacts:
                agent_folder = Path(self.agent_runner.get_agent_folder(self.agent_name))
                self.artifact_manager = ArtifactManager(agent_folder)
                self._initialize_manifest()
                # Set artifact context for interceptors
                artifact_context.set_artifact_manager(self.artifact_manager)
                self.console.print("[green]Artifact system initialized[/green]")
            else:
                self.artifact_manager = None
                self.console.print("[yellow]Artifact system disabled (AGENT_ACTIONS_ENABLE_ARTIFACTS=false)[/yellow]")
        except Exception as e:
            self.console.print(f"[yellow]Warning: Could not initialize artifact system: {e}[/yellow]")
            self.artifact_manager = None

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

    def _initialize_manifest(self):
        """Initialize the manifest artifact with project and agent information."""
        if not self.artifact_manager:
            return
            
        try:
            project_name = self.agent_name
            project_path = str(Path(self.constructor_path).parent)
            
            manifest = ManifestArtifact(project_name, project_path)
            
            # Add all agents from the workflow to the manifest
            for agent_name in self.execution_order:
                agent_config = self.agent_configs[agent_name]
                manifest.add_agent(agent_name, agent_config)
            
            # Set the manifest in the artifact manager
            self.artifact_manager.set_manifest(manifest)
            
        except Exception as e:
            self.console.print(f"[yellow]Warning: Could not initialize manifest: {e}[/yellow]")
    
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
            # No batch registry found - check if passthrough data was processed instead
            passthrough_marker = Path(output_directory) / ".passthrough_processed"
            if passthrough_marker.exists():
                # Found passthrough marker - this indicates successful conditional filtering with passthrough processing
                self.console.print(f"[green]All items filtered by conditional clause - passthrough data processed for {agent_name}[/green]")
                return str(output_directory), 'completed'
            else:
                # No batch registry and no passthrough marker - this means the agent didn't submit any batch jobs
                self.console.print(f"[yellow]No batch jobs found for {agent_name}[/yellow]")
                return None, 'failed'
        else:
            return None, 'failed'

    def _process_all_batch_results(self, output_directory):
        """Process all completed batch jobs in the registry together as one dataset."""
        try:
            # Use the new combined processing method
            processed_files = self.batch_service.process_all_batch_results_to_workflow_output(output_directory)
            if not processed_files:
                raise RuntimeError("No batch results were successfully processed")
        except Exception as e:
            self.console.print(f"[red]Error: Could not process batch results: {e}[/red]")
            raise  # Re-raise to stop the workflow instead of continuing with bad data

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

                # ARTIFACT SYSTEM INTEGRATION: Record agent start
                agent_result = None
                if self.artifact_manager:
                    try:
                        agent_result = self.artifact_manager.record_agent_start(agent_name)
                    except SecurityError as e:
                        self.console.print(f"[yellow]Warning: Could not record agent start: {e}[/yellow]")
                
                # Initialize variables for timing
                output_folder = None
                agent_error_occurred = False
                
                try:
                    output_folder = self.agent_runner.run_agent(
                        agent_config, self.agent_name, self.previous_agent_type, idx, idx == len(self.execution_order) - 1
                    )
                            
                except Exception as agent_error:
                    agent_error_occurred = True
                    # ARTIFACT SYSTEM INTEGRATION: Record agent error
                    if self.artifact_manager and agent_result:
                        try:
                            self.artifact_manager.record_agent_error(
                                agent_result,
                                agent_error,
                                (datetime.now() - start_time).total_seconds(),
                                context={"agent_config": agent_config, "idx": idx}
                            )
                        except SecurityError as e:
                            self.console.print(f"[yellow]Warning: Could not record agent error: {e}[/yellow]")
                    raise agent_error

                # Calculate duration after agent execution (success or failure)
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                # Record success if no error occurred
                if not agent_error_occurred and self.artifact_manager and agent_result:
                    try:
                        self.artifact_manager.record_agent_success(
                            agent_result, 
                            response={"output_folder": output_folder}, 
                            execution_time=duration
                        )
                    except SecurityError as e:
                        self.console.print(f"[yellow]Warning: Could not record agent success: {e}[/yellow]")

                if agent_config.get('run_mode') == 'batch':
                    agent_io_path = Path(self.agent_runner.get_agent_folder(self.agent_name))
                    node_output_dir = agent_io_path / "target" / f"node_{idx}_{agent_name}"
                    
                    # Check if batch registry exists to confirm batch jobs were submitted
                    registry_file = Path(node_output_dir) / "batch" / ".batch_registry.json"
                    passthrough_marker = Path(node_output_dir) / ".passthrough_processed"
                    
                    if registry_file.exists():
                        self._update_status(agent_name, 'batch_submitted')
                        self.console.print(f"\n[yellow]Batch jobs submitted for '{agent_name}'. Run 'agent run' again to check status.[/yellow]")
                        self.console.print(f"{end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} [yellow]SUBMITTED[/yellow] [bold]{agent_name}[/bold] (batch) in {duration:.2f}s")
                    elif passthrough_marker.exists():
                        # Found passthrough marker - this indicates successful conditional filtering with passthrough processing
                        self._update_status(agent_name, 'completed')
                        self.previous_agent_type = agent_name
                        self.ephemeral_directories.append({'output_folder': str(node_output_dir), 'ephemeral': agent_config.get('ephemeral', False)})
                        workflow_complete = True
                        self.console.print(f"\n[green]All items filtered by conditional clause - passthrough data processed for '{agent_name}'.[/green]")
                        self.console.print(f"{end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} [green]OK[/green] [bold]{agent_name}[/bold] in {duration:.2f}s")
                        continue
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
                
                # ARTIFACT SYSTEM INTEGRATION: Save all artifacts at the end
                if self.artifact_manager:
                    try:
                        self.artifact_manager.save_artifacts(force=True)  # Force save at workflow completion
                        artifacts_dir = self.artifact_manager.artifacts_dir
                        self.console.print(f"\n📊 [bold blue]Artifacts saved to:[/bold blue] {artifacts_dir}")
                        self.console.print(f"   - manifest.json")
                        self.console.print(f"   - run_results.json")
                        self.console.print(f"   - validation_results.json")
                    except Exception as e:
                        self.console.print(f"[yellow]Warning: Could not save artifacts: {e}[/yellow]")
                
                self.console.print("\n🎉 [bold green]Workflow Complete[/bold green]")
                self.console.print("Done.")
                
                # Clear artifact context
                artifact_context.clear_artifact_manager()

        except Exception as e:
            self.console.print(f"\n❌ [bold red]Workflow failed with error:[/bold red] {e}")
            self.failed = True
            try:
                running_agent = next(agent for agent, details in self.agent_status.items() if details['status'] in ['running', 'checking_batch'])
                self._update_status(running_agent, 'failed')
            except StopIteration:
                pass
            
            # ARTIFACT SYSTEM INTEGRATION: Save artifacts even on failure
            if self.artifact_manager:
                try:
                    self.artifact_manager.record_error(
                        error_type="workflow_failure",
                        operation="run_workflow",
                        target=self.agent_name,
                        error=e,
                        context={"execution_order": self.execution_order, "agent_status": self.agent_status},
                        user_message="Workflow execution failed. Check the error details and agent configurations."
                    )
                    self.artifact_manager.save_artifacts(force=True)  # Force save on error
                    self.console.print(f"[blue]Error artifacts saved to:[/blue] {self.artifact_manager.artifacts_dir}")
                except Exception as artifact_error:
                    self.console.print(f"[yellow]Warning: Could not save error artifacts: {artifact_error}[/yellow]")
            
            # Clear artifact context
            artifact_context.clear_artifact_manager()
            
            raise