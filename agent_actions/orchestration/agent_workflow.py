"""
Agent workflow orchestration 
"""

import sys
import hashlib
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

from agent_actions.llm_invocation.realtime.config_handler import ConfigManager
from agent_actions.logging import CorrelationContext
import os
import shutil
from agent_actions.io.file_handler import FileHandler

logger = logging.getLogger(__name__)
from agent_actions.prompt_generation.output_processor import OutputProcessor
from agent_actions.llm_invocation.batch.batch_service import BatchService
from agent_actions.orchestration.loop_correlator import LoopOutputCorrelator
from rich.console import Console

# Import new modular components
from agent_actions.orchestration.state_manager import AgentStateManager
from agent_actions.orchestration.skip_evaluator import SkipEvaluator
from agent_actions.orchestration.batch_manager import BatchLifecycleManager
from agent_actions.orchestration.output_manager import AgentOutputManager
from agent_actions.orchestration.agent_executor import AgentExecutor
from agent_actions.orchestration.action_level_executor import ActionLevelOrchestrator


class AgentWorkflow:
    """
    Orchestrates multi-agent workflow execution.

    This refactored version delegates complexity to specialized modules:
    - AgentStateManager: Status persistence and queries
    - SkipEvaluator: Skip condition evaluation (strategy pattern)
    - BatchLifecycleManager: Batch job handling
    - AgentOutputManager: Output loading and passthrough
    - AgentExecutor: Single agent execution
    - ActionLevelOrchestrator: Parallel execution coordination by action level
    """

    def __init__(
        self,
        constructor_path: str,
        user_code_path: Optional[str],
        default_path: str,
        use_tools: bool,
        parent_output: Optional[str] = None,
        parent_source: Optional[str] = None,
        parent_pipeline: Optional[str] = None,
        run_upstream: bool = False,
        run_downstream: bool = False
    ):
        """Initialize workflow with configuration and dependencies."""
        # Store configuration
        self.constructor_path = constructor_path
        self.user_code_path = user_code_path
        self.default_path = default_path
        self.use_tools = use_tools
        self.parent_output = parent_output
        self.parent_source = parent_source
        self.parent_pipeline = parent_pipeline
        self.run_upstream = run_upstream
        self.run_downstream = run_downstream
        self._workspace_index = None  # Lazy-initialized for downstream

        # Initialize state
        self.previous_agent_type = None
        self.ephemeral_directories = []
        self.failed = False
        self.console = Console()

        # Load configuration
        self.config_manager = ConfigManager(self.constructor_path, self.default_path)
        self._load_configs()

        # Discover UDFs
        self._discover_udfs()

        # Create agent runner
        from agent_actions.configuration.bootstrap_factory import create_agent_runner
        self.agent_runner = create_agent_runner(
            use_tools=self.use_tools,
            constructor_path=self.constructor_path,
            default_path=getattr(self.config_manager, 'default_path', None)
        )
        self.agent_runner.execution_order = self.execution_order
        self.agent_runner.agent_indices = self.agent_indices
        self.agent_runner.agent_configs = self.agent_configs
        self.agent_runner.workflow_name = self.agent_name

        # Initialize supporting services
        self.output_processor = OutputProcessor(self.parent_output, self.constructor_path)
        self.batch_service = BatchService(
            agent_indices=self.agent_indices,
            dependency_configs=self.agent_configs
        )

        # Get agent folder
        agent_folder = Path(self.agent_runner.get_agent_folder(self.agent_name))
        status_file = agent_folder / '.agent_status.json'

        # Initialize loop correlator
        self.loop_correlator = LoopOutputCorrelator(agent_folder)

        # Initialize modular components
        self.state_manager = AgentStateManager(status_file, self.execution_order)
        self.skip_evaluator = SkipEvaluator(self.console)
        self.batch_manager = BatchLifecycleManager(self.batch_service, self.console)
        self.output_manager = AgentOutputManager(
            agent_folder,
            self.execution_order,
            self.agent_configs,
            self.state_manager.agent_status,
            self.loop_correlator,
            self.console
        )

        # Initialize agent executor
        self.agent_executor = AgentExecutor(
            self.agent_runner,
            self.state_manager,
            self.skip_evaluator,
            self.batch_manager,
            self.output_manager,
            self.console
        )

        # Initialize action-level orchestrator
        self.action_level_orchestrator = ActionLevelOrchestrator(
            self.execution_order,
            self.agent_configs,
            self.console
        )

        # Generate and inject workflow session ID
        self.workflow_session_id = self._generate_workflow_session_id()
        self._inject_workflow_session_id()

    def _load_configs(self):
        """Load and process configuration files."""
        self.config_manager.load_configs()
        self.config_manager.validate_agent_name()
        self.config_manager.check_child_pipeline()

        user_agents = self.config_manager.get_user_agents()
        self.config_manager.merge_agent_configs(user_agents)
        self.config_manager.determine_execution_order()

        self.agent_name = self.config_manager.agent_name
        self.execution_order = self.config_manager.execution_order
        self.agent_indices = {agent: i for i, agent in enumerate(self.execution_order)}
        self.agent_configs = self.config_manager.get_all_agent_configs_as_dicts()

        # Add idx and workflow_config_path fields to each agent config
        for agent_name, agent_config in self.agent_configs.items():
            # Skip None configs (defensive check for malformed config dictionaries)
            if agent_config is None:
                continue
            if agent_name in self.agent_indices:
                agent_config['idx'] = self.agent_indices[agent_name]
            # Add workflow config path for static data loading
            agent_config['workflow_config_path'] = self.constructor_path

        self.child_pipeline = self.config_manager.child_pipeline

    def _discover_udfs(self):
        """Discover user-defined functions from configured paths."""
        if self.user_code_path:
            self._discover_udfs_from_path(self.user_code_path, is_primary=True)
        elif self.config_manager.tool_path:
            total_udfs = 0
            for path in self.config_manager.tool_path:
                count = self._discover_udfs_from_path(path, is_primary=False)
                total_udfs += count
            if total_udfs > 0:
                self.console.print(f'[green]✅ Discovered {total_udfs} UDF(s)[/green]')

    def _discover_udfs_from_path(self, path: str, is_primary: bool) -> int:
        """Discover UDFs from a specific path."""
        from agent_actions.input_loading.udf_loader import discover_udfs

        abs_path = str(Path(path).resolve())
        if abs_path not in sys.path:
            sys.path.insert(0, abs_path)

        if Path(abs_path).exists() and Path(abs_path).is_dir():
            if not is_primary:
                self.console.print(f'[cyan]🔍 Discovering UDFs in {abs_path}...[/cyan]')
            else:
                self.console.print('[cyan]🔍 Discovering UDFs...[/cyan]')

            registry = discover_udfs(Path(abs_path))

            if is_primary:
                self.console.print(f'[green]✅ Discovered {len(registry)} UDF(s)[/green]')

            return len(registry)

        return 0

    def _generate_workflow_session_id(self) -> str:
        """Generate a deterministic yet unique workflow session ID."""
        timestamp = int(time.time())
        config_content = f'{self.constructor_path}:{self.agent_name}'
        config_hash = hashlib.md5(config_content.encode()).hexdigest()[:8]
        return f'workflow_{timestamp}_{config_hash}'

    def _inject_workflow_session_id(self):
        """Inject workflow session ID into all agent configurations."""
        for agent_name, agent_config in self.agent_configs.items():
            agent_config['workflow_session_id'] = self.workflow_session_id

    def _resolve_upstream_workflows(self):
        """Recursively resolve and execute upstream dependencies."""
        if not self.run_upstream:
            return True  # Continue execution
        
        logger.info(f"Checking upstream dependencies for {self.agent_name}...", extra={'operation': 'resolve_upstream'})
        processed_upstreams = set()
        
        for agent_name, config in self.agent_configs.items():
            for dep in config.get('dependencies', []):
                if isinstance(dep, dict) and 'workflow' in dep:
                    upstream_name = dep['workflow']
                    if upstream_name in processed_upstreams:
                        continue
                    
                    result = self._execute_upstream_workflow(upstream_name)
                    if result is None:
                        # Upstream has pending batch jobs, exit gracefully
                        return False  # Signal to stop execution
                    processed_upstreams.add(upstream_name)
        
        return True  # All upstreams resolved successfully

    def _execute_upstream_workflow(self, upstream_name: str):
        """Execute a single upstream workflow and link artifacts."""
        self.console.print(f"[bold cyan]>> Recursive: Checking upstream workflow '{upstream_name}'...[/bold cyan]")
        
        # 1. Locate Upstream Config (Heuristic: Same parent directory structure)
        # Assumes: .../workflows/CURRENT/agent_config/current.yml
        # Target:  .../workflows/UPSTREAM/agent_config/upstream.yml
        try:
            current_config_path = Path(self.constructor_path)
            workflows_root = current_config_path.parents[2] # .../samples/agent_workflow
            upstream_config_path = workflows_root / upstream_name / 'agent_config' / f'{upstream_name}.yml'
            
            if not upstream_config_path.exists():
                raise FileNotFoundError(f"Could not locate upstream config at {upstream_config_path}")

            # 2. Check if upstream workflow is already complete
            # Optimization: Read status file directly instead of initializing full workflow
            upstream_agent_folder = workflows_root / upstream_name / 'agent_io'
            upstream_status_file = upstream_agent_folder / '.agent_status.json'
            
            all_completed = False
            if upstream_status_file.exists():
                try:
                    import json
                    with open(upstream_status_file, 'r') as f:
                        status_data = json.load(f)
                    # Check if all agents are completed
                    all_completed = all(
                        details.get('status') == 'completed'
                        for details in status_data.values()
                    )
                except Exception:
                    # If we can't read status, assume not complete
                    all_completed = False
            
            if all_completed:
                self.console.print(f"[bold green]>> Upstream workflow '{upstream_name}' already completed, using existing data[/bold green]")
            else:
                # 3. Run Upstream Workflow
                # Only initialize workflow if we need to run it
                self.console.print(f"[bold cyan]>> Recursive: Executing upstream workflow '{upstream_name}'...[/bold cyan]")
                upstream_wf = self.__class__(
                    constructor_path=str(upstream_config_path),
                    user_code_path=self.user_code_path,
                    default_path=self.default_path,
                    use_tools=self.use_tools,
                    run_upstream=False  # Don't trigger recursive check
                )
                result = upstream_wf.run() # Execute synchronously

                # Handle batch job submission
                # Returns: ('success', {}) when complete, None when batch jobs pending
                if result is None:
                    self.console.print(f"[blue]⏳ Upstream workflow '{upstream_name}' has pending batch jobs.[/blue]")
                    self.console.print(f"[blue]Please wait for batch completion and run this command again:[/blue]")
                    self.console.print(f"[blue]  agac run -a {self.agent_name} --upstream[/blue]")
                    return None  # Signal to caller that we should exit gracefully

                # Upstream completed successfully - continue to link artifacts
                status, summary = result

            # 4. Symlink Artifacts (The "Symlink Strategy")
            self._link_upstream_artifacts(upstream_name)

            self.console.print(f"[bold green]>> Recursive: Ready to use upstream data from '{upstream_name}'[/bold green]")

            # Return success to signal upstream is ready
            return True

        except Exception as e:
            logger.error(f"Failed to execute upstream workflow {upstream_name}: {e}")
            raise RuntimeError(f"Recursive execution failed for {upstream_name}") from e

    def _link_workflow_artifacts(self, source_workflow: str, target_workflow: str) -> None:
        """
        Link source workflow's output to target workflow's staging.

        Args:
            source_workflow: Name of the workflow providing output
            target_workflow: Name of the workflow receiving input
        """
        workflows_root = self._get_workflows_root()

        source_target = workflows_root / source_workflow / 'agent_io' / 'target'
        target_staging = workflows_root / target_workflow / 'agent_io' / 'staging'

        if source_target.exists():
            latest_node = self._find_latest_node_dir(source_target)
            if latest_node:
                self._safe_symlink_contents(latest_node, target_staging)
                logger.info(f"Linked {latest_node} -> {target_staging}")
            else:
                logger.warning(f"No output nodes found in {source_target}")
        else:
            logger.warning(f"Source target directory does not exist: {source_target}")

    def _link_upstream_artifacts(self, upstream_name: str) -> None:
        """Link upstream workflow's output to current workflow's staging."""
        self._link_workflow_artifacts(upstream_name, self.agent_name)

    def _find_latest_node_dir(self, target_dir: Path) -> Optional[Path]:
        """Find the most recent node directory in target."""
        nodes = [p for p in target_dir.iterdir() if p.is_dir() and p.name.startswith('node_')]
        if not nodes:
            return None
        # Sort by creation time or name? Name usually has index 'node_0', 'node_1'.
        # Let's sort by modification time to be safe for 'latest' run.
        return max(nodes, key=lambda p: p.stat().st_mtime)

    def _safe_symlink_folder(self, src: Path, dst: Path):
        """Symlink a folder, falling back to copy."""
        if not src.exists():
            return
        
        # Clear destination if it exists
        if dst.exists():
            if dst.is_symlink() or dst.is_file():
                dst.unlink()
            else:
                shutil.rmtree(dst)
        
        try:
            os.symlink(src, dst)
            logger.debug(f"Symlinked {src} -> {dst}")
        except OSError:
            logger.warning(f"Symlink failed, falling back to copy: {src} -> {dst}")
            shutil.copytree(src, dst)

    def _validate_safe_path(self, path: Path, base_dir: Path) -> bool:
        """Validate path doesn't escape base directory (path traversal protection)."""
        try:
            resolved = path.resolve()
            base_resolved = base_dir.resolve()
            return str(resolved).startswith(str(base_resolved))
        except (OSError, ValueError):
            return False

    def _safe_symlink_contents(self, src_dir: Path, dst_dir: Path):
        """Symlink all files from src_dir into dst_dir with path traversal protection."""
        workflows_root = self._get_workflows_root()

        # Validate both directories are within workflows root
        if not self._validate_safe_path(src_dir, workflows_root):
            logger.warning(f"Rejecting symlink: source {src_dir} outside workspace")
            return
        if not self._validate_safe_path(dst_dir, workflows_root):
            logger.warning(f"Rejecting symlink: destination {dst_dir} outside workspace")
            return

        if not dst_dir.exists():
            dst_dir.mkdir(parents=True)

        for item in src_dir.iterdir():
            # Skip hidden files and validate name doesn't contain path traversal
            if item.name.startswith('.') or '..' in item.name:
                continue

            dst_item = dst_dir / item.name

            if dst_item.exists():
                if dst_item.is_symlink() or dst_item.is_file():
                    dst_item.unlink()
                else:
                    shutil.rmtree(dst_item)

            try:
                os.symlink(item, dst_item)
            except OSError:
                if item.is_dir():
                    shutil.copytree(item, dst_item)
                else:
                    shutil.copy2(item, dst_item)

    def _get_workflows_root(self) -> Path:
        """Get the root directory containing all workflows."""
        current_config_path = Path(self.constructor_path)
        # Assumes: .../workflows/CURRENT/agent_config/current.yml
        return current_config_path.parents[2]

    def _resolve_downstream_workflows(self) -> bool:
        """
        Execute all downstream workflows after current workflow completes.

        Returns:
            True if all downstream workflows completed successfully,
            False if any downstream has pending batch jobs.
        """
        if not self.run_downstream:
            return True

        logger.info(
            f"Checking downstream workflows for {self.agent_name}...",
            extra={'operation': 'resolve_downstream'}
        )

        # Lazy-initialize workspace index
        if self._workspace_index is None:
            from agent_actions.orchestration.workspace_index import WorkspaceIndex
            self._workspace_index = WorkspaceIndex(self._get_workflows_root())
            self._workspace_index.scan_workspace()

        # Get sorted downstream workflows
        try:
            downstream_order = self._workspace_index.topological_sort_downstream(
                self.agent_name
            )
        except Exception as e:
            logger.error(f"Failed to compute downstream order: {e}")
            raise

        if not downstream_order:
            self.console.print(f"[dim]No downstream workflows found for {self.agent_name}[/dim]")
            return True

        self.console.print(
            f"\n[bold cyan]>> Found {len(downstream_order)} downstream workflow(s): "
            f"{downstream_order}[/bold cyan]"
        )

        # Execute each downstream workflow in order
        for downstream_name in downstream_order:
            result = self._execute_downstream_workflow(downstream_name)
            if result is None:
                # Batch pending
                return False

        return True

    def _execute_downstream_workflow(self, downstream_name: str):
        """
        Execute a single downstream workflow.

        Args:
            downstream_name: Name of the downstream workflow to execute.

        Returns:
            Result tuple on success, None if batch pending.
        """
        self.console.print(
            f"\n[bold cyan]>> Downstream: Executing workflow '{downstream_name}'...[/bold cyan]"
        )

        # Locate downstream config
        downstream_config_path = self._get_workflows_root() / downstream_name / 'agent_config' / f'{downstream_name}.yml'

        if not downstream_config_path.exists():
            raise FileNotFoundError(
                f"Downstream workflow config not found at {downstream_config_path}"
            )

        # Link current workflow's output to downstream's staging
        self._link_downstream_artifacts(downstream_name)

        # Create new workflow instance (without recursive downstream)
        downstream_wf = self.__class__(
            constructor_path=str(downstream_config_path),
            user_code_path=self.user_code_path,
            default_path=self.default_path,
            use_tools=self.use_tools,
            run_upstream=False,   # Don't re-run upstream
            run_downstream=False  # Don't recurse downstream
        )

        result = downstream_wf.run()

        if result is None:
            self.console.print(
                f"[blue]⏳ Downstream workflow '{downstream_name}' has pending batch jobs.[/blue]"
            )
            self.console.print(
                f"[blue]Please wait for batch completion and run this command again:[/blue]"
            )
            self.console.print(
                f"[blue]  agac run -a {self.agent_name} --downstream[/blue]"
            )
            return None

        self.console.print(
            f"[bold green]>> Downstream: Workflow '{downstream_name}' completed[/bold green]"
        )
        return result

    def _link_downstream_artifacts(self, downstream_name: str) -> None:
        """Link current workflow's output to downstream workflow's staging."""
        self._link_workflow_artifacts(self.agent_name, downstream_name)

    async def async_run(self, concurrency_limit: int = 5):
        """
        Execute workflow level-by-level with parallelism within each level.

        Args:
            concurrency_limit: Maximum concurrent agents within a level (default 5)
        """
        # Initialize correlation context
        previous_context = CorrelationContext.get_context()
        try:
            CorrelationContext.start_workflow(self.agent_name)
            should_continue = self._resolve_upstream_workflows()
            if not should_continue:
                # Upstream has pending batch jobs, exit gracefully
                if previous_context:
                    CorrelationContext.set_context(previous_context)
                else:
                    CorrelationContext.clear_context()
                return None
        except Exception as e:
            if previous_context:
                CorrelationContext.set_context(previous_context)
            else:
                CorrelationContext.clear_context()
            raise e
        workflow_start = datetime.now()

        # Log session separator for file-based logging
        correlation_id = CorrelationContext.get_correlation_id()
        separator = f"====== {workflow_start.strftime('%H:%M:%S.%f')[:-3]} | {correlation_id[:8] if correlation_id else 'unknown'} ======"
        logger.info(separator)

        logger.info(
            "Workflow started (async)",
            extra={
                'operation': 'workflow_start_async',
                'workflow_name': self.agent_name,
                'agent_count': len(self.execution_order),
                'concurrency_limit': concurrency_limit
            }
        )

        try:
            levels = self.action_level_orchestrator.compute_execution_levels()
            self.action_level_orchestrator.log_execution_levels(levels, self.agent_indices)

            # Execute each level
            for level_idx, level_agents in enumerate(levels):
                # Set agent context for each agent in the level
                for agent_name in level_agents:
                    if agent_name in self.agent_indices:
                        CorrelationContext.set_agent(agent_name, self.agent_indices[agent_name])

                level_complete = await self.action_level_orchestrator.execute_level_async(
                    level_idx,
                    level_agents,
                    self.agent_indices,
                    self.state_manager,
                    self.agent_executor,
                    concurrency_limit
                )

                # If batch jobs pending, stop workflow
                if not level_complete:
                    return

            # Workflow complete
            self._finalize_workflow()

            # Log successful completion
            duration = (datetime.now() - workflow_start).total_seconds()
            logger.info(
                "Workflow completed successfully (async)",
                extra={
                    'operation': 'workflow_complete_async',
                    'workflow_name': self.agent_name,
                    'duration': duration,
                    'agent_count': len(self.execution_order),
                    'success': True
                }
            )

            # Execute downstream workflows if requested
            downstream_success = self._resolve_downstream_workflows()
            if not downstream_success:
                # Downstream has pending batch jobs
                return None

            # Return success tuple to distinguish from batch pending (None)
            return ('success', {})

        except Exception as e:
            duration = (datetime.now() - workflow_start).total_seconds()
            logger.exception(
                "Workflow failed (async)",
                extra={
                    'operation': 'workflow_failed_async',
                    'workflow_name': self.agent_name,
                    'duration': duration,
                    'agent_count': len(self.execution_order),
                    'error': str(e),
                    'error_type': type(e).__name__
                }
            )
            self._handle_workflow_error(e)
            raise
        finally:
            # Restore previous context
            if previous_context:
                CorrelationContext.set_context(previous_context)
            else:
                CorrelationContext.clear_context()

    def run(self):
        """Execute workflow sequentially."""
        # Initialize correlation context
        previous_context = CorrelationContext.get_context()
        try:
            CorrelationContext.start_workflow(self.agent_name)
            should_continue = self._resolve_upstream_workflows()
            if not should_continue:
                # Upstream has pending batch jobs, exit gracefully
                if previous_context:
                    CorrelationContext.set_context(previous_context)
                else:
                    CorrelationContext.clear_context()
                return None  # Return None to indicate incomplete workflow
        except Exception as e:
            if previous_context:
                CorrelationContext.set_context(previous_context)
            else:
                CorrelationContext.clear_context()
            raise e

        workflow_start = datetime.now()

        # Log session separator for file-based logging
        correlation_id = CorrelationContext.get_correlation_id()
        separator = f"====== {workflow_start.strftime('%H:%M:%S.%f')[:-3]} | {correlation_id[:8] if correlation_id else 'unknown'} ======"
        logger.info(separator)

        logger.info(
            "Workflow started",
            extra={
                'operation': 'workflow_start',
                'workflow_name': self.agent_name,
                'agent_count': len(self.execution_order)
            }
        )

        try:
            total_agents = len(self.execution_order)
            self.console.print(f'Found {total_agents} agents to run.')

            for idx, agent_name in enumerate(self.execution_order):
                # Set agent context for correlation
                CorrelationContext.set_agent(agent_name, idx)

                should_stop = self._run_single_agent(idx, agent_name, total_agents)
                if should_stop:
                    # Batch submitted or workflow needs to stop
                    break

            # Check if workflow is complete
            if self.state_manager.is_workflow_complete():
                self._finalize_workflow()

                # Log successful completion
                duration = (datetime.now() - workflow_start).total_seconds()
                logger.info(
                    "Workflow completed successfully",
                    extra={
                        'operation': 'workflow_complete',
                        'workflow_name': self.agent_name,
                        'duration': duration,
                        'agent_count': len(self.execution_order),
                        'success': True
                    }
                )

                # Execute downstream workflows if requested
                downstream_success = self._resolve_downstream_workflows()
                if not downstream_success:
                    # Downstream has pending batch jobs
                    return None

                # Return success tuple to distinguish from batch pending (None)
                return ('success', {})

        except Exception as e:
            duration = (datetime.now() - workflow_start).total_seconds()
            logger.debug(
                "Workflow failed",
                extra={
                    'operation': 'workflow_failed',
                    'workflow_name': self.agent_name,
                    'duration': duration,
                    'agent_count': len(self.execution_order),
                    'error': str(e),
                    'error_type': type(e).__name__
                },
                exc_info=True
            )
            self._handle_workflow_error(e)
            raise
        finally:
            # Restore previous context
            if previous_context:
                CorrelationContext.set_context(previous_context)
            else:
                CorrelationContext.clear_context()

    def _run_single_agent(self, idx: int, agent_name: str, total_agents: int) -> bool:
        """
        Run a single agent in sequential mode.

        Returns:
            bool: True if workflow should stop, False to continue
        """
        agent_config = self.agent_configs[agent_name]
        start_time = datetime.now()

        self.console.print(
            f"{start_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} "
            f"START agent: [bold]{agent_name}[/bold]..."
        )

        # Check if already completed
        if self.state_manager.is_completed(agent_name):
            self._log_agent_skip(idx, agent_name, total_agents, start_time)
            return False

        # Execute agent
        is_last = idx == len(self.execution_order) - 1
        result = self.agent_executor.execute_agent_sync(
            agent_name,
            idx,
            agent_config,
            is_last
        )

        # Log result
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        self._log_agent_result(idx, agent_name, total_agents, result, end_time, duration)

        # Handle result
        if result.success:
            # If batch was submitted, stop workflow to wait for completion
            if result.status == 'batch_submitted':
                return True  # Signal to stop workflow

            if result.output_folder and result.status == 'completed':
                self.ephemeral_directories.append({
                    'output_folder': result.output_folder,
                    'ephemeral': agent_config.get('ephemeral', False)
                })
            return False  # Continue to next agent
        else:
            raise result.error

    def _log_agent_skip(self, idx: int, agent_name: str, total_agents: int, start_time: datetime):
        """Log skipped agent."""
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        self.console.print(
            f"{end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} "
            f"[yellow]SKIP[/yellow] [bold]{agent_name}[/bold] in {duration:.2f}s"
        )

    def _log_agent_result(
        self,
        idx: int,
        agent_name: str,
        total_agents: int,
        result,
        end_time: datetime,
        duration: float
    ):
        """Log agent execution result."""
        status_map = {
            'completed': ('[green]OK[/green]', ''),
            'batch_submitted': ('[yellow]SUBMITTED[/yellow]', ' (batch)'),
            'failed': ('[red]FAIL[/red]', '')
        }

        status_color, suffix = status_map.get(result.status, ('[yellow]UNKNOWN[/yellow]', ''))

        self.console.print(
            f"{end_time.strftime('%H:%M:%S')} | {idx + 1}/{total_agents} "
            f"{status_color} [bold]{agent_name}[/bold]{suffix} in {duration:.2f}s"
        )

    def _finalize_workflow(self):
        """Finalize workflow execution."""
        self.console.print('\n[bold]Workflow Summary:[/bold]')

        for agent_name in self.execution_order:
            status = self.state_manager.get_status(agent_name)
            color = 'green' if status == 'completed' else 'red' if status == 'failed' else 'yellow'
            self.console.print(f'- {agent_name}: [{color}]{status}[/{color}]')

        # Process final output
        self.output_processor.process_final_output(self.ephemeral_directories)

        self.console.print('\n🎉 [bold green]Workflow Complete[/bold green]')
        self.console.print('Done.')

    def _handle_workflow_error(self, error: Exception):
        """Handle workflow execution error."""
        self.console.print(f'\n❌ [bold red]Workflow failed with error:[/bold red] {error}')
        self.failed = True

        # Mark running agent as failed
        failed_agent = self.state_manager.mark_running_as_failed()




