"""File walking, merging, and storage backend processing for ActionRunner.

Extracted from runner.py to keep both modules under ~500 LOC.
Functions that need instance method dispatch take a ``runner`` parameter
and call ``runner._process_single_file(params)`` so that monkey-patching
in tests (e.g. test_runner_merge.py) continues to work.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_actions.workflow.merge import merge_json_files, merge_records_by_key

if TYPE_CHECKING:
    from agent_actions.storage.backend import StorageBackend
    from agent_actions.workflow.runner import ActionRunner, FileProcessParams

logger = logging.getLogger(__name__)

# Cache of cross-workflow SQLite backends opened during a run.
_cross_workflow_backends: dict[Path, StorageBackend] = {}


def clear_cross_workflow_backends() -> None:
    """Close and clear cached cross-workflow storage backends.

    Called at workflow run teardown and between tests.
    """
    _cross_workflow_backends.clear()


def _resolve_backend_for_path(runner: ActionRunner, input_path: Path) -> StorageBackend:
    """Return the correct storage backend for *input_path*.

    When *input_path* points to a different workflow's ``target/`` directory
    (cross-workflow dependency), open that workflow's SQLite DB read-only.
    Otherwise, return the runner's own backend.
    """
    if runner.storage_backend is None:
        raise RuntimeError("No storage backend available")

    # Check if this path belongs to the runner's own workflow.
    own_db_path = Path(runner.storage_backend.db_path)  # type: ignore[attr-defined]
    own_target_dir = own_db_path.parent  # .../agent_io/target

    # If input_path is under our own target dir, use the runner's backend.
    try:
        input_path.resolve().relative_to(own_target_dir.resolve())
        return runner.storage_backend
    except ValueError:
        pass

    # Cross-workflow: find the upstream's DB in the input path's target dir.
    # input_path is something like:
    #   .../upstream_wf/agent_io/target/format_quiz_text  OR
    #   .../upstream_wf/agent_io/target
    # Walk up to find the target/ dir, then look for the .db file.
    candidate = input_path
    while candidate.name != "target" and candidate != candidate.parent:
        candidate = candidate.parent

    if candidate.name != "target":
        # Can't determine upstream DB — fall back to runner's backend.
        return runner.storage_backend

    upstream_target_dir = candidate

    if upstream_target_dir in _cross_workflow_backends:
        return _cross_workflow_backends[upstream_target_dir]

    # Find the .db file in the upstream's target dir.
    db_files = list(upstream_target_dir.glob("*.db"))
    if not db_files:
        return runner.storage_backend

    upstream_db = db_files[0]
    logger.info(
        "Opening cross-workflow storage backend: %s",
        upstream_db,
    )

    from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

    upstream_backend = SQLiteBackend(
        db_path=str(upstream_db),
        workflow_name=upstream_db.stem,
    )
    upstream_backend.initialize()
    _cross_workflow_backends[upstream_target_dir] = upstream_backend
    return upstream_backend


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
    from agent_actions.workflow.runner import FileLocationParams, SingleFileProcessParams

    count = 0
    for item in input_path.rglob("*"):
        if runner._should_skip_item(item, input_path, processed_paths, params.file_type_filter):
            continue

        relative_path = item.relative_to(input_path)
        processed_paths.add(relative_path)

        runner._process_single_file(
            SingleFileProcessParams(
                locations=FileLocationParams(
                    item=item,
                    input_path=input_path,
                    output_path=output_path,
                    input_directory=input_directory,
                ),
                action_config=params.action_config,
                action_name=params.action_name,
                strategy=params.strategy,
                idx=params.idx,
            )
        )
        count += 1
        if _file_limit_reached(params.action_config, count, params.action_name):
            break
    return count


def process_merged_files(runner: ActionRunner, params: FileProcessParams) -> int:
    """Process files from multiple upstream directories with content merging."""
    from agent_actions.workflow.runner import FileLocationParams, SingleFileProcessParams

    output_path = Path(params.output_directory)
    files_by_path = runner._collect_files_from_upstream(params.upstream_data_dirs)
    files_processed_count = 0

    for relative_path, file_paths in files_by_path.items():
        if len(file_paths) == 1:
            file_path = file_paths[0]
            input_path = file_path.parent
            while input_path.name != "target" and input_path.parent != input_path:
                input_path = input_path.parent
            if input_path.name == "target":
                input_path = file_path.parent

            # Find the upstream directory this file belongs to
            for upstream_dir in params.upstream_data_dirs:
                upstream_path = Path(upstream_dir)
                if file_path.is_relative_to(upstream_path):
                    input_path = upstream_path
                    break

            runner._process_single_file(
                SingleFileProcessParams(
                    locations=FileLocationParams(
                        item=file_path,
                        input_path=input_path,
                        output_path=output_path,
                        input_directory=str(input_path),
                    ),
                    action_config=params.action_config,
                    action_name=params.action_name,
                    strategy=params.strategy,
                    idx=params.idx,
                )
            )
        else:
            reduce_key = params.action_config.get("reduce_key")
            logger.debug(
                "Merging %d files for %s from parallel branches (reduce_key=%s)",
                len(file_paths),
                relative_path,
                reduce_key or "auto",
            )
            merged_data = merge_json_files(file_paths, reduce_key=reduce_key)

            # Write merged data to a temp directory instead of mutating the
            # upstream file in-place.  The old approach (overwrite + restore
            # in finally) left corrupt files on SIGKILL because the finally
            # block never ran.  Using TemporaryDirectory preserves the
            # relative_path structure so _process_single_file computes the
            # correct output filename.
            with tempfile.TemporaryDirectory() as td:
                tmp_file = Path(td) / relative_path
                tmp_file.parent.mkdir(parents=True, exist_ok=True)
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(merged_data, f)

                runner._process_single_file(
                    SingleFileProcessParams(
                        locations=FileLocationParams(
                            item=tmp_file,
                            input_path=Path(td),
                            output_path=output_path,
                            input_directory=str(Path(td)),
                        ),
                        action_config=params.action_config,
                        action_name=params.action_name,
                        strategy=params.strategy,
                        idx=params.idx,
                    )
                )

        files_processed_count += 1
        if _file_limit_reached(params.action_config, files_processed_count, params.action_name):
            break

    return files_processed_count


def process_from_storage_backend(
    runner: ActionRunner, params: FileProcessParams
) -> tuple[int, int]:
    """Process data from storage backend instead of filesystem.

    Returns:
        (files_found, files_processed) to distinguish "no data" from
        "data found but processing failed".
    """
    from agent_actions.workflow.runner import FileLocationParams, SingleFileProcessParams

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

        # Determine which storage backend to query.  When the input dir
        # points to a *different* workflow's target (cross-workflow dep),
        # open that workflow's DB instead of the current runner's.
        backend = _resolve_backend_for_path(runner, input_path)

        try:
            target_files = backend.list_target_files(action_name)
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
                data = backend.read_target(action_name, relative_path)
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
                SingleFileProcessParams(
                    locations=FileLocationParams(
                        item=virtual_input_path,
                        input_path=output_path,
                        output_path=output_path,
                        input_directory=str(output_path),
                    ),
                    action_config=params.action_config,
                    action_name=params.action_name,
                    strategy=params.strategy,
                    idx=params.idx,
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


def _is_cross_workflow_input(runner: ActionRunner, upstream_dirs: list[str]) -> bool:
    """Return True if any upstream dir belongs to a different workflow's target."""
    if not runner.storage_backend:
        return False
    db_path = getattr(runner.storage_backend, "db_path", None)
    if not isinstance(db_path, (str, Path)):
        return False
    try:
        own_target = Path(db_path).parent.resolve()
    except (TypeError, OSError):
        return False
    for d in upstream_dirs:
        try:
            Path(d).resolve().relative_to(own_target)
        except ValueError:
            if is_target_directory(d):
                return True
    return False


def process_files(runner: ActionRunner, params: FileProcessParams) -> None:
    """Walk upstream data directories and process each file with the given strategy."""
    if runner.storage_backend is not None:
        # Skip storage backend for cross-workflow inputs — their data was
        # exported to JSON files by the artifact linker.
        all_targets = all(is_target_directory(d) for d in params.upstream_data_dirs)
        cross_wf = _is_cross_workflow_input(runner, params.upstream_data_dirs)
        if all_targets and not cross_wf:
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
        # Check if this is parallel branches (same action) or multiple deps
        upstream_paths = [Path(d) for d in params.upstream_data_dirs]
        dep_names = [p.name for p in upstream_paths]
        unique_names = set(dep_names)

        if len(unique_names) == 1:
            # Parallel branches from same action - merge them
            logger.info(
                f"Detected parallel branches from '{unique_names.pop()}'. "
                f"Merging {len(upstream_paths)} outputs."
            )
            files_processed_count = process_merged_files(runner, params)
            if files_processed_count == 0:
                warn_no_files_found(params)
            return
        else:
            # Fan-in pattern: multiple different dependencies
            # This should have been resolved to primary dependency in _resolve_dependency_directories()
            # If we reach here, it means all directories should be merged (aggregation pattern)
            logger.info(
                f"Multiple dependency directories detected: {dep_names}. "
                f"Merging all inputs (aggregation pattern)."
            )
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
