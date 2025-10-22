import sys
import json
import os
import asyncio  # Added for async processing
import hashlib
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List
from agent_actions.agents.handlers.config_handler import ConfigManager
from agent_actions.core.runtime.agent_runner import AgentRunner
from agent_actions.agents.generators.output_processor import OutputProcessor
from agent_actions.tasks.services.batch_service import BatchService
from agent_actions.core.parser.where_parser import get_global_filter, evaluate_safe_skip_condition
from agent_actions.core.constants import PROMPT_KEY, SCHEMA_NAME_KEY
from agent_actions.artifacts.manager import ArtifactManager
from agent_actions.artifacts.manifest import ManifestArtifact
from agent_actions.core.contracts.base import SecurityError as ArtifactSecurityError
from agent_actions.core.context import context as artifact_context
from agent_actions.core.parser.where_parser import WhereClauseParser
from agent_actions.core.graph.loop_correlator import LoopOutputCorrelator

from rich.console import Console


class AgentWorkflow:
    async def async_run(self, concurrency_limit=5):
        """
        Execute workflow level-by-level with parallelism within each level.

        Args:
            concurrency_limit: Maximum concurrent agents within a level (default 5)
        """
        # Compute execution levels
        levels = self._compute_execution_levels()
        self._log_execution_levels(levels)

        total_agents = len(self.execution_order)

        for level_idx, level_agents in enumerate(levels):
            start_time = datetime.now()

            # Check for already completed agents in this level
            pending_agents = [
                agent for agent in level_agents
                if self.agent_status.get(agent, {}).get('status') != 'completed'
            ]

            if not pending_agents:
                self.console.print(f"[yellow]Action {level_idx}: All agents complete (skipped)[/yellow]")
                continue

            self.console.print(f"[cyan]Action {level_idx}: Starting {len(pending_agents)} agent(s)...[/cyan]")

            # Execute agents in level
            if len(pending_agents) == 1:
                # Single agent - run directly
                agent_name = pending_agents[0]
                original_idx = self.agent_indices[agent_name]
                await self._run_single_agent_async(agent_name, original_idx)
            else:
                # Multiple agents - run in parallel with concurrency limit
                self.console.print(f"[blue]  → {len(pending_agents)} agents in parallel[/blue]")

                semaphore = asyncio.Semaphore(concurrency_limit)

                async def run_with_limit(agent):
                    async with semaphore:
                        original_idx = self.agent_indices[agent]
                        return await self._run_single_agent_async(agent, original_idx)

                tasks = [run_with_limit(agent) for agent in pending_agents]
                # Use return_exceptions=True to capture all errors, not just first
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Check for any exceptions and aggregate them
                errors = []
                for agent, result in zip(pending_agents, results):
                    if isinstance(result, Exception):
                        errors.append((agent, result))

                if errors:
                    # Multiple agents failed - show all errors
                    from agent_actions.core.exceptions import WorkflowError
                    error_details = '\n'.join([
                        f"  - {agent}: {str(exc)}" for agent, exc in errors
                    ])
                    error_msg = f"Multiple agents failed in parallel action {level_idx}:\n{error_details}"
                    raise WorkflowError('parallel_execution_failures', error_msg)

            # Check for batch submissions in this level
            batch_pending = [
                agent for agent in level_agents
                if self.agent_status.get(agent, {}).get('status') == 'batch_submitted'
            ]

            if batch_pending:
                # Before early exit, check if any agents in this level failed
                failed_agents = [
                    agent for agent in level_agents
                    if self.agent_status.get(agent, {}).get('status') == 'failed'
                ]

                if failed_agents:
                    # Some batch agents succeeded but others failed - raise error
                    from agent_actions.core.exceptions import WorkflowError
                    error_msg = f"Partial failure in parallel action {level_idx}: {', '.join(failed_agents)} failed while batch jobs were submitted"
                    raise WorkflowError('batch_submission_partial_failure', error_msg)

                # All agents succeeded and batch jobs submitted - safe to exit
                duration = (datetime.now() - start_time).total_seconds()
                self.console.print(f"[yellow]Action {level_idx}: {len(batch_pending)} batch job(s) submitted ({duration:.2f}s)[/yellow]")
                self.console.print(f"[yellow]Run workflow again to check batch status[/yellow]")
                return  # Exit early - resume on next run

            # Level complete
            duration = (datetime.now() - start_time).total_seconds()
            self.console.print(f"[green]Action {level_idx} complete ({duration:.2f}s)[/green]")

        # All levels complete
        self.console.print("\n[bold]Workflow Summary:[/bold]")
        for agent_name in self.execution_order:
            status = self.agent_status[agent_name]['status']
            color = "green" if status == "completed" else "red" if status == "failed" else "yellow"
            self.console.print(f"- {agent_name}: [{color}]{status}[/{color}]")

        self.output_processor.process_final_output(self.ephemeral_directories)
        self.console.print("\n🎉 [bold green]Workflow Complete[/bold green]")
        self.console.print("Done.")

    async def _run_single_agent_async(self, agent_name: str, agent_idx: int):
        """
        Run a single agent asynchronously.

        Args:
            agent_name: Name of the agent to run
            agent_idx: Original index in execution_order (for directory naming)
        """
        agent_config = self.agent_configs[agent_name]
        status_details = self.agent_status.get(agent_name, {})
        current_status = status_details.get('status', 'pending')
        start_time = datetime.now()

        # Check if agent is already completed
        if current_status == 'completed':
            # Note: previous_agent_type is not updated in parallel execution
            # to avoid race conditions. It remains the last sequential agent.
            return

        # Check if agent has batch already submitted (from previous run)
        if current_status == 'batch_submitted':
            self._update_status(agent_name, 'checking_batch')

            # Check batch status instead of re-running agent
            output_folder, batch_status = await asyncio.to_thread(
                self._handle_batch_agent,
                agent_name,
                agent_idx
            )

            if batch_status == 'completed':
                self._update_status(agent_name, 'completed')
                self.ephemeral_directories.append({
                    'output_folder': output_folder,
                    'ephemeral': agent_config.get('ephemeral', False)
                })
                duration = (datetime.now() - start_time).total_seconds()
                self.console.print(f"  [green]✓ {agent_name} (batch completed, {duration:.2f}s)[/green]")
                return
            elif batch_status == 'in_progress':
                self._update_status(agent_name, 'batch_submitted')
                duration = (datetime.now() - start_time).total_seconds()
                self.console.print(f"  [yellow]→ {agent_name}: batch still in progress ({duration:.2f}s)[/yellow]")
                return
            else:
                # Batch failed
                self._update_status(agent_name, 'failed')
                duration = (datetime.now() - start_time).total_seconds()
                self.console.print(f"  [red]✗ {agent_name}: batch failed ({duration:.2f}s)[/red]")
                raise Exception(f"Batch job for {agent_name} failed")

        # Check WHERE clause
        previous_outputs = self._get_previous_outputs(agent_idx)
        if self._should_skip_agent(agent_config, previous_outputs):
            self.console.print(f"  [yellow]Skipping {agent_name} (WHERE clause)[/yellow]")
            self._create_passthrough_output(agent_idx, agent_name)
            self._update_status(agent_name, 'completed')
            # Note: previous_agent_type not updated to avoid race condition
            return

        # Set up loop correlation if needed (BEFORE running the agent)
        self._setup_correlation_if_needed(agent_idx)

        # Run the agent
        try:
            output_folder = await asyncio.to_thread(
                self.agent_runner.run_agent,
                agent_config,
                self.agent_name,
                self.previous_agent_type,
                agent_idx,
                agent_idx == len(self.execution_order) - 1
            )

            # Check if batch mode
            if agent_config.get('run_mode') == 'batch':
                # Check for batch registry
                agent_io_path = Path(self.agent_runner.get_agent_folder(self.agent_name))
                node_output_dir = agent_io_path / "target" / f"node_{agent_idx}_{agent_name}"
                registry_file = node_output_dir / "batch" / ".batch_registry.json"

                if registry_file.exists():
                    self._update_status(agent_name, 'batch_submitted')
                    self.console.print(f"  [yellow]→ {agent_name}: batch submitted[/yellow]")
                    return

            # Online mode or batch passthrough
            self._update_status(agent_name, 'completed')
            # Note: previous_agent_type not updated to avoid race condition in parallel execution
            self.ephemeral_directories.append({
                'output_folder': output_folder,
                'ephemeral': agent_config.get('ephemeral', False)
            })

            duration = (datetime.now() - start_time).total_seconds()
            self.console.print(f"  [green]✓ {agent_name} ({duration:.2f}s)[/green]")

        except Exception as e:
            self.console.print(f"  [red]✗ {agent_name} failed: {e}[/red]")
            self._update_status(agent_name, 'failed')
            raise
        finally:
            # Restore original setup_directories if it was overridden for loop correlation
            if hasattr(self, '_original_setup_directories'):
                self.agent_runner.setup_directories = self._original_setup_directories

    def __init__(self, constructor_path, user_code_path, default_path, use_tools,
                 parent_output=None, parent_source=None, parent_pipeline=None):
        self.constructor_path = constructor_path
        self.user_code_path = user_code_path
        self.default_path = default_path
        self.use_tools = use_tools
        self.parent_output = parent_output
        self.parent_source = parent_source
        self.parent_pipeline = parent_pipeline

        # Note: previous_agent_type tracks the last completed agent in sequential execution.
        # In parallel execution (async_run), it is NOT updated to avoid race conditions.
        # For parallel agents, this value represents the last sequential agent (or None).
        self.previous_agent_type = None
        self.ephemeral_directories = []
        self.failed = False

        self.config_manager = ConfigManager(self.constructor_path, self.default_path)
        self._load_configs()

        # Discover and register UDFs
        if self.user_code_path:
            from agent_actions.core.udf_loader import discover_udfs
            console = Console()

            abs_user_code_path = str(Path(self.user_code_path).resolve())
            if abs_user_code_path not in sys.path:
                sys.path.insert(0, abs_user_code_path)

            # Discover UDFs
            console.print("[cyan]🔍 Discovering UDFs...[/cyan]")
            registry = discover_udfs(Path(abs_user_code_path))
            console.print(f"[green]✅ Discovered {len(registry)} UDF(s)[/green]")

        elif self.config_manager.tool_path:
            from agent_actions.core.udf_loader import discover_udfs
            console = Console()

            # Discover UDFs from all tool paths
            total_udfs = 0
            for path in self.config_manager.tool_path:
                abs_tool_path = str(Path(path).resolve())
                if abs_tool_path not in sys.path:
                    sys.path.insert(0, abs_tool_path)

                # Discover UDFs in this path
                if Path(abs_tool_path).exists() and Path(abs_tool_path).is_dir():
                    console.print(f"[cyan]🔍 Discovering UDFs in {abs_tool_path}...[/cyan]")
                    registry = discover_udfs(Path(abs_tool_path))
                    total_udfs += len(registry)

            if total_udfs > 0:
                console.print(f"[green]✅ Discovered {total_udfs} UDF(s)[/green]")

        # Use bootstrap to create properly configured AgentRunner with DI
        from ..bootstrap_factory import create_agent_runner
        self.agent_runner = create_agent_runner(
            use_tools=self.use_tools,
            constructor_path=self.constructor_path,
            default_path=getattr(self.config_manager, 'default_path', None)
        )
        # Pass execution_order, agent_indices, and agent_configs to agent_runner for proper dependency resolution
        self.agent_runner.execution_order = self.execution_order
        self.agent_runner.agent_indices = self.agent_indices
        self.agent_runner.agent_configs = self.agent_configs

        self.output_processor = OutputProcessor(self.parent_output, self.constructor_path)
        self.batch_service = BatchService()
        self.where_parser = WhereClauseParser()

        # Initialize loop correlator for parallel map-reduce support
        agent_folder = Path(self.agent_runner.get_agent_folder(self.agent_name))
        self.loop_correlator = LoopOutputCorrelator(agent_folder)

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

        # Generate workflow session ID for deterministic correlation across all batches
        self.workflow_session_id = self._generate_workflow_session_id()
        
        # Inject workflow session ID into all agent configs for correlation
        self._inject_workflow_session_id()

    def _load_configs(self):
        self.config_manager.load_configs()
        self.config_manager.validate_agent_name()
        self.config_manager.check_child_pipeline()
        user_agents = self.config_manager.get_user_agents()
        self.config_manager.merge_agent_configs(user_agents)
        self.config_manager.determine_execution_order()
        self.agent_name = self.config_manager.agent_name
        self.execution_order = self.config_manager.execution_order
        # Pre-compute agent indices for O(1) lookup instead of O(n) execution_order.index()
        self.agent_indices = {agent: i for i, agent in enumerate(self.execution_order)}
        self.agent_configs = self.config_manager.get_all_agent_configs_as_dicts()
        self.child_pipeline = self.config_manager.child_pipeline

    def _generate_workflow_session_id(self) -> str:
        """
        Generate a deterministic yet unique workflow session ID.
        
        Returns:
            Workflow session ID in format: workflow_{timestamp}_{config_hash}
        """
        timestamp = int(time.time())
        
        # Create a hash based on the workflow configuration for determinism
        config_content = f"{self.constructor_path}:{self.agent_name}"
        config_hash = hashlib.md5(config_content.encode()).hexdigest()[:8]
        
        return f"workflow_{timestamp}_{config_hash}"
    
    def _inject_workflow_session_id(self):
        """
        Inject the workflow session ID into all agent configurations.
        This enables deterministic correlation IDs across all agents and batches.
        """
        for agent_name, agent_config in self.agent_configs.items():
            agent_config['workflow_session_id'] = self.workflow_session_id

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

    def _compute_execution_levels(self) -> List[List[str]]:
        """
        Compute execution levels from dependency graph.
        Agents in same level can run in parallel.

        Returns:
            List of execution levels, where each level is a list of agent names
        """
        from agent_actions.core.exceptions import WorkflowError

        # Build dependency map
        deps_map = {
            agent: self.agent_configs[agent].get('dependencies', [])
            for agent in self.execution_order
        }

        levels = []
        assigned = set()

        # Iteratively assign agents to levels
        while len(assigned) < len(self.execution_order):
            # Find agents whose dependencies are all satisfied
            current_level = [
                agent for agent in self.execution_order
                if agent not in assigned
                and all(dep in assigned for dep in deps_map[agent])
            ]

            if not current_level:
                # No progress made - circular dependency detected
                # Build detailed error showing which agents are waiting for which dependencies
                remaining_agents = set(self.execution_order) - assigned
                unsatisfied_deps = {
                    agent: [dep for dep in deps_map[agent] if dep not in assigned]
                    for agent in remaining_agents
                }

                # Create detailed error message
                error_details = '\n'.join([
                    f"  - {agent} waiting for: {', '.join(deps)}"
                    for agent, deps in unsatisfied_deps.items()
                ])

                raise WorkflowError(
                    'circular_dependency',
                    f'Circular dependency detected - cannot compute execution levels.\n\nAgents blocked:\n{error_details}',
                    context={
                        'assigned': list(assigned),
                        'remaining': list(remaining_agents),
                        'unsatisfied_dependencies': unsatisfied_deps
                    }
                )

            levels.append(current_level)
            assigned.update(current_level)

        return levels

    def _should_use_parallel_execution(self) -> bool:
        """
        Determine if workflow should use parallel execution.

        Returns True if any execution level has more than 1 agent.
        """
        levels = self._compute_execution_levels()
        return any(len(level) > 1 for level in levels)

    def _log_execution_levels(self, levels: List[List[str]]) -> None:
        """Log execution levels for user transparency."""
        self.console.print(f"[blue]📊 Execution: {len(levels)} action(s)[/blue]")

        for i, level in enumerate(levels):
            if len(level) > 1:
                # Sort agents by original execution order for consistent logging
                sorted_agents = sorted(level, key=lambda a: self.agent_indices[a])
                self.console.print(
                    f"[blue]  Action {i}: {len(level)} agents in parallel - {', '.join(sorted_agents)}[/blue]"
                )
            else:
                self.console.print(
                    f"[dim]  Action {i}: {level[0]} (sequential)[/dim]"
                )

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

    def _get_input_directory(self, idx: int) -> str:
        agent_folder = Path(self.agent_runner.get_agent_folder(self.agent_name))

        if idx == 0:
            return str(agent_folder / "staging")

        # Check if current agent needs loop correlation
        current_agent = self.execution_order[idx]

        loop_consumption_map = self.loop_correlator.detect_explicit_loop_consumption(
            self.execution_order, self.agent_configs
        )

        if current_agent in loop_consumption_map:
            # Use correlated input for agents with explicit loop consumption
            consumption_config = loop_consumption_map[current_agent]
            loop_sources = consumption_config['loop_agents']
            pattern = consumption_config['pattern']

            correlated_dir = self.loop_correlator.prepare_correlated_input(
                current_agent, loop_sources, idx
            )

            if correlated_dir:
                self.console.print(f"[blue]🔗 Using correlated input for {current_agent} from {len(loop_sources)} loop sources (pattern: {pattern})[/blue]")
                return correlated_dir
            else:
                self.console.print(f"[yellow]⚠️ Failed to correlate loop outputs for {current_agent}, falling back to standard input[/yellow]")

        # Standard input directory (existing behavior)
        prev_agent = self.execution_order[idx - 1]
        return str(agent_folder / "target" / f"node_{idx-1}_{prev_agent}")

    def _setup_correlation_if_needed(self, idx: int):
        """
        Set up correlation for agents that depend on loop outputs by temporarily
        overriding the AgentRunner's setup_directories method.
        """
        current_agent = self.execution_order[idx]
        loop_consumption_map = self.loop_correlator.detect_explicit_loop_consumption(
            self.execution_order, self.agent_configs
        )

        if current_agent in loop_consumption_map:
            # This agent needs correlation - override setup_directories
            consumption_config = loop_consumption_map[current_agent]
            loop_sources = consumption_config['loop_agents']
            pattern = consumption_config['pattern']

            # Store original method
            original_setup_directories = self.agent_runner.setup_directories

            def correlation_setup_directories(agent_folder, agent_config, previous_agent_type, agent_idx):
                # Use correlation logic for input directory
                correlated_dir = self.loop_correlator.prepare_correlated_input(
                    current_agent, loop_sources, agent_idx
                )

                if correlated_dir:
                    self.console.print(f"[blue]🔗 Using correlated input for {current_agent} from {len(loop_sources)} loop sources (pattern: {pattern})[/blue]")
                    input_directory = correlated_dir
                else:
                    self.console.print(f"[yellow]⚠️ Failed to correlate loop outputs for {current_agent}, falling back to standard input[/yellow]")
                    # Fall back to original logic
                    input_dir, output_dir = original_setup_directories(agent_folder, agent_config, previous_agent_type, agent_idx)
                    input_directory = input_dir

                # Set up output directory normally
                from pathlib import Path
                indexed_agent_type = f"node_{agent_idx}_{agent_config['agent_type']}"
                output_directory = Path(agent_folder) / 'target' / indexed_agent_type
                output_directory.mkdir(parents=True, exist_ok=True)

                return str(input_directory), str(output_directory)

            # Temporarily replace the method
            self.agent_runner.setup_directories = correlation_setup_directories

            # Store a reference to restore it later
            self._original_setup_directories = original_setup_directories
        else:
            # Restore original method if it was overridden
            if hasattr(self, '_original_setup_directories'):
                self.agent_runner.setup_directories = self._original_setup_directories

    def _get_previous_outputs(self, idx: int) -> Dict[str, Any]:
        outputs: Dict[str, Any] = {}
        agent_folder = Path(self.agent_runner.get_agent_folder(self.agent_name))
        for i, agent_name in enumerate(self.execution_order[:idx]):
            output_dir = agent_folder / "target" / f"node_{i}_{agent_name}"
            items = []
            if output_dir.exists():
                for file in output_dir.glob("*.json"):
                    try:
                        with open(file, "r", encoding="utf-8") as f:
                            items.append(json.load(f))
                    except Exception:
                        continue
            outputs[agent_name] = items
        return outputs


    def _create_passthrough_output(self, idx: int, agent_type: str):
        input_dir = self._get_input_directory(idx)
        agent_folder = Path(self.agent_runner.get_agent_folder(self.agent_name))
        output_dir = agent_folder / "target" / f"node_{idx}_{agent_type}"
        output_dir.mkdir(parents=True, exist_ok=True)
        if os.path.exists(input_dir):
            import shutil
            for item in os.listdir(input_dir):
                shutil.copy2(os.path.join(input_dir, item), output_dir / item)
        with open(output_dir / ".agent_skipped", "w", encoding="utf-8") as f:
            f.write(f"Agent {agent_type} skipped due to WHERE clause condition")

    def _handle_batch_agent(self, agent_name, idx):
        agent_io_path = Path(self.agent_runner.get_agent_folder(self.agent_name))
        output_directory = agent_io_path / "target" / f"node_{idx}_{agent_name}"

        # Get agent config for loop correlation
        agent_config = self.agent_configs.get(agent_name, {})

        # Check overall batch registry status - this is the single source of truth
        registry_status = self.batch_service._get_batch_registry_status(str(output_directory))

        if registry_status == 'completed':
            self.console.print(f"[green]All batch jobs are completed. Processing results...[/green]")
            # Process all completed batch jobs in the registry
            self._process_all_batch_results(str(output_directory), agent_config)
            self.console.print(f"[green]✅ Processed all batch results for {agent_name}[/green]")
            return str(output_directory), 'completed'
        elif registry_status in ['in_progress', 'partial_failed']:
            # Check if all jobs are actually done (some might have completed since last check)
            if self.batch_service._are_all_batch_jobs_completed(str(output_directory)):
                self.console.print(f"[green]All batch jobs are now completed. Processing results...[/green]")
                self._process_all_batch_results(str(output_directory), agent_config)
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

    def _process_all_batch_results(self, output_directory, agent_config=None):
        """Process all completed batch jobs in the registry together as one dataset."""
        try:
            # Use the new combined processing method
            processed_files = self.batch_service.process_all_batch_results_to_workflow_output(output_directory, agent_config=agent_config)
            if not processed_files:
                from agent_actions.core.exceptions import ProcessingError
                raise ProcessingError("No batch results were successfully processed")
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

                previous_outputs = self._get_previous_outputs(idx)
                if self._should_skip_agent(agent_config, previous_outputs):
                    self.console.print(f"Skipping agent {agent_name} due to WHERE clause condition")
                    self._create_passthrough_output(idx, agent_name)
                    self._update_status(agent_name, 'completed')
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
                    except ArtifactSecurityError as e:
                        self.console.print(f"[yellow]Warning: Could not record agent start: {e}[/yellow]")
                
                # Initialize variables for timing
                output_folder = None
                agent_error_occurred = False
                
                try:
                    # Check if this agent needs custom input directory for loop correlation
                    self._setup_correlation_if_needed(idx)

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
                        except ArtifactSecurityError as e:
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
                    except ArtifactSecurityError as e:
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

                        # Cleanup: Remove marker file to prevent interference with subsequent file processing
                        try:
                            passthrough_marker.unlink()
                        except FileNotFoundError:
                            pass  # Already removed, ignore

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
    
    def _should_skip_agent(self, agent_config: Dict[str, Any], previous_outputs: Dict[str, Any] = None) -> bool:
        """
        Determine if an agent should be skipped based on skip conditions.
        
        Enhanced with comprehensive WHERE clause filtering support and detailed logging.
        
        Args:
            agent_config: Agent configuration
            previous_outputs: Previous agent outputs for context
            
        Returns:
            True if the agent should be skipped, False otherwise
        """
        agent_name = agent_config.get('agent_type', 'unknown')
        
        # Check new safe skip condition
        skip_condition = agent_config.get('skip_condition')
        if skip_condition:
            try:
                context = {
                    'previous_outputs': previous_outputs or {},
                    'agent_config': agent_config
                }
                should_skip = evaluate_safe_skip_condition(skip_condition, context)
                if should_skip:
                    self.console.print(f"[yellow]🔍 Agent {agent_name} SKIPPED: skip_condition evaluated to True[/yellow]")
                else:
                    self.console.print(f"[green]✓ Agent {agent_name} passed skip_condition check[/green]")
                return should_skip
            except Exception as e:
                self.console.print(f"[red]⚠️ Agent {agent_name}: Error evaluating skip condition: {e}[/red]")
                # Fail safe - don't skip on error
                return False
        
        # Check WHERE clause with agent scope
        where_config = agent_config.get('where_clause')
        if where_config and where_config.get('scope') == 'agent':
            try:
                filter_service = get_global_filter()
                context_data = {
                    'previous_outputs': previous_outputs or {},
                    'agent_type': agent_config.get('agent_type'),
                    'dependencies': agent_config.get('dependencies', []),
                    'agent_config': {k: v for k, v in agent_config.items() if k not in ['where_clause']}
                }
                
                # Enhanced logging for WHERE clause evaluation
                where_clause = where_config['clause']
                self.console.print(f"[blue]🔍 Evaluating agent-level WHERE clause for {agent_name}: {where_clause}[/blue]")
                
                filter_result = filter_service.filter_item(
                    context_data,
                    where_clause,
                    timeout=agent_config.get('max_execution_time', 5)
                )
                
                if not filter_result.success:
                    # Handle error based on configuration
                    passthrough_on_error = where_config.get('passthrough_on_error', True)
                    error_msg = filter_result.error or "Unknown filter error"
                    self.console.print(f"[red]⚠️ Agent {agent_name}: WHERE clause evaluation failed: {error_msg}[/red]")
                    
                    if passthrough_on_error:
                        self.console.print(f"[yellow]→ Agent {agent_name} proceeding due to passthrough_on_error=True[/yellow]")
                        return False  # Don't skip
                    else:
                        self.console.print(f"[red]→ Agent {agent_name} SKIPPED due to passthrough_on_error=False[/red]")
                        return True  # Skip
                
                if not filter_result.matched:
                    self.console.print(f"[yellow]🚫 Agent {agent_name} SKIPPED: WHERE clause condition not met[/yellow]")
                    self.console.print(f"[yellow]   Clause: {where_clause}[/yellow]")
                    self.console.print(f"[yellow]   Context: {context_data}[/yellow]")
                    return True  # Skip if doesn't match
                else:
                    self.console.print(f"[green]✓ Agent {agent_name} passed WHERE clause check (execution time: {filter_result.execution_time:.3f}s)[/green]")
                    return False  # Don't skip
                
            except Exception as e:
                self.console.print(f"[red]⚠️ Agent {agent_name}: Error evaluating agent WHERE clause: {e}[/red]")
                # Fail safe - check passthrough behavior
                passthrough_on_error = where_config.get('passthrough_on_error', True)
                if passthrough_on_error:
                    self.console.print(f"[yellow]→ Agent {agent_name} proceeding due to error and passthrough_on_error=True[/yellow]")
                    return False
                else:
                    self.console.print(f"[red]→ Agent {agent_name} SKIPPED due to error and passthrough_on_error=False[/red]")
                    return True
        
        # Legacy skip_if condition (deprecated but maintained for backwards compatibility)
        if agent_config.get('skip_if'):
            try:
                from agent_actions.core.parser.where_parser import evaluate_safe_expression
                context = {
                    'previous_outputs': previous_outputs or {},
                    'agent_config': agent_config
                }
                should_skip = evaluate_safe_expression(agent_config['skip_if'], context)
                if should_skip:
                    self.console.print(f"[yellow]🔍 Agent {agent_name} SKIPPED: legacy skip_if condition[/yellow]")
                else:
                    self.console.print(f"[green]✓ Agent {agent_name} passed legacy skip_if check[/green]")
                return should_skip
            except Exception as e:
                self.console.print(f"[red]⚠️ Agent {agent_name}: Error evaluating legacy skip_if condition: {e}[/red]")
                return False
        
        return False
    
    def _get_previous_outputs(self, current_idx: int) -> Dict[str, Any]:
        """
        Get outputs from previously executed agents with enhanced context for WHERE clause evaluation.
        
        Args:
            current_idx: Index of the current agent
            
        Returns:
            Dictionary of previous agent outputs with metadata
        """
        previous_outputs = {}
        
        # Get the agent folder path
        agent_io_path = Path(self.agent_runner.get_agent_folder(self.agent_name))
        
        # Look at all previous agents in the execution order
        for i in range(current_idx):
            prev_agent_name = self.execution_order[i]
            output_dir = agent_io_path / "target" / f"node_{i}_{prev_agent_name}"
            
            # Initialize agent output structure
            agent_output = {
                'data': [],
                'status': self.agent_status.get(prev_agent_name, {}).get('status', 'unknown'),
                'output_count': 0,
                'output_files': [],
                'has_data': False,
                'errors': []
            }
            
            # Try to load output data from the previous agent
            try:
                if output_dir.exists():
                    # Look for JSON files in the output directory
                    json_files = list(output_dir.glob("*.json"))
                    agent_output['output_files'] = [str(f.name) for f in json_files]
                    
                    if json_files:
                        outputs = []
                        for json_file in json_files:
                            try:
                                with open(json_file, 'r') as f:
                                    data = json.load(f)
                                    if isinstance(data, list):
                                        outputs.extend(data)
                                    else:
                                        outputs.append(data)
                            except Exception as file_error:
                                agent_output['errors'].append(f"Failed to read {json_file.name}: {file_error}")
                        
                        agent_output['data'] = outputs
                        agent_output['output_count'] = len(outputs)
                        agent_output['has_data'] = len(outputs) > 0
                    
                    # Check for passthrough markers
                    passthrough_marker = output_dir / ".passthrough_processed"
                    if passthrough_marker.exists():
                        agent_output['passthrough'] = True
                        try:
                            with open(passthrough_marker, 'r') as f:
                                agent_output['passthrough_reason'] = f.read().strip()
                        except:
                            agent_output['passthrough_reason'] = "Unknown"
                    
                    # Check for skip markers
                    skip_marker = output_dir / ".agent_skipped"
                    if skip_marker.exists():
                        agent_output['skipped'] = True
                        try:
                            with open(skip_marker, 'r') as f:
                                agent_output['skip_reason'] = f.read().strip()
                        except:
                            agent_output['skip_reason'] = "Unknown"
                
                # Store both the structured output and the raw data list for backward compatibility
                previous_outputs[prev_agent_name] = agent_output['data']  # Backward compatibility
                previous_outputs[f"{prev_agent_name}_meta"] = agent_output  # Enhanced metadata
                
            except Exception as e:
                error_msg = f"Could not load outputs for {prev_agent_name}: {e}"
                self.console.print(f"[yellow]Warning: {error_msg}[/yellow]")
                
                # Still provide the structure even on error
                agent_output['errors'].append(error_msg)
                previous_outputs[prev_agent_name] = []
                previous_outputs[f"{prev_agent_name}_meta"] = agent_output
        
        return previous_outputs