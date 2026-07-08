"""Version output correlation for parallel map-reduce patterns."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_actions.errors import AgentActionsError, ConfigurationError, DataValidationError
from agent_actions.input.preprocessing.staging.initial_pipeline import _should_save_source_items
from agent_actions.utils.atomic_write import atomic_json_write
from agent_actions.utils.content import get_existing_content
from agent_actions.workflow.managers.output import AllVersionsFilteredError
from agent_actions.workflow.merge import merge_branch_records

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)


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
            outputs, filenames = self._load_from_storage_backend(version_agent)
            if outputs:
                version_outputs[version_agent] = outputs
                version_filenames.update(filenames)

        return version_outputs, version_filenames

    def _load_from_storage_backend(self, version_agent: str) -> tuple[list[dict[str, Any]], set]:
        """Load outputs from storage backend for a version agent."""
        if self.storage_backend is None:
            logger.warning(
                "No storage backend configured — cannot load version outputs for %s",
                version_agent,
            )
            return [], set()

        outputs = []
        filenames = set()

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
            except FileNotFoundError:
                logger.warning(
                    "Target %s/%s listed but not found (possible TOCTOU race) — skipping",
                    version_agent,
                    relative_path,
                )

        logger.debug(
            "Loaded %d records from storage backend for %s (files: %s)",
            len(outputs),
            version_agent,
            list(filenames),
        )
        return outputs, filenames

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
    ) -> str:
        """Return the correlated input directory.

        Raises AllVersionsFilteredError when every version source produced zero
        records (nothing to merge — the caller cascade-skips), or
        ConfigurationError on a correlation or storage fault.
        """
        try:
            correlation_dir = self.agent_folder / "target" / agent_name
            if self.storage_backend is None:
                correlation_dir.mkdir(parents=True, exist_ok=True)

            version_outputs, version_filenames = self._load_version_outputs(version_sources)
            if not version_outputs:
                raise AllVersionsFilteredError(agent_name, version_sources)

            self._process_version_files(
                version_outputs, version_filenames, correlation_dir, action_name=agent_name
            )
            return str(correlation_dir)
        except (AllVersionsFilteredError, AgentActionsError):
            raise
        except Exception as e:
            # Translate raw backend/OS faults into a clean, loud ConfigurationError
            # rather than letting a raw traceback escape.
            raise ConfigurationError(
                f"Version correlation failed for '{agent_name}' from sources "
                f"{version_sources}: {e}",
                context={"agent": agent_name, "version_sources": version_sources},
            ) from e

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
                        f"Could not align versions for source record '{source_guid}': "
                        f"version '{version_agent}' produced a record with no "
                        f"version_correlation_id. All N parallel versions of a source "
                        f"record must share one id before a merge consumer can group them.",
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

        if base_record.get("source_guid") is None:
            logger.warning(
                "Missing 'source_guid' in base record during version output correlation; "
                "merged record will have source_guid=None"
            )

        # Version-specific invariant: every record must have its own namespace.
        # merge_branch_records warns and skips; version merge requires strict enforcement.
        for agent_name, record in agent_records.items():
            content = get_existing_content(record)
            if agent_name not in content:
                raise DataValidationError(
                    f"Version record missing own namespace '{agent_name}' in content",
                    {"agent_name": agent_name, "content_keys": list(content.keys())},
                )

        merged_record = merge_branch_records(agent_records)
        merged_record["_correlation_sources"] = list(agent_records.keys())

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
                tagged_data = [{**r, "_delta_mode": "full"} for r in cleaned_data]
                self.storage_backend.write_target(action_name, filename, tagged_data)
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
            output_file = output_dir / filename
            self._create_correlation_source_data(output_file, cleaned_data)
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
