"""
Loop output correlation system for parallel map-reduce patterns.

Handles correlation of loop iteration outputs for downstream agents
without breaking existing sequential execution.
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict

from agent_actions.errors import DataValidationError

logger = logging.getLogger(__name__)


@dataclass
class JsonLoadParams:
    """Parameters for loading JSON from file."""
    json_file: Path
    outputs: List
    corrupted_files: List
    output_dir: Path
    operation: str
    add_source_file: bool = False

class LoopOutputCorrelator:
    """Correlates outputs from parallel loop executions for downstream consumption."""

    def __init__(self, agent_folder: Path):
        self.agent_folder = agent_folder
        self.correlations_cache = {}

    def detect_explicit_loop_consumption(
        self, execution_order: List[str], agent_configs: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Detect agents with explicit loop consumption configurations.

        Returns:
            Dict mapping agent_name -> {
                'source_base_name': str,
                'pattern': str,
                'loop_agents': List[str]
            }
        """
        loop_consumption_map = {}
        loop_groups = {}
        for agent_name in execution_order:
            if '_' in agent_name and agent_name.count('_') >= 1:
                parts = agent_name.rsplit('_', 1)
                if len(parts) == 2:
                    base_name, suffix = parts
                    if suffix.isdigit():
                        if base_name not in loop_groups:
                            loop_groups[base_name] = []
                        loop_groups[base_name].append(agent_name)
        for agent_name in execution_order:
            agent_config = agent_configs.get(agent_name, {})
            loop_consumption_config = agent_config.get('loop_consumption_config')
            if loop_consumption_config:
                source_base_name = loop_consumption_config.get('source')
                pattern = loop_consumption_config.get('pattern', 'merge')
                loop_agents = loop_groups.get(source_base_name, [])
                if loop_agents:
                    loop_consumption_map[agent_name] = {
                        'source_base_name': source_base_name,
                        'pattern': pattern,
                        'loop_agents': loop_agents
                    }
                else:
                    logger.warning(
                        "Agent '%s' consumes loop '%s' but no loop agents found",
                        agent_name,
                        source_base_name
                    )
        return loop_consumption_map

    def _load_loop_outputs(
        self, loop_sources: List[str]
    ) -> tuple[Dict[str, List[Dict[str, Any]]], set]:
        """Load outputs from all loop sources."""
        loop_outputs = {}
        loop_filenames = set()
        for loop_agent in loop_sources:
            loop_idx = self._find_agent_index(loop_agent)
            if loop_idx is None:
                continue
            loop_output_dir = (
                self.agent_folder / 'target' /
                f'node_{loop_idx}_{loop_agent}'
            )
            if loop_output_dir.exists():
                outputs, filenames = (
                    self._load_agent_outputs_with_filenames(
                        loop_output_dir
                    )
                )
                loop_outputs[loop_agent] = outputs
                loop_filenames.update(filenames)
        return loop_outputs, loop_filenames

    def _process_loop_files(
        self,
        loop_outputs: Dict[str, List[Dict[str, Any]]],
        loop_filenames: set,
        correlation_dir: Path
    ):
        """Process and correlate outputs by file."""
        for filename in loop_filenames:
            file_loop_outputs = {}
            for loop_agent, outputs in loop_outputs.items():
                file_outputs = [
                    o for o in outputs
                    if o.get('_source_file') == filename
                ]
                if file_outputs:
                    file_loop_outputs[loop_agent] = file_outputs
            if file_loop_outputs:
                correlated_data = self._correlate_by_source_record(
                    file_loop_outputs
                )
                self._write_correlated_data(
                    correlation_dir, correlated_data, filename
                )

    def prepare_correlated_input(
        self, agent_name: str, loop_sources: List[str], current_idx: int
    ) -> Optional[str]:
        """
        Prepare correlated input directory for an agent that depends on loop outputs.

        Args:
            agent_name: Name of the agent that needs correlated input
            loop_sources: List of loop agent names this agent depends on
            current_idx: Current execution index
            pattern: Merge pattern to use (only 'merge' supported)

        Returns:
            Path to correlated input directory, or None if correlation failed
        """
        try:
            correlation_dir = (
                self.agent_folder / 'target' /
                f'node_{current_idx}_{agent_name}'
            )
            correlation_dir.mkdir(parents=True, exist_ok=True)

            loop_outputs, loop_filenames = self._load_loop_outputs(loop_sources)
            if not loop_outputs:
                return None

            self._process_loop_files(loop_outputs, loop_filenames, correlation_dir)
            return str(correlation_dir)
        except (OSError, IOError, ValueError, KeyError) as e:
            logger.exception(
                'Error preparing correlated input for %s: %s',
                agent_name,
                e
            )
            return None

    def _find_agent_index(self, agent_name: str) -> Optional[int]:
        """Find the execution index of an agent by scanning target directories."""
        target_dir = self.agent_folder / 'target'
        if not target_dir.exists():
            return None
        for subdir in target_dir.iterdir():
            if subdir.is_dir() and subdir.name.endswith(f'_{agent_name}'):
                parts = subdir.name.split('_')
                if len(parts) >= 2 and parts[0] == 'node' and parts[1].isdigit():
                    return int(parts[1])
        return None

    def _load_json_from_file(self, params: JsonLoadParams):
        """Load JSON from a file and handle errors."""
        try:
            with open(params.json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if params.add_source_file:
                    if isinstance(data, list):
                        for record in data:
                            record['_source_file'] = params.json_file.name
                        params.outputs.extend(data)
                    else:
                        data['_source_file'] = params.json_file.name
                        params.outputs.append(data)
                elif isinstance(data, list):
                    params.outputs.extend(data)
                else:
                    params.outputs.append(data)
        except json.JSONDecodeError as e:
            logger.warning(
                "Skipping corrupted JSON file in loop output",
                extra={
                    'operation': params.operation,
                    'file': str(params.json_file),
                    'output_dir': str(params.output_dir),
                    'error': str(e),
                    'line': e.lineno if hasattr(e, 'lineno') else None
                }
            )
            params.corrupted_files.append(str(params.json_file.name))
        except (OSError, IOError) as e:
            logger.error(
                "Failed to read loop output file",
                extra={
                    'operation': params.operation,
                    'file': str(params.json_file),
                    'output_dir': str(params.output_dir),
                    'error': str(e)
                }
            )
            params.corrupted_files.append(str(params.json_file.name))
        except (ValueError, TypeError, UnicodeDecodeError) as e:
            logger.exception(
                "Unexpected error loading loop output file",
                extra={
                    'operation': params.operation,
                    'file': str(params.json_file),
                    'output_dir': str(params.output_dir),
                    'error': str(e),
                    'error_type': type(e).__name__
                }
            )
            params.corrupted_files.append(str(params.json_file.name))

    def _load_agent_outputs(
        self, output_dir: Path
    ) -> List[Dict[str, Any]]:
        """Load all JSON outputs from an agent's output directory."""
        outputs = []
        corrupted_files = []

        for json_file in output_dir.glob('*.json'):
            self._load_json_from_file(
                JsonLoadParams(
                    json_file=json_file,
                    outputs=outputs,
                    corrupted_files=corrupted_files,
                    output_dir=output_dir,
                    operation='load_loop_outputs',
                    add_source_file=False
                )
            )

        if corrupted_files:
            logger.warning(
                "Skipped %d corrupted files in loop output",
                len(corrupted_files),
                extra={
                    'operation': 'load_loop_outputs',
                    'output_dir': str(output_dir),
                    'corrupted_count': len(corrupted_files),
                    'corrupted_files': corrupted_files,
                    'loaded_count': len(outputs)
                }
            )

        return outputs

    def _load_agent_outputs_with_filenames(
        self, output_dir: Path
    ) -> Tuple[List[Dict[str, Any]], set]:
        """Load all JSON outputs with filenames."""
        outputs = []
        filenames = set()
        corrupted_files = []

        for json_file in output_dir.glob('*.json'):
            before_count = len(outputs)
            self._load_json_from_file(
                JsonLoadParams(
                    json_file=json_file,
                    outputs=outputs,
                    corrupted_files=corrupted_files,
                    output_dir=output_dir,
                    operation='load_loop_outputs_with_filenames',
                    add_source_file=True
                )
            )
            # If file was successfully loaded, add to filenames
            if len(outputs) > before_count:
                filenames.add(json_file.name)

        if corrupted_files:
            logger.warning(
                "Skipped %d corrupted files in loop output",
                len(corrupted_files),
                extra={
                    'operation': 'load_loop_outputs_with_filenames',
                    'output_dir': str(output_dir),
                    'corrupted_count': len(corrupted_files),
                    'corrupted_files': corrupted_files,
                    'loaded_count': len(outputs)
                }
            )

        return (outputs, filenames)

    def _build_correlation_groups(
        self, loop_outputs: Dict[str, List[Dict[str, Any]]]
    ) -> defaultdict:
        """Build correlation groups from loop outputs."""
        correlation_groups = defaultdict(dict)
        for loop_agent, outputs in loop_outputs.items():
            for record in outputs:
                # Use dict comprehension instead of copy()+pop() for efficiency
                record_copy = {k: v for k, v in record.items() if k != '_source_file'}
                correlation_key = record_copy.get('loop_correlation_id')
                if not correlation_key:
                    source_guid = record_copy.get('source_guid', 'unknown')
                    raise DataValidationError(
                        'Missing required field: loop_correlation_id',
                        {
                            'source_guid': source_guid,
                            'loop_agent': loop_agent,
                            'operation': 'correlate_loop_outputs'
                        }
                    )
                correlation_groups[correlation_key][loop_agent] = record_copy
        return correlation_groups

    def _create_merged_record(
        self,
        agent_records: Dict[str, Dict[str, Any]],
        loop_outputs: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, Any]:
        """Create a merged record from agent records."""
        base_record = next(iter(agent_records.values()))
        merged_record = {
            'source_guid': base_record['source_guid'],
            'target_id': base_record.get('target_id'),
            'node_id': base_record.get('node_id'),
            'lineage': base_record.get('lineage'),
            'loop_correlation_id': base_record.get('loop_correlation_id'),
            'content': self._merge_with_pattern(agent_records),
            '_correlation_sources': list(agent_records.keys())
        }
        # Check for missing iterations
        all_expected_loops = set(loop_outputs.keys())
        present_loops = set(agent_records.keys())
        missing_loops = all_expected_loops - present_loops
        if missing_loops:
            merged_record['_missing_iterations'] = list(missing_loops)
        return merged_record

    def _correlate_by_source_record(
        self, loop_outputs: Dict[str, List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """
        Correlate loop outputs by source record ID using merge pattern.

        Handles the agent-actions data structure where actual content is nested
        in a 'content' field and correlation is done by 'source_guid'.

        Args:
            loop_outputs: Dict mapping loop agent names to their outputs
        """
        correlation_groups = self._build_correlation_groups(loop_outputs)
        correlated_records = []
        for agent_records in correlation_groups.values():
            if agent_records:
                merged_record = self._create_merged_record(
                    agent_records, loop_outputs
                )
                correlated_records.append(merged_record)
        return correlated_records

    def _merge_with_pattern(
        self, agent_records: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Merge content from multiple loop agent records using merge pattern.

        Args:
            agent_records: Dict mapping loop agent names to their records

        Returns:
            Merged content dictionary
        """
        merged_content = {}
        for record in agent_records.values():
            content = record.get('content', {})
            merged_content.update(content)
        return merged_content

    def _extract_correlation_key(
        self, record: Dict[str, Any]
    ) -> Optional[str]:
        """
        Extract a correlation key from a record to match it across loop iterations.

        Tries multiple strategies to find a suitable correlation key.
        """
        if 'id' in record:
            return str(record['id'])
        if 'source_guid' in record:
            return str(record['source_guid'])
        key_fields = ['url', 'question', 'fact', 'content']
        available_fields = [field for field in key_fields if field in record]
        if available_fields:
            key_parts = [str(record[field]) for field in available_fields[:2]]
            return '|'.join(key_parts)
        stable_fields = {
            k: v for k, v in record.items()
            if not any((k.endswith(f'_{i}') for i in range(1, 10)))
        }
        if stable_fields:
            # sort_keys=True for consistent hashing, compact separators for speed
            content_str = json.dumps(stable_fields, sort_keys=True, separators=(',', ':'))
            return str(hash(content_str))
        return None

    def _write_correlated_data(
        self,
        output_dir: Path,
        correlated_data: List[Dict[str, Any]],
        filename: str = 'correlated_data.json'
    ):
        """Write correlated data to the output directory and create corresponding source data."""
        if not correlated_data:
            return
        # Use dict comprehension instead of copy()+pop() for efficiency
        keys_to_remove = {'_correlation_sources', '_missing_iterations'}
        cleaned_data = [
            {k: v for k, v in record.items() if k not in keys_to_remove}
            for record in correlated_data
        ]
        output_file = output_dir / filename
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(cleaned_data, f, indent=2)
        self._create_correlation_source_data(output_file, cleaned_data)

    def _create_correlation_source_data(
        self, target_file: Path, correlated_data: List[Dict[str, Any]]
    ):
        """Create source data file that corresponds to the correlation target file."""
        try:
            parts = target_file.parts
            agent_io_index = None
            for i, part in enumerate(parts):
                if part == 'agent_io':
                    agent_io_index = i
                    break
            filename = target_file.name
            if agent_io_index is not None:
                pipeline_parts = parts[:agent_io_index]
                source_path = Path(*pipeline_parts) / 'agent_io' / 'source' / filename
            else:
                source_path = self.agent_folder / 'source' / filename
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_records = []
            for record in correlated_data:
                source_record = {
                    'source_guid': record.get('source_guid'),
                    'id': record.get('target_id', record.get('source_guid'))
                }
                source_records.append(source_record)
            with open(source_path, 'w', encoding='utf-8') as f:
                json.dump(source_records, f, indent=2)
        except (OSError, IOError, ValueError) as e:
            logger.warning(
                'Could not create correlation source data: %s', e
            )


__all__ = ['LoopOutputCorrelator']
