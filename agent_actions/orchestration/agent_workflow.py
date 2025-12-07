"""
Agent workflow orchestration - Refactored version.

This is the refactored version of agent_workflow.py with reduced complexity.
Original: 733 lines, CC 176, MI 7.8
Target: <200 lines, CC <50, MI >20

Key improvements:
- Extracted specialized modules for state, skip logic, batch handling, etc.
- Reduced method complexity through delegation
- Eliminated duplicate code
- Improved maintainability and testability
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
        parent_pipeline: Optional[str] = None
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

    async def async_run(self, concurrency_limit: int = 5):
        """
        Execute workflow level-by-level with parallelism within each level.

        Args:
            concurrency_limit: Maximum concurrent agents within a level (default 5)
        """
        # Initialize correlation context
        CorrelationContext.start_workflow(self.agent_name)
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

        except Exception as e:
            duration = (datetime.now() - workflow_start).total_seconds()
            logger.error(
                "Workflow failed (async)",
                extra={
                    'operation': 'workflow_failed_async',
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
            # Clear correlation context
            CorrelationContext.clear_context()

    def run(self):
        """Execute workflow sequentially."""
        # Initialize correlation context
        CorrelationContext.start_workflow(self.agent_name)
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

        except Exception as e:
            duration = (datetime.now() - workflow_start).total_seconds()
            logger.error(
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
            # Clear correlation context
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

    # Backward compatibility properties and methods
    @property
    def agent_status(self):
        """Provide backward compatibility for agent_status access."""
        return self.state_manager.agent_status

    def _update_status(self, agent_name: str, status: str, **metadata):
        """Backward compatibility for status updates."""
        self.state_manager.update_status(agent_name, status, **metadata)

    def _compute_execution_levels(self):
        """
        Compute execution levels from dependency graph.

        Backward compatibility implementation that works with or without action_level_orchestrator.
        """
        if hasattr(self, 'action_level_orchestrator'):
            return self.action_level_orchestrator.compute_execution_levels()

        # Fallback implementation for tests/mocks
        from agent_actions.shared.exceptions import WorkflowError

        deps_map = {
            agent: self.agent_configs[agent].get('dependencies', [])
            for agent in self.execution_order
        }

        levels = []
        assigned = set()

        while len(assigned) < len(self.execution_order):
            current_level = [
                agent for agent in self.execution_order
                if agent not in assigned
                and all(dep in assigned for dep in deps_map[agent])
            ]

            if not current_level:
                remaining_agents = set(self.execution_order) - assigned
                unsatisfied_deps = {
                    agent: [dep for dep in deps_map[agent] if dep not in assigned]
                    for agent in remaining_agents
                }
                error_details = '\n'.join([
                    f"  - {agent} waiting for: {', '.join(deps)}"
                    for agent, deps in unsatisfied_deps.items()
                ])
                raise WorkflowError(
                    'circular_dependency',
                    f'Circular dependency detected - cannot compute execution levels.\n\n'
                    f'Agents blocked:\n{error_details}',
                    context={
                        'assigned': list(assigned),
                        'remaining': list(remaining_agents),
                        'unsatisfied_dependencies': unsatisfied_deps
                    }
                )

            levels.append(current_level)
            assigned.update(current_level)

        return levels

    def _should_skip_agent(self, agent_config: Dict[str, Any], previous_outputs: Dict[str, Any] = None) -> bool:
        """Backward compatibility for should_skip_agent."""
        if hasattr(self, 'skip_evaluator'):
            return self.skip_evaluator.should_skip_agent(agent_config, previous_outputs)
        return False  # Fallback for tests

    def _get_previous_outputs(self, current_idx: int) -> Dict[str, Any]:
        """Backward compatibility for get_previous_outputs."""
        return self.output_manager.get_previous_outputs(current_idx)

    def _create_passthrough_output(self, idx: int, agent_type: str):
        """Backward compatibility for create_passthrough_output."""
        self.output_manager.create_passthrough_output(idx, agent_type)

    def _handle_batch_agent(self, agent_name: str, idx: int):
        """Backward compatibility for handle_batch_agent."""
        agent_io_path = Path(self.agent_runner.get_agent_folder(self.agent_name))
        output_directory = str(agent_io_path / 'target' / f'node_{idx}_{agent_name}')
        agent_config = self.agent_configs.get(agent_name, {})
        return self.batch_manager.handle_batch_agent(agent_name, idx, output_directory, agent_config)

    def _log_execution_levels(self, levels: List[List[str]]):
        """Backward compatibility for log_execution_levels."""
        self.action_level_orchestrator.log_execution_levels(levels, self.agent_indices)

    def _should_use_parallel_execution(self) -> bool:
        """
        Determine if workflow should use parallel execution.

        Backward compatibility implementation that works with or without action_level_orchestrator.
        """
        if hasattr(self, 'action_level_orchestrator'):
            return self.action_level_orchestrator.should_use_parallel_execution()

        # Fallback implementation for tests/mocks
        levels = self._compute_execution_levels()
        return any(len(level) > 1 for level in levels)

    def _get_input_directory(self, idx: int) -> str:
        """Backward compatibility for get_input_directory."""
        if hasattr(self, 'output_manager'):
            return self.output_manager.get_input_directory(idx)

        # Fallback for tests/mocks
        agent_folder = Path(self.agent_runner.get_agent_folder(self.agent_name))
        if idx == 0:
            return str(agent_folder / 'staging')

        current_agent = self.execution_order[idx]
        if hasattr(self, 'loop_correlator'):
            loop_consumption_map = self.loop_correlator.detect_explicit_loop_consumption(
                self.execution_order,
                self.agent_configs
            )
            if current_agent in loop_consumption_map:
                consumption_config = loop_consumption_map[current_agent]
                loop_sources = consumption_config['loop_agents']
                correlated_dir = self.loop_correlator.prepare_correlated_input(
                    current_agent,
                    loop_sources,
                    idx
                )
                if correlated_dir:
                    return correlated_dir

        prev_agent = self.execution_order[idx - 1]
        return str(agent_folder / 'target' / f'node_{idx - 1}_{prev_agent}')

    def _setup_correlation_if_needed(self, idx: int):
        """Backward compatibility for setup_correlation_if_needed."""
        correlation_wrapper = self.output_manager.setup_correlation_wrapper(
            idx,
            self.agent_runner.setup_directories
        )
        if correlation_wrapper:
            self._original_setup_directories = self.agent_runner.setup_directories
            self.agent_runner.setup_directories = correlation_wrapper

    async def _run_single_agent_async(self, agent_name: str, agent_idx: int):
        """Backward compatibility for async single agent execution."""
        agent_config = self.agent_configs[agent_name]
        is_last = agent_idx == len(self.execution_order) - 1

        result = await self.agent_executor.execute_agent_async(
            agent_name,
            agent_idx,
            agent_config,
            is_last
        )

        if result.success and result.output_folder and result.status == 'completed':
            self.ephemeral_directories.append({
                'output_folder': result.output_folder,
                'ephemeral': agent_config.get('ephemeral', False)
            })

        if not result.success:
            raise result.error
