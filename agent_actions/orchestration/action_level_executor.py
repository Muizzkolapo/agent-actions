"""
Action-level execution orchestration module.

Handles dependency analysis, action-level computation, and parallel execution.
Extracted from agent_workflow.py to consolidate parallel execution logic.

An "Action" is a stage of execution where multiple agents can run in parallel
if they have no inter-dependencies.
"""

import asyncio
from datetime import datetime
from typing import List, Dict, Any, Optional
from rich.console import Console


class ActionLevelOrchestrator:
    """
    Orchestrates agent execution by dependency levels.

    Responsibilities:
    - Compute execution levels from dependency graph
    - Execute agents in parallel within levels
    - Manage concurrency limits
    - Handle level-based error propagation
    """

    def __init__(
        self,
        execution_order: List[str],
        agent_configs: Dict[str, Dict[str, Any]],
        console: Optional[Console] = None
    ):
        """
        Initialize level orchestrator.

        Args:
            execution_order: List of agent names in topological order
            agent_configs: Dictionary of agent configurations
            console: Rich console for output
        """
        self.execution_order = execution_order
        self.agent_configs = agent_configs
        self.console = console or Console()

    def compute_execution_levels(self) -> List[List[str]]:
        """
        Compute execution levels from dependency graph.

        Agents in the same level have no inter-dependencies and can run in parallel.

        Returns:
            List of execution levels, where each level is a list of agent names

        Raises:
            WorkflowError: If circular dependencies detected
        """
        from agent_actions.errors import WorkflowError  # New modular pattern!

        # Build dependency map
        deps_map = {
            agent: self.agent_configs[agent].get('dependencies', [])
            for agent in self.execution_order
        }

        levels = []
        assigned = set()

        while len(assigned) < len(self.execution_order):
            # Find agents whose dependencies are all satisfied
            current_level = [
                agent for agent in self.execution_order
                if agent not in assigned
                and all(dep in assigned for dep in deps_map[agent])
            ]

            if not current_level:
                # Circular dependency detected
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

    def should_use_parallel_execution(self) -> bool:
        """
        Determine if workflow should use parallel execution.

        Returns:
            True if any execution level has more than 1 agent
        """
        levels = self.compute_execution_levels()
        return any(len(level) > 1 for level in levels)

    def log_execution_levels(self, levels: List[List[str]], agent_indices: Dict[str, int]):
        """
        Log execution levels for user transparency.

        Args:
            levels: List of execution levels
            agent_indices: Dictionary mapping agent names to indices
        """
        self.console.print(f'[blue]📊 Execution: {len(levels)} action(s)[/blue]')

        for i, level in enumerate(levels):
            if len(level) > 1:
                sorted_agents = sorted(level, key=lambda a: agent_indices[a])
                agent_list = ', '.join(sorted_agents)
                self.console.print(
                    f"[blue]  Action {i}: {len(level)} agents in parallel - {agent_list}[/blue]"
                )
            else:
                self.console.print(f'[dim]  Action {i}: {level[0]} (sequential)[/dim]')

    async def execute_level_async(
        self,
        level_idx: int,
        level_agents: List[str],
        agent_indices: Dict[str, int],
        state_manager,
        agent_executor,
        concurrency_limit: int = 5
    ) -> bool:
        """
        Execute all agents in a level asynchronously.

        Args:
            level_idx: Index of the level
            level_agents: List of agent names in this level
            agent_indices: Dictionary mapping agent names to indices
            state_manager: AgentStateManager instance
            agent_executor: AgentExecutor instance
            concurrency_limit: Maximum concurrent agents

        Returns:
            True if level completed successfully, False if batch jobs pending

        Raises:
            WorkflowError: If any agent fails during execution
        """
        from agent_actions.errors import WorkflowError  # New modular pattern!

        start_time = datetime.now()

        # Filter to pending agents only
        pending_agents = state_manager.get_pending_agents(level_agents)

        if not pending_agents:
            self.console.print(f'[yellow]Action {level_idx}: All agents complete (skipped)[/yellow]')
            return True

        self.console.print(f'[cyan]Action {level_idx}: Starting {len(pending_agents)} agent(s)...[/cyan]')

        # Single agent - execute directly
        if len(pending_agents) == 1:
            agent_name = pending_agents[0]
            original_idx = agent_indices[agent_name]
            agent_config = self.agent_configs[agent_name]
            is_last = original_idx == len(self.execution_order) - 1

            result = await agent_executor.execute_agent_async(
                agent_name,
                original_idx,
                agent_config,
                is_last
            )

            if not result.success:
                raise result.error

        # Multiple agents - execute in parallel
        else:
            self.console.print(f'[blue]  → {len(pending_agents)} agents in parallel[/blue]')
            semaphore = asyncio.Semaphore(concurrency_limit)

            async def run_with_limit(agent):
                """Run agent with semaphore limit."""
                async with semaphore:
                    original_idx = agent_indices[agent]
                    agent_config = self.agent_configs[agent]
                    is_last = original_idx == len(self.execution_order) - 1

                    return await agent_executor.execute_agent_async(
                        agent,
                        original_idx,
                        agent_config,
                        is_last
                    )

            # Execute all agents concurrently
            tasks = [run_with_limit(agent) for agent in pending_agents]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Check for errors
            errors = []
            for agent, result in zip(pending_agents, results):
                if isinstance(result, Exception):
                    errors.append((agent, result))
                elif not result.success:
                    errors.append((agent, result.error))

            if errors:
                error_details = '\n'.join([
                    f'  - {agent}: {str(exc)}'
                    for agent, exc in errors
                ])
                error_msg = f'Multiple agents failed in parallel action {level_idx}:\n{error_details}'
                raise WorkflowError('parallel_execution_failures', error_msg)

        # Check for batch submissions
        batch_pending = state_manager.get_batch_submitted_agents(level_agents)

        if batch_pending:
            # Check for partial failures
            failed_agents = state_manager.get_failed_agents(level_agents)
            if failed_agents:
                error_msg = (
                    f"Partial failure in parallel action {level_idx}: "
                    f"{', '.join(failed_agents)} failed while batch jobs were submitted"
                )
                raise WorkflowError('batch_submission_partial_failure', error_msg)

            # Batch jobs submitted, need to wait
            duration = (datetime.now() - start_time).total_seconds()
            self.console.print(
                f'[yellow]Action {level_idx}: {len(batch_pending)} batch job(s) submitted ({duration:.2f}s)[/yellow]'
            )
            self.console.print('[yellow]Run workflow again to check batch status[/yellow]')
            return False  # Level not complete

        # Level completed
        duration = (datetime.now() - start_time).total_seconds()
        self.console.print(f'[green]Action {level_idx} complete ({duration:.2f}s)[/green]')
        return True
