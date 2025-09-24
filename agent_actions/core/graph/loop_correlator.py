"""
Loop output correlation system for parallel map-reduce patterns.

Handles correlation of loop iteration outputs for downstream agents
without breaking existing sequential execution.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict


class LoopOutputCorrelator:
    """Correlates outputs from parallel loop executions for downstream consumption."""

    def __init__(self, agent_folder: Path):
        self.agent_folder = agent_folder
        self.correlations_cache = {}

    def detect_loop_dependencies(self, execution_order: List[str], agent_configs: Dict[str, Any]) -> Dict[str, List[str]]:
        """
        Detect which agents depend on loop outputs.

        Returns:
            Dict mapping agent_name -> list of loop agents it depends on
        """
        loop_dependencies = {}

        # First, identify which agents are part of loops
        loop_agents = set()
        loop_groups = {}  # base_name -> [agent_1, agent_2, agent_3]

        for agent_name in execution_order:
            if '_' in agent_name and agent_name.count('_') >= 1:
                # Check if this looks like a loop agent (e.g., generate_distractors_1)
                parts = agent_name.rsplit('_', 1)
                if len(parts) == 2:
                    base_name, suffix = parts
                    if suffix.isdigit():
                        loop_agents.add(agent_name)
                        if base_name not in loop_groups:
                            loop_groups[base_name] = []
                        loop_groups[base_name].append(agent_name)

        # Now check dependencies
        for agent_name in execution_order:
            if agent_name in loop_agents:
                continue  # Skip loop agents themselves

            agent_config = agent_configs.get(agent_name, {})
            dependencies = agent_config.get('dependencies', [])

            loop_deps = []
            for dep in dependencies:
                # Check if dependency is a loop base name
                if dep in loop_groups:
                    loop_deps.extend(loop_groups[dep])
                elif dep in loop_agents:
                    loop_deps.append(dep)

            if loop_deps:
                loop_dependencies[agent_name] = loop_deps

        return loop_dependencies

    def prepare_correlated_input(self, agent_name: str, loop_sources: List[str],
                                 current_idx: int) -> Optional[str]:
        """
        Prepare correlated input directory for an agent that depends on loop outputs.

        Args:
            agent_name: Name of the agent that needs correlated input
            loop_sources: List of loop agent names this agent depends on
            current_idx: Current execution index

        Returns:
            Path to correlated input directory, or None if correlation failed
        """
        try:
            # Create correlation directory in target (same as other agents)
            correlation_dir = self.agent_folder / "target" / f"node_{current_idx}_{agent_name}"
            correlation_dir.mkdir(parents=True, exist_ok=True)

            # Collect outputs from all loop sources with their filenames
            loop_outputs = {}
            loop_filenames = set()
            for loop_agent in loop_sources:
                # Find the output directory for this loop agent
                loop_idx = self._find_agent_index(loop_agent)
                if loop_idx is None:
                    continue

                loop_output_dir = self.agent_folder / "target" / f"node_{loop_idx}_{loop_agent}"
                if loop_output_dir.exists():
                    outputs, filenames = self._load_agent_outputs_with_filenames(loop_output_dir)
                    loop_outputs[loop_agent] = outputs
                    loop_filenames.update(filenames)

            if not loop_outputs:
                return None

            # Process each unique filename separately
            for filename in loop_filenames:
                # Collect outputs for this specific file from all loop agents
                file_loop_outputs = {}
                for loop_agent, outputs in loop_outputs.items():
                    file_outputs = [o for o in outputs if o.get('_source_file') == filename]
                    if file_outputs:
                        file_loop_outputs[loop_agent] = file_outputs

                if file_loop_outputs:
                    # Correlate outputs by source record
                    correlated_data = self._correlate_by_source_record(file_loop_outputs)

                    # Write correlated data with original filename
                    self._write_correlated_data(correlation_dir, correlated_data, filename)

            return str(correlation_dir)

        except Exception as e:
            print(f"Error preparing correlated input for {agent_name}: {e}")
            return None

    def _find_agent_index(self, agent_name: str) -> Optional[int]:
        """Find the execution index of an agent by scanning target directories."""
        target_dir = self.agent_folder / "target"
        if not target_dir.exists():
            return None

        for subdir in target_dir.iterdir():
            if subdir.is_dir() and subdir.name.endswith(f"_{agent_name}"):
                # Extract index from directory name (e.g., "node_5_generate_distractors_1" -> 5)
                parts = subdir.name.split('_')
                if len(parts) >= 2 and parts[0] == "node" and parts[1].isdigit():
                    return int(parts[1])
        return None

    def _load_agent_outputs(self, output_dir: Path) -> List[Dict[str, Any]]:
        """Load all JSON outputs from an agent's output directory."""
        outputs = []
        for json_file in output_dir.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        outputs.extend(data)
                    else:
                        outputs.append(data)
            except Exception:
                continue
        return outputs

    def _load_agent_outputs_with_filenames(self, output_dir: Path) -> Tuple[List[Dict[str, Any]], set]:
        """Load all JSON outputs from an agent's output directory with their filenames."""
        outputs = []
        filenames = set()
        for json_file in output_dir.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    # Tag each record with its source filename
                    if isinstance(data, list):
                        for record in data:
                            record['_source_file'] = json_file.name
                        outputs.extend(data)
                    else:
                        data['_source_file'] = json_file.name
                        outputs.append(data)
                    filenames.add(json_file.name)
            except Exception:
                continue
        return outputs, filenames

    def _correlate_by_source_record(self, loop_outputs: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Correlate loop outputs by source record ID.

        Handles the agent-actions data structure where actual content is nested
        in a 'content' field and correlation is done by 'source_guid'.
        """
        # Group records by source_guid
        correlation_groups = defaultdict(dict)

        for loop_agent, outputs in loop_outputs.items():
            for record in outputs:
                # Remove temporary filename marker before processing
                record_copy = record.copy()
                record_copy.pop('_source_file', None)

                # Use source_guid as correlation key
                correlation_key = record_copy.get('source_guid')
                if correlation_key:
                    correlation_groups[correlation_key][loop_agent] = record_copy

        # Merge correlated records
        correlated_records = []
        for correlation_key, agent_records in correlation_groups.items():
            # Include records even if they don't exist in all loop iterations
            # This handles partial failures gracefully
            if agent_records:  # Changed from checking len == len(loop_outputs)
                # Start with the first record as base structure
                base_record = next(iter(agent_records.values()))
                merged_record = {
                    'source_guid': base_record['source_guid'],
                    'target_id': base_record.get('target_id'),
                    'node_id': base_record.get('node_id'),
                    'lineage': base_record.get('lineage'),
                    'content': {},
                    '_correlation_sources': list(agent_records.keys())  # Track which loops contributed
                }

                # Merge all content fields from all loop iterations
                for loop_agent, record in agent_records.items():
                    content = record.get('content', {})
                    # Optionally prefix fields if there's a conflict risk
                    merged_record['content'].update(content)

                # Add metadata about missing loop iterations if any
                all_expected_loops = set(loop_outputs.keys())
                present_loops = set(agent_records.keys())
                missing_loops = all_expected_loops - present_loops
                if missing_loops:
                    merged_record['_missing_iterations'] = list(missing_loops)

                correlated_records.append(merged_record)

        return correlated_records

    def _extract_correlation_key(self, record: Dict[str, Any]) -> Optional[str]:
        """
        Extract a correlation key from a record to match it across loop iterations.

        Tries multiple strategies to find a suitable correlation key.
        """
        # Strategy 1: Use explicit ID field
        if 'id' in record:
            return str(record['id'])

        # Strategy 2: Use combination of fields that should be unique
        key_fields = ['url', 'question', 'fact', 'content']
        available_fields = [field for field in key_fields if field in record]
        if available_fields:
            key_parts = [str(record[field]) for field in available_fields[:2]]  # Use first 2 available
            return '|'.join(key_parts)

        # Strategy 3: Use hash of stable content
        stable_fields = {k: v for k, v in record.items()
                        if not any(k.endswith(f"_{i}") for i in range(1, 10))}  # Exclude loop-specific fields
        if stable_fields:
            content_str = json.dumps(stable_fields, sort_keys=True)
            return str(hash(content_str))

        return None

    def _write_correlated_data(self, output_dir: Path, correlated_data: List[Dict[str, Any]],
                              filename: str = "correlated_data.json"):
        """Write correlated data to the output directory and create corresponding source data."""
        if not correlated_data:
            return

        # Clean up metadata fields before writing
        cleaned_data = []
        for record in correlated_data:
            clean_record = record.copy()
            # Remove internal tracking fields from the output
            clean_record.pop('_correlation_sources', None)
            clean_record.pop('_missing_iterations', None)
            cleaned_data.append(clean_record)

        # Write with the original filename
        output_file = output_dir / filename
        with open(output_file, 'w') as f:
            json.dump(cleaned_data, f, indent=2)

        # Create corresponding source data for source_data_loader
        self._create_correlation_source_data(output_file, cleaned_data)

    def _create_correlation_source_data(self, target_file: Path, correlated_data: List[Dict[str, Any]]):
        """Create source data file that corresponds to the correlation target file."""
        try:
            # Derive source path from target path
            # Look for "agent_io" in path, or use agent_folder directly
            parts = target_file.parts
            agent_io_index = None
            for i, part in enumerate(parts):
                if part == "agent_io":
                    agent_io_index = i
                    break

            filename = target_file.name

            if agent_io_index is not None:
                # Standard agent_io structure
                pipeline_parts = parts[:agent_io_index]
                source_path = Path(*pipeline_parts) / "agent_io" / "source" / filename
            else:
                # Use agent_folder structure (for tests and non-standard layouts)
                # Navigate from target/node_X_agent/file.json to source/file.json
                source_path = self.agent_folder / "source" / filename

            # Create source directory if it doesn't exist
            source_path.parent.mkdir(parents=True, exist_ok=True)

            # Extract source records from correlation data
            source_records = []
            for record in correlated_data:
                source_record = {
                    'source_guid': record.get('source_guid'),
                    'id': record.get('target_id', record.get('source_guid')),
                    # Add other fields that might be needed for source data
                }
                source_records.append(source_record)

            # Write source data
            with open(source_path, 'w') as f:
                json.dump(source_records, f, indent=2)

        except Exception as e:
            print(f"Warning: Could not create correlation source data: {e}")

    def should_use_correlation(self, agent_name: str, agent_configs: Dict[str, Any]) -> bool:
        """
        Check if an agent should use correlation instead of normal input.
        """
        agent_config = agent_configs.get(agent_name, {})
        dependencies = agent_config.get('dependencies', [])

        # Check if any dependency looks like a loop agent
        for dep in dependencies:
            if '_' in dep and dep.rsplit('_', 1)[1].isdigit():
                return True

        return False


__all__ = ["LoopOutputCorrelator"]