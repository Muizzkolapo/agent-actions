"""
Single agent execution module.

Handles individual agent execution with batch support.
Extracted from agent_workflow.py to reduce run() method complexity.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from rich.console import Console


class AgentExecutionResult:
    """Result of agent execution."""

    def __init__(
        self,
        success: bool,
        output_folder: Optional[str] = None,
        status: str = 'completed',
        error: Optional[Exception] = None,
        duration: float = 0.0
    ):
        self.success = success
        self.output_folder = output_folder
        self.status = status  # 'completed', 'batch_submitted', 'failed'
        self.error = error
        self.duration = duration


class AgentExecutor:
    """
    Executes individual agents with full lifecycle management.

    Responsibilities:
    - Execute single agent (sync or async)
    - Handle batch mode detection and submission
    - Manage correlation setup
    """

    def __init__(
        self,
        agent_runner,
        state_manager,
        skip_evaluator,
        batch_manager,
        output_manager,
        console: Optional[Console] = None
    ):
        """
        Initialize agent executor.

        Args:
            agent_runner: AgentRunner instance
            state_manager: AgentStateManager instance
            skip_evaluator: SkipEvaluator instance
            batch_manager: BatchLifecycleManager instance
            output_manager: AgentOutputManager instance
            console: Rich console for output
        """
        self.agent_runner = agent_runner
        self.state_manager = state_manager
        self.skip_evaluator = skip_evaluator
        self.batch_manager = batch_manager
        self.output_manager = output_manager
        self.console = console or Console()

    def execute_agent_sync(
        self,
        agent_name: str,
        agent_idx: int,
        agent_config: Dict[str, Any],
        is_last_agent: bool
    ) -> AgentExecutionResult:
        """
        Execute a single agent synchronously.

        Args:
            agent_name: Name of the agent
            agent_idx: Index in execution order
            agent_config: Agent configuration
            is_last_agent: Whether this is the last agent in workflow

        Returns:
            AgentExecutionResult with execution details
        """
        start_time = datetime.now()
        current_status = self.state_manager.get_status(agent_name)

        # Check 1: Already completed
        if current_status == 'completed':
            return AgentExecutionResult(
                success=True,
                status='completed',
                duration=0.0
            )

        # Check 2: Batch job submitted, check status
        if current_status == 'batch_submitted':
            return self._handle_batch_check(agent_name, agent_idx, agent_config, start_time)

        # Check 3: Should skip agent?
        previous_outputs = self.output_manager.get_previous_outputs(agent_idx)
        if self.skip_evaluator.should_skip_agent(agent_config, previous_outputs):
            self.console.print(f'Skipping agent {agent_name} due to WHERE clause condition')
            self.output_manager.create_passthrough_output(agent_idx, agent_name)
            self.state_manager.update_status(agent_name, 'completed')
            return AgentExecutionResult(
                success=True,
                status='completed',
                duration=(datetime.now() - start_time).total_seconds()
            )

        # Execute the agent
        return self._execute_agent_run(
            agent_name,
            agent_idx,
            agent_config,
            is_last_agent,
            start_time
        )

    async def execute_agent_async(
        self,
        agent_name: str,
        agent_idx: int,
        agent_config: Dict[str, Any],
        is_last_agent: bool
    ) -> AgentExecutionResult:
        """
        Execute a single agent asynchronously.

        Args:
            agent_name: Name of the agent
            agent_idx: Index in execution order
            agent_config: Agent configuration
            is_last_agent: Whether this is the last agent in workflow

        Returns:
            AgentExecutionResult with execution details
        """
        start_time = datetime.now()
        current_status = self.state_manager.get_status(agent_name)

        # Check 1: Already completed
        if current_status == 'completed':
            return AgentExecutionResult(
                success=True,
                status='completed',
                duration=0.0
            )

        # Check 2: Batch job submitted, check status
        if current_status == 'batch_submitted':
            return await self._handle_batch_check_async(agent_name, agent_idx, agent_config, start_time)

        # Check 3: Should skip agent?
        previous_outputs = self.output_manager.get_previous_outputs(agent_idx)
        if self.skip_evaluator.should_skip_agent(agent_config, previous_outputs):
            self.console.print(f'  [yellow]Skipping {agent_name} (WHERE clause)[/yellow]')
            self.output_manager.create_passthrough_output(agent_idx, agent_name)
            self.state_manager.update_status(agent_name, 'completed')
            return AgentExecutionResult(
                success=True,
                status='completed',
                duration=(datetime.now() - start_time).total_seconds()
            )

        # Execute the agent
        return await self._execute_agent_run_async(
            agent_name,
            agent_idx,
            agent_config,
            is_last_agent,
            start_time
        )

    def _handle_batch_check(
        self,
        agent_name: str,
        agent_idx: int,
        agent_config: Dict[str, Any],
        start_time: datetime
    ) -> AgentExecutionResult:
        """Handle batch job status checking (synchronous)."""
        self.state_manager.update_status(agent_name, 'checking_batch')
        agent_io_path = Path(self.agent_runner.get_agent_folder(self.agent_runner.workflow_name))
        output_directory = str(agent_io_path / 'target' / f'node_{agent_idx}_{agent_name}')

        output_folder, batch_status = self.batch_manager.handle_batch_agent(
            agent_name,
            agent_idx,
            output_directory,
            agent_config
        )

        duration = (datetime.now() - start_time).total_seconds()

        if batch_status == 'completed':
            self.state_manager.update_status(agent_name, 'completed')
            return AgentExecutionResult(
                success=True,
                output_folder=output_folder,
                status='completed',
                duration=duration
            )
        elif batch_status == 'in_progress':
            self.state_manager.update_status(agent_name, 'batch_submitted')
            return AgentExecutionResult(
                success=True,
                status='batch_submitted',
                duration=duration
            )
        else:
            self.state_manager.update_status(agent_name, 'failed')
            error = Exception(f'Batch job for {agent_name} failed')
            return AgentExecutionResult(
                success=False,
                status='failed',
                error=error,
                duration=duration
            )

    async def _handle_batch_check_async(
        self,
        agent_name: str,
        agent_idx: int,
        agent_config: Dict[str, Any],
        start_time: datetime
    ) -> AgentExecutionResult:
        """Handle batch job status checking (asynchronous)."""
        self.state_manager.update_status(agent_name, 'checking_batch')
        agent_io_path = Path(self.agent_runner.get_agent_folder(self.agent_runner.workflow_name))
        output_directory = str(agent_io_path / 'target' / f'node_{agent_idx}_{agent_name}')

        output_folder, batch_status = await asyncio.to_thread(
            self.batch_manager.handle_batch_agent,
            agent_name,
            agent_idx,
            output_directory,
            agent_config
        )

        duration = (datetime.now() - start_time).total_seconds()

        if batch_status == 'completed':
            self.state_manager.update_status(agent_name, 'completed')
            self.console.print(f'  [green]✓ {agent_name} (batch completed, {duration:.2f}s)[/green]')
            return AgentExecutionResult(
                success=True,
                output_folder=output_folder,
                status='completed',
                duration=duration
            )
        elif batch_status == 'in_progress':
            self.state_manager.update_status(agent_name, 'batch_submitted')
            self.console.print(f'  [yellow]→ {agent_name}: batch still in progress ({duration:.2f}s)[/yellow]')
            return AgentExecutionResult(
                success=True,
                status='batch_submitted',
                duration=duration
            )
        else:
            self.state_manager.update_status(agent_name, 'failed')
            self.console.print(f'  [red]✗ {agent_name}: batch failed ({duration:.2f}s)[/red]')
            error = Exception(f'Batch job for {agent_name} failed')
            return AgentExecutionResult(
                success=False,
                status='failed',
                error=error,
                duration=duration
            )

    def _execute_agent_run(
        self,
        agent_name: str,
        agent_idx: int,
        agent_config: Dict[str, Any],
        is_last_agent: bool,
        start_time: datetime
    ) -> AgentExecutionResult:
        """Execute agent run (synchronous)."""
        self.state_manager.update_status(agent_name, 'running')

        # Setup correlation if needed
        original_setup = self._setup_correlation(agent_idx)

        try:
            # Run the agent
            output_folder = self.agent_runner.run_agent(
                agent_config,
                agent_name,
                None,  # previous_agent_type not needed with new setup
                agent_idx,
                is_last_agent
            )

            duration = (datetime.now() - start_time).total_seconds()

            # Check if batch mode
            batch_status = self._check_batch_submission(agent_name, agent_idx)
            if batch_status == 'batch_submitted':
                self.state_manager.update_status(agent_name, 'batch_submitted')
                return AgentExecutionResult(
                    success=True,
                    status='batch_submitted',
                    duration=duration
                )
            elif batch_status == 'passthrough':
                self.state_manager.update_status(agent_name, 'completed')
                return AgentExecutionResult(
                    success=True,
                    output_folder=output_folder,
                    status='completed',
                    duration=duration
                )

            # Normal completion
            self.state_manager.update_status(agent_name, 'completed')

            return AgentExecutionResult(
                success=True,
                output_folder=output_folder,
                status='completed',
                duration=duration
            )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            self.state_manager.update_status(agent_name, 'failed')

            return AgentExecutionResult(
                success=False,
                status='failed',
                error=e,
                duration=duration
            )

        finally:
            # Restore original setup
            if original_setup:
                self.agent_runner.setup_directories = original_setup

    async def _execute_agent_run_async(
        self,
        agent_name: str,
        agent_idx: int,
        agent_config: Dict[str, Any],
        is_last_agent: bool,
        start_time: datetime
    ) -> AgentExecutionResult:
        """Execute agent run (asynchronous)."""
        self.state_manager.update_status(agent_name, 'running')

        # Setup correlation if needed
        original_setup = self._setup_correlation(agent_idx)

        try:
            # Run the agent in thread pool
            output_folder = await asyncio.to_thread(
                self.agent_runner.run_agent,
                agent_config,
                agent_name,
                None,
                agent_idx,
                is_last_agent
            )

            duration = (datetime.now() - start_time).total_seconds()

            # Check if batch mode
            batch_status = self._check_batch_submission(agent_name, agent_idx)
            if batch_status == 'batch_submitted':
                self.state_manager.update_status(agent_name, 'batch_submitted')
                self.console.print(f'  [yellow]→ {agent_name}: batch submitted[/yellow]')
                return AgentExecutionResult(
                    success=True,
                    status='batch_submitted',
                    duration=duration
                )

            # Normal completion
            self.state_manager.update_status(agent_name, 'completed')
            self.console.print(f'  [green]✓ {agent_name} ({duration:.2f}s)[/green]')

            return AgentExecutionResult(
                success=True,
                output_folder=output_folder,
                status='completed',
                duration=duration
            )

        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            self.console.print(f'  [red]✗ {agent_name} failed: {e}[/red]')
            self.state_manager.update_status(agent_name, 'failed')

            return AgentExecutionResult(
                success=False,
                status='failed',
                error=e,
                duration=duration
            )

        finally:
            # Restore original setup
            if original_setup:
                self.agent_runner.setup_directories = original_setup

    def _setup_correlation(self, agent_idx: int) -> Optional[callable]:
        """Setup loop correlation if needed, return original setup function."""
        correlation_wrapper = self.output_manager.setup_correlation_wrapper(
            agent_idx,
            self.agent_runner.setup_directories
        )

        if correlation_wrapper:
            original = self.agent_runner.setup_directories
            self.agent_runner.setup_directories = correlation_wrapper
            return original

        return None

    def _check_batch_submission(self, agent_name: str, agent_idx: int) -> Optional[str]:
        """Check if batch jobs were submitted."""
        agent_io_path = Path(self.agent_runner.get_agent_folder(self.agent_runner.workflow_name))
        return self.batch_manager.check_batch_submission(agent_name, agent_idx, agent_io_path)
