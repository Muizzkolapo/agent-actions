"""Version output correlation for parallel map-reduce patterns."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_actions.errors import DataValidationError
from agent_actions.input.preprocessing.staging.initial_pipeline import _should_save_source_items
from agent_actions.record.envelope import RecordEnvelope
from agent_actions.utils.atomic_write import atomic_json_write

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


@dataclass
class JsonLoadParams:
    """Parameters for loading JSON from file."""

    json_file: Path
    outputs: list
    corrupted_files: list
    output_dir: Path
    operation: str
    add_source_file: bool = False


class VersionOutputCorrelator:
    """Correlates outputs from parallel version executions for downstream consumption."""

    def __init__(
        self,
        agent_folder: Path,
        storage_backend: StorageBackend | None = None,
    ):
        self.agent_folder = agent_folder
        self.storage_backend = storage_backend
        self.correlations_cache: dict[str, Any] = {}

    def detect_explicit_version_consumption(
        self, execution_order: list[str], agent_configs: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Return map of agent names to their version consumption configurations."""
        version_consumption_map = {}
        version_groups: dict[str, list[str]] = {}
        for agent_name in execution_order:
            if "_" in agent_name and agent_name.count("_") >= 1:
                parts = agent_name.rsplit("_", 1)
                if len(parts) == 2:
                    base_name, suffix = parts
                    if suffix.isdigit():
                        if base_name not in version_groups:
                            version_groups[base_name] = []
                        version_groups[base_name].append(agent_name)
        for agent_name in execution_order:
            agent_config = agent_configs.get(agent_name, {})
            version_consumption_config = agent_config.get("version_consumption_config")
            if version_consumption_config:
                source_base_name = version_consumption_config.get("source")
                pattern = version_consumption_config.get("pattern", "merge")
                version_agents = version_groups.get(source_base_name, [])
                if version_agents:
                    version_consumption_map[agent_name] = {
                        "source_base_name": source_base_name,
                        "pattern": pattern,
                        "version_agents": version_agents,
                    }
                else:
                    logger.warning(
                        "Agent '%s' consumes version '%s' but no version agents found",
                        agent_name,
                        source_base_name,
                    )
        return version_consumption_map

    def _load_version_outputs(
        self, version_sources: list[str]
    ) -> tuple[dict[str, list[dict[str, Any]]], set]:
        """Load outputs from all version sources, preferring storage backend over filesystem."""
        version_outputs = {}
        version_filenames = set()

        for version_agent in version_sources:
            if self.storage_backend is not None:
                outputs, filenames = self._load_from_storage_backend(version_agent)
                if outputs:
                    version_outputs[version_agent] = outputs
                    version_filenames.update(filenames)
                    continue

            version_idx = self._find_agent_index(version_agent)
            if version_idx is None:
                continue
            version_output_dir = self.agent_folder / "target" / version_agent
            if version_output_dir.exists():
                outputs, filenames = self._load_agent_outputs_with_filenames(version_output_dir)
                version_outputs[version_agent] = outputs
                version_filenames.update(filenames)

        return version_outputs, version_filenames

    def _load_from_storage_backend(self, version_agent: str) -> tuple[list[dict[str, Any]], set]:
        """Load outputs from storage backend for a version agent."""
        if self.storage_backend is None:
            return [], set()

        outputs = []
        filenames = set()

        try:
            target_files = self.storage_backend.list_target_files(version_agent)
            if not target_files:
                logger.debug(
                    "No target files found in storage backend for %s",
                    version_agent,
                )
                return [], set()

            for relative_path in target_files:
                try:
                    data = self.storage_backend.read_target(version_agent, relative_path)
                    if isinstance(data, list):
                        for record in data:
                            record["_source_file"] = relative_path
                        outputs.extend(data)
                    else:
                        data["_source_file"] = relative_path  # type: ignore[unreachable]
                        outputs.append(data)
                    filenames.add(relative_path)
                except Exception as e:
                    logger.warning(
                        "Failed to read target %s/%s from storage backend: %s",
                        version_agent,
                        relative_path,
                        e,
                        exc_info=True,
                    )

            logger.debug(
                "Loaded %d records from storage backend for %s (files: %s)",
                len(outputs),
                version_agent,
                list(filenames),
            )
            return outputs, filenames

        except Exception as e:
            logger.warning(
                "Failed to list target files from storage backend for %s: %s",
                version_agent,
                e,
                exc_info=True,
            )
            return [], set()

    def _process_version_files(
        self,
        version_outputs: dict[str, list[dict[str, Any]]],
        version_filenames: set,
        correlation_dir: Path,
        action_name: str,
    ):
        """Process and correlate outputs by file."""
        for filename in version_filenames:
            file_version_outputs = {}
            for version_agent, outputs in version_outputs.items():
                file_outputs = [o for o in outputs if o.get("_source_file") == filename]
                if file_outputs:
                    file_version_outputs[version_agent] = file_outputs
            if file_version_outputs:
                correlated_data = self._correlate_by_source_record(file_version_outputs)
                self._write_correlated_data(
                    correlation_dir, correlated_data, filename, action_name=action_name
                )

    def prepare_correlated_input(
        self, agent_name: str, version_sources: list[str], _current_idx: int
    ) -> str | None:
        """Return path to correlated input directory, or None if correlation failed."""
        try:
            correlation_dir = self.agent_folder / "target" / agent_name
            if self.storage_backend is None:
                correlation_dir.mkdir(parents=True, exist_ok=True)

            version_outputs, version_filenames = self._load_version_outputs(version_sources)
            if not version_outputs:
                return None

            self._process_version_files(
                version_outputs, version_filenames, correlation_dir, action_name=agent_name
            )
            return str(correlation_dir)
        except (OSError, ValueError, KeyError) as e:
            logger.exception("Error preparing correlated input for %s: %s", agent_name, e)
            return None

    def _find_agent_index(self, agent_name: str) -> int | None:
        """Return 0 if the agent has data in storage or filesystem, None otherwise."""
        if self.storage_backend is not None:
            try:
                target_files = self.storage_backend.list_target_files(agent_name)
                if target_files:
                    return 0
            except Exception as e:
                logger.debug("Failed to list target files for %s: %s", agent_name, e, exc_info=True)

        target_dir = self.agent_folder / "target"
        if not target_dir.exists():
            return None
        agent_dir = target_dir / agent_name
        if agent_dir.exists() and agent_dir.is_dir():
            return 0
        return None

    def _load_json_from_file(self, params: JsonLoadParams):
        """Load JSON from a file and handle errors."""
        try:
            with open(params.json_file, encoding="utf-8") as f:
                data = json.load(f)
                if params.add_source_file:
                    if isinstance(data, list):
                        for record in data:
                            record["_source_file"] = params.json_file.name
                        params.outputs.extend(data)
                    else:
                        data["_source_file"] = params.json_file.name
                        params.outputs.append(data)
                elif isinstance(data, list):
                    params.outputs.extend(data)
                else:
                    params.outputs.append(data)
        except json.JSONDecodeError as e:
            logger.warning(
                "Skipping corrupted JSON file in version output",
                extra={
                    "operation": params.operation,
                    "file": str(params.json_file),
                    "output_dir": str(params.output_dir),
                    "error": str(e),
                    "line": e.lineno if hasattr(e, "lineno") else None,
                },
            )
            params.corrupted_files.append(str(params.json_file.name))
        except OSError as e:
            logger.error(
                "Failed to read version output file",
                extra={
                    "operation": params.operation,
                    "file": str(params.json_file),
                    "output_dir": str(params.output_dir),
                    "error": str(e),
                },
            )
            params.corrupted_files.append(str(params.json_file.name))
        except (ValueError, TypeError, UnicodeDecodeError) as e:
            logger.exception(
                "Unexpected error loading version output file",
                extra={
                    "operation": params.operation,
                    "file": str(params.json_file),
                    "output_dir": str(params.output_dir),
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            params.corrupted_files.append(str(params.json_file.name))

    def _load_agent_outputs_with_filenames(
        self, output_dir: Path
    ) -> tuple[list[dict[str, Any]], set]:
        """Load all JSON outputs with filenames."""
        outputs: list[dict[str, Any]] = []
        filenames = set()
        corrupted_files: list[str] = []

        for json_file in output_dir.glob("*.json"):
            before_count = len(outputs)
            self._load_json_from_file(
                JsonLoadParams(
                    json_file=json_file,
                    outputs=outputs,
                    corrupted_files=corrupted_files,
                    output_dir=output_dir,
                    operation="load_version_outputs_with_filenames",
                    add_source_file=True,
                )
            )
            if len(outputs) > before_count:
                filenames.add(json_file.name)

        if corrupted_files:
            logger.warning(
                "Skipped %d corrupted files in version output",
                len(corrupted_files),
                extra={
                    "operation": "load_loop_outputs_with_filenames",
                    "output_dir": str(output_dir),
                    "corrupted_count": len(corrupted_files),
                    "corrupted_files": corrupted_files,
                    "loaded_count": len(outputs),
                },
            )

        return (outputs, filenames)

    def _build_correlation_groups(
        self, version_outputs: dict[str, list[dict[str, Any]]]
    ) -> defaultdict:
        """Build correlation groups from version outputs."""
        correlation_groups: defaultdict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for version_agent, outputs in version_outputs.items():
            for record in outputs:
                record_copy = {k: v for k, v in record.items() if k != "_source_file"}
                correlation_key = record_copy.get("version_correlation_id")
                if not correlation_key:
                    source_guid = record_copy.get("source_guid", "unknown")
                    raise DataValidationError(
                        "Missing required field: version_correlation_id",
                        {
                            "source_guid": source_guid,
                            "version_agent": version_agent,
                            "operation": "correlate_version_outputs",
                        },
                    )
                correlation_groups[correlation_key][version_agent] = record_copy
        return correlation_groups

    def _create_merged_record(
        self,
        agent_records: dict[str, dict[str, Any]],
        version_outputs: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Create a merged record from agent records."""
        base_record = next(iter(agent_records.values()))

        merged_lineage = []
        seen_lineage_entries: set = set()
        for record in agent_records.values():
            record_lineage = record.get("lineage", [])
            if isinstance(record_lineage, list):
                for entry in record_lineage:
                    entry_key = entry if isinstance(entry, str) else entry.get("node_id")
                    if entry_key and entry_key not in seen_lineage_entries:
                        merged_lineage.append(entry)
                        seen_lineage_entries.add(entry_key)

        source_guid = base_record.get("source_guid")
        if source_guid is None:
            logger.warning(
                "Missing 'source_guid' in base record during version output correlation; "
                "merged record will have source_guid=None"
            )
        version_namespaces = self._merge_with_pattern(agent_records)
        merged = RecordEnvelope.build_version_merge(version_namespaces, base_record)
        merged_record = {
            "source_guid": source_guid,
            "target_id": base_record.get("target_id"),
            "node_id": base_record.get("node_id"),
            "lineage": merged_lineage,
            "version_correlation_id": base_record.get("version_correlation_id"),
            "content": merged["content"],
            "_correlation_sources": list(agent_records.keys()),
        }
        all_expected_versions = set(version_outputs.keys())
        present_versions = set(agent_records.keys())
        missing_versions = all_expected_versions - present_versions
        if missing_versions:
            merged_record["_missing_iterations"] = list(missing_versions)
        return merged_record

    def _correlate_by_source_record(
        self, version_outputs: dict[str, list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        """Correlate version outputs by source record ID using merge pattern."""
        correlation_groups = self._build_correlation_groups(version_outputs)
        correlated_records = []
        for agent_records in correlation_groups.values():
            if agent_records:
                merged_record = self._create_merged_record(agent_records, version_outputs)
                correlated_records.append(merged_record)
        return correlated_records

    def _merge_with_pattern(self, agent_records: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Merge content into nested namespaces keyed by version agent name."""
        from agent_actions.prompt.context.scope_namespace import _extract_content_data

        merged_content = {}
        for agent_name, record in agent_records.items():
            content = _extract_content_data(record)
            merged_content[agent_name] = content
        return merged_content

    def _write_correlated_data(
        self,
        output_dir: Path,
        correlated_data: list[dict[str, Any]],
        filename: str = "correlated_data.json",
        action_name: str | None = None,
    ):
        """Write correlated data to storage backend or filesystem."""
        if not correlated_data:
            return
        keys_to_remove = {"_correlation_sources", "_missing_iterations"}
        cleaned_data = [
            {k: v for k, v in record.items() if k not in keys_to_remove}
            for record in correlated_data
        ]

        if self.storage_backend is not None and action_name:
            try:
                self.storage_backend.write_target(action_name, filename, cleaned_data)
                logger.debug(
                    "Wrote %d correlated records to storage backend for %s/%s",
                    len(cleaned_data),
                    action_name,
                    filename,
                )
            except Exception as e:
                logger.warning(
                    "Failed to write correlated data to storage backend for %s: %s",
                    action_name,
                    e,
                )
        else:
            output_file = output_dir / filename
            atomic_json_write(output_file, cleaned_data, indent=2)
            self._create_correlation_source_data(output_file, cleaned_data)

    def _create_correlation_source_data(
        self, target_file: Path, correlated_data: list[dict[str, Any]]
    ):
        """Create source data file for the correlation target, skipping if existing source is richer."""
        try:
            parts = target_file.parts
            agent_io_index = None
            for i, part in enumerate(parts):
                if part == "agent_io":
                    agent_io_index = i
                    break
            filename = target_file.name
            if agent_io_index is not None:
                pipeline_parts = parts[:agent_io_index]
                source_path = Path(*pipeline_parts) / "agent_io" / "source" / filename
            else:
                source_path = self.agent_folder / "source" / filename
            source_path.parent.mkdir(parents=True, exist_ok=True)
            source_records = []
            for record in correlated_data:
                source_record = {
                    "source_guid": record.get("source_guid"),
                    "id": record.get("target_id", record.get("source_guid")),
                    "lineage": record.get("lineage", []),
                    "node_id": record.get("node_id"),
                }
                source_records.append(source_record)

            base_directory = str(target_file.parent)

            if not _should_save_source_items(
                source_records, str(target_file), base_directory, None
            ):
                logger.debug(
                    "Skipping correlation source save - existing source data is richer than correlation output for %s",
                    filename,
                )
                return

            atomic_json_write(source_path, source_records, indent=2)
        except (OSError, ValueError) as e:
            logger.warning("Could not create correlation source data: %s", e)


__all__ = ["VersionOutputCorrelator"]
