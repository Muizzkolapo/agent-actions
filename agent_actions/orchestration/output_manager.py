"""
Agent output management module.

Handles previous output loading, passthrough creation, and loop correlation.
Extracted from agent_workflow.py to consolidate output handling.
"""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from rich.console import Console

logger = logging.getLogger(__name__)


class AgentOutputManager:
    """
    Manages agent output operations.

    Responsibilities:
    - Load previous agent outputs with metadata
    - Create passthrough outputs for skipped agents
    - Setup loop output correlation
    - Manage input directory resolution
    """

    def __init__(
        self,
        agent_folder: Path,
        execution_order: List[str],
        agent_configs: Dict[str, Dict[str, Any]],
        agent_status: Dict[str, Dict[str, Any]],
        loop_correlator,
        console: Optional[Console] = None
    ):
        """
        Initialize output manager.

        Args:
            agent_folder: Path to agent I/O folder
            execution_order: List of agent names in execution order
            agent_configs: Dictionary of agent configurations
            agent_status: Dictionary of agent statuses
            loop_correlator: LoopOutputCorrelator instance
            console: Rich console for output
        """
        self.agent_folder = agent_folder
        self.execution_order = execution_order
        self.agent_configs = agent_configs
        self.agent_status = agent_status
        self.loop_correlator = loop_correlator
        self.console = console or Console()

    def get_previous_outputs(self, current_idx: int) -> Dict[str, Any]:
        """
        Get outputs from previously executed agents with enhanced metadata.

        Args:
            current_idx: Index of the current agent

        Returns:
            Dictionary of previous agent outputs with metadata.
            For each agent 'foo', returns:
            - previous_outputs['foo'] = [data items]
            - previous_outputs['foo_meta'] = {status, output_count, has_data, etc.}
        """
        previous_outputs = {}

        for i in range(current_idx):
            prev_agent_name = self.execution_order[i]
            output_dir = self.agent_folder / 'target' / f'node_{i}_{prev_agent_name}'

            agent_output = {
                'data': [],
                'status': self.agent_status.get(prev_agent_name, {}).get('status', 'unknown'),
                'output_count': 0,
                'output_files': [],
                'has_data': False,
                'errors': []
            }

            try:
                if output_dir.exists():
                    json_files = list(output_dir.glob('*.json'))
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
                                agent_output['errors'].append(
                                    f'Failed to read {json_file.name}: {file_error}'
                                )

                        agent_output['data'] = outputs
                        agent_output['output_count'] = len(outputs)
                        agent_output['has_data'] = len(outputs) > 0

                    # Check for passthrough marker
                    passthrough_marker = output_dir / '.passthrough_processed'
                    if passthrough_marker.exists():
                        agent_output['passthrough'] = True
                        try:
                            with open(passthrough_marker, 'r') as f:
                                agent_output['passthrough_reason'] = f.read().strip()
                        except (OSError, IOError, PermissionError) as e:
                            logger.warning(
                                "Could not read passthrough marker, using 'Unknown'",
                                extra={
                                    'operation': 'read_passthrough_marker',
                                    'file': str(passthrough_marker),
                                    'agent': prev_agent_name,
                                    'error': str(e)
                                }
                            )
                            agent_output['passthrough_reason'] = 'Unknown'
                        except Exception as e:
                            logger.error(
                                "Unexpected error reading passthrough marker",
                                extra={
                                    'operation': 'read_passthrough_marker',
                                    'file': str(passthrough_marker),
                                    'agent': prev_agent_name,
                                    'error': str(e),
                                    'error_type': type(e).__name__
                                },
                                exc_info=True
                            )
                            agent_output['passthrough_reason'] = 'Unknown'

                    # Check for skip marker
                    skip_marker = output_dir / '.agent_skipped'
                    if skip_marker.exists():
                        agent_output['skipped'] = True
                        try:
                            with open(skip_marker, 'r') as f:
                                agent_output['skip_reason'] = f.read().strip()
                        except (OSError, IOError, PermissionError) as e:
                            logger.warning(
                                "Could not read skip marker, using 'Unknown'",
                                extra={
                                    'operation': 'read_skip_marker',
                                    'file': str(skip_marker),
                                    'agent': prev_agent_name,
                                    'error': str(e)
                                }
                            )
                            agent_output['skip_reason'] = 'Unknown'
                        except Exception as e:
                            logger.error(
                                "Unexpected error reading skip marker",
                                extra={
                                    'operation': 'read_skip_marker',
                                    'file': str(skip_marker),
                                    'agent': prev_agent_name,
                                    'error': str(e),
                                    'error_type': type(e).__name__
                                },
                                exc_info=True
                            )
                            agent_output['skip_reason'] = 'Unknown'

                previous_outputs[prev_agent_name] = agent_output['data']
                previous_outputs[f'{prev_agent_name}_meta'] = agent_output

            except Exception as e:
                error_msg = f'Could not load outputs for {prev_agent_name}: {e}'
                self.console.print(f'[yellow]Warning: {error_msg}[/yellow]')
                agent_output['errors'].append(error_msg)
                previous_outputs[prev_agent_name] = []
                previous_outputs[f'{prev_agent_name}_meta'] = agent_output

        return previous_outputs

    def create_passthrough_output(self, idx: int, agent_type: str):
        """
        Create passthrough output for a skipped agent.

        Copies input files to output directory and creates skip marker.

        Args:
            idx: Index of the agent
            agent_type: Type/name of the agent
        """
        input_dir = self.get_input_directory(idx)
        output_dir = self.agent_folder / 'target' / f'node_{idx}_{agent_type}'
        output_dir.mkdir(parents=True, exist_ok=True)

        # Copy input files to output
        if os.path.exists(input_dir):
            for item in os.listdir(input_dir):
                src = os.path.join(input_dir, item)
                dst = output_dir / item
                try:
                    shutil.copy2(src, dst)
                except Exception as e:
                    self.console.print(f'[yellow]Warning: Could not copy {item}: {e}[/yellow]')

        # Create skip marker
        skip_marker = output_dir / '.agent_skipped'
        with open(skip_marker, 'w', encoding='utf-8') as f:
            f.write(f'Agent {agent_type} skipped due to WHERE clause condition')

    def get_input_directory(self, idx: int) -> str:
        """
        Get input directory for an agent, considering loop correlation.

        Args:
            idx: Index of the agent

        Returns:
            Path to input directory
        """
        # First agent uses staging directory
        if idx == 0:
            return str(self.agent_folder / 'staging')

        current_agent = self.execution_order[idx]

        # Check if agent consumes loop outputs
        loop_consumption_map = self.loop_correlator.detect_explicit_loop_consumption(
            self.execution_order,
            self.agent_configs
        )

        if current_agent in loop_consumption_map:
            consumption_config = loop_consumption_map[current_agent]
            loop_sources = consumption_config['loop_agents']
            pattern = consumption_config['pattern']

            correlated_dir = self.loop_correlator.prepare_correlated_input(
                current_agent,
                loop_sources,
                idx
            )

            if correlated_dir:
                self.console.print(
                    f'[blue]🔗 Using correlated input for {current_agent} from '
                    f'{len(loop_sources)} loop sources (pattern: {pattern})[/blue]'
                )
                return correlated_dir
            else:
                self.console.print(
                    f'[yellow]⚠️ Failed to correlate loop outputs for {current_agent}, '
                    f'falling back to standard input[/yellow]'
                )

        # Standard case: use previous agent's output
        prev_agent = self.execution_order[idx - 1]
        return str(self.agent_folder / 'target' / f'node_{idx - 1}_{prev_agent}')

    def setup_correlation_wrapper(
        self,
        idx: int,
        original_setup_directories: Callable
    ) -> Optional[Callable]:
        """
        Create a correlation-aware setup_directories wrapper if needed.

        Args:
            idx: Index of the agent
            original_setup_directories: Original setup_directories function

        Returns:
            Wrapped setup_directories function if correlation needed, None otherwise
        """
        current_agent = self.execution_order[idx]

        loop_consumption_map = self.loop_correlator.detect_explicit_loop_consumption(
            self.execution_order,
            self.agent_configs
        )

        if current_agent not in loop_consumption_map:
            return None

        consumption_config = loop_consumption_map[current_agent]
        loop_sources = consumption_config['loop_agents']
        pattern = consumption_config['pattern']

        def correlation_setup_directories(agent_folder, agent_config, previous_agent_type, agent_idx):
            """Wrapper that uses correlated input for loop consumers."""
            correlated_dir = self.loop_correlator.prepare_correlated_input(
                current_agent,
                loop_sources,
                agent_idx
            )

            if correlated_dir:
                self.console.print(
                    f'[blue]🔗 Using correlated input for {current_agent} from '
                    f'{len(loop_sources)} loop sources (pattern: {pattern})[/blue]'
                )
                input_directory = correlated_dir
            else:
                self.console.print(
                    f'[yellow]⚠️ Failed to correlate loop outputs for {current_agent}, '
                    f'falling back to standard input[/yellow]'
                )
                input_dir, output_dir = original_setup_directories(
                    agent_folder,
                    agent_config,
                    previous_agent_type,
                    agent_idx
                )
                input_directory = input_dir

            # Setup output directory
            indexed_agent_type = f"node_{agent_idx}_{agent_config['agent_type']}"
            output_directory = Path(agent_folder) / 'target' / indexed_agent_type
            output_directory.mkdir(parents=True, exist_ok=True)

            return (str(input_directory), str(output_directory))

        return correlation_setup_directories
