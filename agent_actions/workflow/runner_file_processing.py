"""File walking, merging, and storage backend processing for ActionRunner.

Extracted from runner.py to keep both modules under ~500 LOC.
Functions that need instance method dispatch take a ``runner`` parameter
and call ``runner._process_single_file(params)`` so that monkey-patching
in tests (e.g. test_runner_merge.py) continues to work.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_actions.utils.atomic_write import atomic_json_write
from agent_actions.workflow.merge import merge_json_files, merge_records_by_key

if TYPE_CHECKING:
    from agent_actions.workflow.runner import (
        ActionRunner,
        FileProcessParams,
        SingleFileProcessParams,
    )

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers (no runner param)
# ---------------------------------------------------------------------------


def is_target_directory(path: str) -> bool:
    """Return True if path is a target directory (not staging)."""
    return "target" in path and "staging" not in path


def _file_limit_reached(action_config: dict, count: int, action_name: str) -> bool:
    """Return True (and log) if file_limit has been reached."""
    file_limit = action_config.get("file_limit")
    if file_limit is not None and count >= file_limit:
        logger.info("file_limit=%d reached for %s", count, action_name)
        return True
    return False


def should_skip_item(
    item: Path,
    input_path: Path,
    processed_paths: set,
    file_type_filter: set[str] | None = None,
) -> bool:
    """Check if an item should be skipped during processing."""
    if "batch" in item.parts:
        return True
    if not item.is_file():
        return True
    if item.name.startswith("."):
        return True
    relative_path = item.relative_to(input_path)
    if relative_path in processed_paths:
        return True
    if file_type_filter and item.suffix.lstrip(".").lower() not in file_type_filter:
        return True
    return False


def _build_file_params(
    params: FileProcessParams,
    item: Path,
    input_path: Path,
    output_path: Path,
    input_directory: str,
    *,
    source_relative_path: str | None = None,
    data: Any = None,
) -> SingleFileProcessParams:
    """Build SingleFileProcessParams with shared fields from FileProcessParams."""
    from agent_actions.workflow.runner import FileLocationParams, SingleFileProcessParams

    kwargs: dict[str, Any] = {
        "locations": FileLocationParams(
            item=item,
            input_path=input_path,
            output_path=output_path,
            input_directory=input_directory,
        ),
        "action_config": params.action_config,
        "action_name": params.action_name,
        "strategy": params.strategy,
        "idx": params.idx,
    }
    if source_relative_path is not None:
        kwargs["source_relative_path"] = source_relative_path
    if data is not None:
        kwargs["data"] = data
    return SingleFileProcessParams(**kwargs)


def collect_files_from_upstream(upstream_data_dirs: list[str]) -> dict[Path, list[Path]]:
    """Collect files from upstream directories, grouped by relative path."""
    files_by_relative_path: dict[Path, list[Path]] = {}

    for input_directory in upstream_data_dirs:
        input_path = Path(input_directory)
        if not input_path.exists():
            continue

        for item in input_path.rglob("*"):
            if "batch" in item.parts:
                continue
            if not item.is_file():
                continue
            if item.name.startswith("."):
                continue

            relative_path = item.relative_to(input_path)
            if relative_path not in files_by_relative_path:
                files_by_relative_path[relative_path] = []
            files_by_relative_path[relative_path].append(item)

    return files_by_relative_path


def warn_no_files_found(params: FileProcessParams) -> None:
    """Log warning if no files were found in upstream directories."""
    has_content = any(
        Path(d).exists() and any(Path(d).iterdir()) for d in params.upstream_data_dirs
    )
    if not has_content:
        logger.warning(
            "No files found in upstream directories: %s. Processing continues.",
            params.upstream_data_dirs,
            extra={
                "upstream_data_dirs": params.upstream_data_dirs,
                "action_name": params.action_name,
                "operation": "directory_processing",
            },
        )


# ---------------------------------------------------------------------------
# Functions taking ``runner`` param (call runner._process_single_file)
# ---------------------------------------------------------------------------


def process_directory_files(
    runner: ActionRunner,
    input_path: Path,
    output_path: Path,
    input_directory: str,
    params: FileProcessParams,
    processed_paths: set,
) -> int:
    """Process all files in a single directory. Returns count of files processed."""
    count = 0
    for item in input_path.rglob("*"):
        if runner._should_skip_item(item, input_path, processed_paths, params.file_type_filter):
            continue

        relative_path = item.relative_to(input_path)
        processed_paths.add(relative_path)

        runner._process_single_file(
            _build_file_params(params, item, input_path, output_path, input_directory)
        )
        count += 1
        if _file_limit_reached(params.action_config, count, params.action_name):
            break
    return count


def process_merged_files(runner: ActionRunner, params: FileProcessParams) -> int:
    """Process files from multiple upstream directories with content merging."""
    output_path = Path(params.output_directory)
    files_by_path = runner._collect_files_from_upstream(params.upstream_data_dirs)
    files_processed_count = 0

    for relative_path, file_paths in files_by_path.items():
        if len(file_paths) == 1:
            file_path = file_paths[0]
            input_path = _resolve_upstream_root(file_path, params.upstream_data_dirs)

            runner._process_single_file(
                _build_file_params(params, file_path, input_path, output_path, str(input_path))
            )
        else:
            reduce_key = params.action_config.get("reduce_key")
            logger.debug(
                "Merging %d files for %s (reduce_key=%s)",
                len(file_paths),
                relative_path,
                reduce_key or "auto",
            )
            merged_data = merge_json_files(file_paths, reduce_key=reduce_key)

            # TemporaryDirectory instead of in-place overwrite: the old approach
            # (overwrite + restore in finally) left corrupt files on SIGKILL.
            with tempfile.TemporaryDirectory() as td:
                tmp_file = Path(td) / relative_path
                tmp_file.parent.mkdir(parents=True, exist_ok=True)
                atomic_json_write(tmp_file, merged_data, fsync=False)

                runner._process_single_file(
                    _build_file_params(params, tmp_file, Path(td), output_path, td)
                )

        files_processed_count += 1
        if _file_limit_reached(params.action_config, files_processed_count, params.action_name):
            break

    return files_processed_count


def _resolve_upstream_root(file_path: Path, upstream_data_dirs: list[str]) -> Path:
    """Find which upstream directory a file belongs to."""
    for upstream_dir in upstream_data_dirs:
        upstream_path = Path(upstream_dir)
        if file_path.is_relative_to(upstream_path):
            return upstream_path
    return file_path.parent


def process_from_storage_backend(
    runner: ActionRunner, params: FileProcessParams
) -> tuple[int, int]:
    """Process data from storage backend instead of filesystem.

    Returns:
        (files_found, files_processed) to distinguish "no data" from
        "data found but processing failed".
    """

    if runner.storage_backend is None:
        return (0, 0)

    output_path = Path(params.output_directory)
    processing_errors: list[str] = []

    data_by_path: dict[str, list[tuple[str, Any]]] = {}

    for input_directory in params.upstream_data_dirs:
        input_path = Path(input_directory)
        action_name = input_path.name

        if "staging" in str(input_path):
            continue

        try:
            target_files = runner.storage_backend.list_target_files(action_name)
        except Exception as e:
            logger.warning(
                "Could not list target files from backend for %s: %s",
                action_name,
                e,
                exc_info=True,
            )
            continue

        for relative_path in target_files:
            try:
                data = runner.storage_backend.read_target(action_name, relative_path)
                if relative_path not in data_by_path:
                    data_by_path[relative_path] = []
                data_by_path[relative_path].append((action_name, data))
            except Exception as e:
                logger.warning(
                    "Failed to read backend entry %s/%s: %s",
                    action_name,
                    relative_path,
                    e,
                    exc_info=True,
                )

    files_found = len(data_by_path)
    files_processed = 0

    for relative_path, data_sources in data_by_path.items():
        try:
            if len(data_sources) == 1:
                _, data = data_sources[0]
            else:
                reduce_key = params.action_config.get("reduce_key")
                logger.debug(
                    "Merging %d sources for %s from parallel branches (reduce_key=%s)",
                    len(data_sources),
                    relative_path,
                    reduce_key or "auto",
                )
                all_data: list[Any] = []
                for _, source_data in data_sources:
                    if isinstance(source_data, list):
                        all_data.extend(source_data)
                    else:
                        all_data.append(source_data)
                data = merge_records_by_key(all_data, reduce_key)

            source_key = str(Path(relative_path).with_suffix(""))
            virtual_input_path = output_path / relative_path

            record_count = len(data) if isinstance(data, list) else 1
            logger.debug(
                "Processing %s with %d pre-loaded records (no file read)",
                relative_path,
                record_count,
            )
            runner._process_single_file(
                _build_file_params(
                    params,
                    virtual_input_path,
                    output_path,
                    output_path,
                    str(output_path),
                    source_relative_path=source_key,
                    data=data,
                )
            )
            files_processed += 1
            if _file_limit_reached(params.action_config, files_processed, params.action_name):
                break

        except Exception as e:
            error_msg = f"{relative_path}: {e}"
            processing_errors.append(error_msg)
            logger.warning(
                "Failed to process backend entry %s: %s",
                relative_path,
                e,
                exc_info=True,
            )

    if files_found > 0 and files_processed < files_found:
        logger.error(
            "Storage backend processing incomplete: %d/%d files processed for %s. Errors: %s",
            files_processed,
            files_found,
            params.action_name,
            "; ".join(processing_errors[:3]),  # Show first 3 errors
            extra={
                "action_name": params.action_name,
                "files_found": files_found,
                "files_processed": files_processed,
                "error_count": len(processing_errors),
            },
        )

    return (files_found, files_processed)


def process_files(runner: ActionRunner, params: FileProcessParams) -> None:
    """Walk upstream data directories and process each file with the given strategy."""
    if runner.storage_backend is not None:
        all_targets = all(is_target_directory(d) for d in params.upstream_data_dirs)
        if all_targets:
            files_found, files_processed = process_from_storage_backend(runner, params)
            if files_processed > 0:
                return
            if files_found > 0:
                # Data was found in DB but processing failed
                # Don't fall through to filesystem (virtual paths don't exist)
                from agent_actions.errors import DependencyError

                raise DependencyError(
                    f"Action '{params.action_name}': Found {files_found} files in storage "
                    f"backend but failed to process any. Check logs for details.",
                    context={
                        "action": params.action_name,
                        "files_found": files_found,
                        "upstream_dirs": params.upstream_data_dirs,
                    },
                )
            # Fall through to filesystem if backend had no data

    if len(params.upstream_data_dirs) > 1:
        upstream_paths = [Path(d) for d in params.upstream_data_dirs]
        dep_names = [p.name for p in upstream_paths]
        unique_names = set(dep_names)

        if len(unique_names) == 1:
            logger.info(
                "Parallel branches from '%s': merging %d outputs.",
                next(iter(unique_names)),
                len(upstream_paths),
            )
        else:
            logger.info("Multiple dependencies detected: %s. Merging all inputs.", dep_names)

        files_processed_count = process_merged_files(runner, params)
        if files_processed_count == 0:
            warn_no_files_found(params)
        return

    files_processed_count = 0
    output_path = Path(params.output_directory)
    processed_relative_paths: set = set()

    for input_directory in params.upstream_data_dirs:
        input_path = Path(input_directory)
        if not input_path.exists():
            logger.warning("Upstream directory not found: %s", input_directory)
            continue

        files_processed_count += process_directory_files(
            runner, input_path, output_path, input_directory, params, processed_relative_paths
        )

    if files_processed_count == 0:
        warn_no_files_found(params)
