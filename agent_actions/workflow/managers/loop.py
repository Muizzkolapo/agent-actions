"""Version output correlation for parallel map-reduce patterns."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_actions.errors import AgentActionsError, ConfigurationError, DataValidationError
from agent_actions.logging.diagnostics import DIAGNOSTIC
from agent_actions.utils.content import get_existing_content
from agent_actions.utils.limits import forget_slice_observation
from agent_actions.workflow.managers.output import AllVersionsFilteredError
from agent_actions.workflow.merge import merge_branch_records

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend

logger = logging.getLogger(__name__)

_CORRELATION_KEYS = frozenset({"_correlation_sources", "_missing_iterations"})


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
        self, version_sources: list[str], lost: list[str] | None = None
    ) -> tuple[dict[str, list[dict[str, Any]]], set]:
        """Load outputs from all version sources, preferring storage backend over filesystem."""
        version_outputs = {}
        version_filenames = set()

        for version_agent in version_sources:
            outputs, filenames = self._load_from_storage_backend(version_agent, lost)
            if outputs:
                version_outputs[version_agent] = outputs
                version_filenames.update(filenames)

        return version_outputs, version_filenames

    def _load_from_storage_backend(
        self, version_agent: str, lost: list[str] | None = None
    ) -> tuple[list[dict[str, Any]], set]:
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
                if lost is not None:
                    lost.append(relative_path)
                logger.warning(
                    "Target %s/%s listed but not found (possible TOCTOU race) — skipping",
                    version_agent,
                    relative_path,
                    extra=DIAGNOSTIC,
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
    ) -> dict[str, list[dict[str, Any]]]:
        """Correlate outputs by file; a file every version holds empty correlates to []."""
        correlated: dict[str, list[dict[str, Any]]] = {}
        for filename in version_filenames:
            file_version_outputs = {}
            for version_agent, outputs in version_outputs.items():
                file_outputs = [o for o in outputs if o.get("_source_file") == filename]
                if file_outputs:
                    file_version_outputs[version_agent] = file_outputs
            correlated[filename] = [
                {k: v for k, v in record.items() if k not in _CORRELATION_KEYS}
                for record in self._correlate_by_source_record(file_version_outputs)
            ]
        return correlated

    def prepare_correlated_input(
        self, agent_name: str, version_sources: list[str], _current_idx: int
    ) -> dict[str, list[dict[str, Any]]]:
        """Return the merged input of each file a version source lists, by its path.

        Handed to the consumer's walk rather than stored: the consumer's own target
        holds its answers, which a run carries records from. Raises
        AllVersionsFilteredError when every version source produced zero records
        (nothing to merge — the caller cascade-skips), ConfigurationError on a
        storage fault, or DataValidationError when a version record cannot be aligned.
        """
        try:
            lost: list[str] = []
            version_outputs, version_filenames = self._load_version_outputs(version_sources, lost)
            if lost:
                # A source that vanished between listing and reading is skipped
                # rather than raised, so the correlated input the consumer then
                # walks is already short and its slice never sees the records.
                forget_slice_observation(self.storage_backend, agent_name)
            if not version_outputs:
                raise AllVersionsFilteredError(agent_name, version_sources)

            correlated = self._process_version_files(version_outputs, version_filenames)
            self._forget_files_no_version_holds(agent_name, version_sources)
            return correlated
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

    def _forget_files_no_version_holds(self, agent_name: str, version_sources: list[str]) -> None:
        """Delete the merge's stored files that no version source lists: their input is gone.

        Under a file limit and a repair too, where the walk does not delete what its
        input no longer holds: every version file is listed, so a file none lists is
        gone, not unopened. A failure only warns.
        """
        from agent_actions.workflow.runner_file_processing import forget_files_of_inputs_gone

        backend = self.storage_backend
        if backend is None:
            return
        try:
            listed = {
                name for source in version_sources for name in backend.list_target_files(source)
            }
            gone = [name for name in backend.list_target_files(agent_name) if name not in listed]
            if gone:
                forget_files_of_inputs_gone(backend, agent_name, gone, listed)
        except Exception as e:
            logger.warning(
                "Could not delete what '%s' stores for input that is gone: %s", agent_name, e
            )

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
                "merged record will have source_guid=None",
                extra=DIAGNOSTIC,
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


__all__ = ["VersionOutputCorrelator"]
