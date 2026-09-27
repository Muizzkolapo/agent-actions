"""File walking, merging, and storage backend processing for ActionRunner.

Extracted from runner.py to keep both modules under ~500 LOC.
Functions that need instance method dispatch take a ``runner`` parameter
and call ``runner._process_single_file(params)`` so that monkey-patching
in tests (e.g. test_runner_merge.py) continues to work.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import stat as stat_module
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_actions.errors import is_action_fatal, raised_by_exhaustion_policy
from agent_actions.logging.diagnostics import DIAGNOSTIC
from agent_actions.storage.backend import DISPOSITION_FILTERED, NODE_LEVEL_RECORD_ID
from agent_actions.utils.atomic_write import atomic_json_write
from agent_actions.utils.file_handler import walk_files
from agent_actions.utils.limits import forget_slice_observation, resolve_file_limit
from agent_actions.workflow.merge import merge_json_files, merge_records_by_key

if TYPE_CHECKING:
    from agent_actions.workflow.runner import (
        ActionRunner,
        FileProcessParams,
        SingleFileProcessParams,
    )

logger = logging.getLogger(__name__)


@dataclass
class CollectedErrors:
    """Per-file failures for one collector pass."""

    messages: list[str] = field(default_factory=list)
    halt: Exception | None = None
    halt_message: str | None = None
    fatal: Exception | None = None
    fatal_message: str | None = None

    def record(self, relative_path: object, exc: Exception) -> None:
        if len(self.messages) < _MAX_TRACKED_ERRORS:
            self.messages.append(f"{relative_path}: {exc}")
        # Deliberately outside the cap: the halt may be the fiftieth failure,
        # and it is the one signal the next run cannot reconstruct.
        if raised_by_exhaustion_policy(exc):
            if self.halt is None:
                self.halt = exc
                self.halt_message = f"{relative_path}: {exc}"
        elif self.fatal is None and is_action_fatal(exc):
            self.fatal = exc
            self.fatal_message = f"{relative_path}: {exc}"

    def merge(self, other: CollectedErrors) -> None:
        self.messages.extend(other.messages)
        if self.halt is None:
            self.halt, self.halt_message = other.halt, other.halt_message
        if self.fatal is None:
            self.fatal, self.fatal_message = other.fatal, other.fatal_message

    @property
    def action_fatal(self) -> Exception | None:
        """The error the pass must raise, halt first: it carries the policy tag."""
        return self.halt or self.fatal

    @property
    def action_fatal_message(self) -> str | None:
        return self.halt_message if self.halt is not None else self.fatal_message


# ---------------------------------------------------------------------------
# Pure helpers (no runner param)
# ---------------------------------------------------------------------------


def is_target_directory(path: str) -> bool:
    """Return True if path is a target directory (not staging)."""
    return "target" in path and "staging" not in path


_MAX_TRACKED_ERRORS = 10  # Cap to avoid unbounded memory on mass failure
_ERROR_SAMPLE_SIZE = 3


def _format_error_sample(messages: list[str]) -> str:
    """Join the first few per-file errors for display."""
    return "; ".join(messages[:_ERROR_SAMPLE_SIZE])


def _lose_file(runner: Any, action_name: str) -> None:
    """Take the action's record count out of service: a file went uncounted.

    The failure is not fatal to the action — the walk records it and carries on
    — so the run completes holding fewer records than its input offered. A count
    missing them would let a later limit read as one that could not have bitten,
    and the action would be skipped rather than re-run. Said for any per-file
    failure, including one raised after that file was sliced: over-reporting
    costs a re-run, and under-reporting costs the records.
    """
    forget_slice_observation(getattr(runner, "storage_backend", None), action_name)


def _is_regular_file(item: Path) -> bool:
    """Whether *item* is a regular file, raising when the filesystem will not say.

    ``Path.is_file()`` cannot be used for this: it answers ``False`` for the errnos
    in ``pathlib``'s ``_IGNORED_ERRNOS`` — ``ENOENT``, ``ENOTDIR``, ``EBADF``,
    ``ELOOP`` — which a walk reads as a deliberate "not a file" and drops silently.
    It re-raises the rest, so ``EACCES`` already escaped; catching ``OSError`` here
    is deliberately wider than the silent set, so that a permission failure becomes
    the same named, counted loss rather than an error from the middle of a walk.
    """
    return stat_module.S_ISREG(item.stat().st_mode)


def _walk_label(directory: Path, root: Path) -> Path:
    """How *directory* is named in an error about the walk of *root*.

    The root itself is named rather than rendered as ``.``: the views that show
    these messages truncate at 60-80 characters, so the short end carries it.
    """
    if directory == root:
        return Path(root.name)
    try:
        return directory.relative_to(root)
    except ValueError:
        return directory


def _walk_files(root: Path, unreadable: list[tuple[Path, OSError]] | None = None) -> list[Path]:
    """Every file under *root*, collecting the directories it could not open.

    Not ``rglob``: it drops such a directory's whole subtree and raises nothing,
    handing back the directory entry alone — which the question above answers
    correctly as "not a regular file", so no loss is ever declared. A ``batch``
    directory is left out, its files being skipped whether or not it opens.
    """

    def _note(exc: OSError) -> None:
        if unreadable is None:
            return
        failed = Path(exc.filename) if exc.filename else root
        if "batch" not in failed.parts:
            unreadable.append((failed, exc))

    return walk_files(root, _note)


def _log_processing_errors(
    messages: list[str],
    processed: int,
    total: int,
    action_name: str,
    context: str,
) -> None:
    """Log a summary when some files failed processing."""
    if not messages or total == 0:
        return
    error_count = len(messages)
    suffix = (
        f" (and {error_count - _ERROR_SAMPLE_SIZE} more)"
        if error_count > _ERROR_SAMPLE_SIZE
        else ""
    )
    logger.error(
        "%s incomplete for %s: %d/%d files processed (%d errors). Errors: %s%s",
        context,
        action_name,
        processed,
        total,
        error_count,
        _format_error_sample(messages),
        suffix,
        extra={
            # Embeds the per-file messages the handlers above already logged,
            # so it restates them whether the action failed wholly or in part.
            **DIAGNOSTIC,
            "action_name": action_name,
            "files_found": total,
            "files_processed": processed,
            "error_count": error_count,
        },
    )


def _raise_all_files_failed(
    action_name: str,
    files_found: int,
    upstream_dirs: list[str],
    errors: CollectedErrors,
) -> None:
    """Raise DependencyError when files were found but all failed processing.

    Causes lead the message because the views that render it truncate (run
    summary at 80 chars, ``agac dispositions`` at 60).  The total is
    ``files_found``, never the capped error count.  The chain is the *halting*
    cause where there is one, and otherwise the first action-fatal cause:
    chaining the first failure of any kind loses the halt whenever another
    file failed before it.
    """
    from agent_actions.errors import DependencyError

    # The action-fatal cause leads when there is one: the sample is capped, so
    # a halt that failed after the cap would otherwise appear only on the chain.
    detail = (
        errors.action_fatal_message
        or _format_error_sample(errors.messages)
        or "Check logs for details."
    )
    raise DependencyError(
        f"Action '{action_name}': {detail} (Found {files_found} files but failed to process any.)",
        context={
            "action": action_name,
            "files_found": files_found,
            "upstream_dirs": upstream_dirs,
            "processing_errors": errors.messages,
        },
        cause=errors.action_fatal,
    )


def _raise_action_fatal(
    action_name: str,
    files_found: int,
    files_processed: int,
    upstream_dirs: list[str],
    errors: CollectedErrors,
) -> None:
    """Raise the collected action-fatal error despite other files succeeding.

    The layer below re-raised it deliberately; tolerating it because another
    file processed erases the policy it carries. The processed files keep the
    output they wrote, but only a halt keeps its dispositions — the reset an
    unmarked failure gets on the next run clears them, so those records are
    processed again.
    """
    from agent_actions.errors import DependencyError

    raise DependencyError(
        f"Action '{action_name}': {errors.action_fatal_message} "
        f"(Processed {files_processed} of {files_found} files, then stopped "
        f"on the action-fatal error.)",
        context={
            "action": action_name,
            "files_found": files_found,
            "files_processed": files_processed,
            "upstream_dirs": upstream_dirs,
            "processing_errors": errors.messages,
        },
        cause=errors.action_fatal,
    )


def _file_limit_reached(
    runner: ActionRunner,
    params: FileProcessParams,
    count: int,
    more_remain: Callable[[], bool],
) -> bool:
    """Whether the walk has taken as many files as the limit in force allows.

    A repair is never held back: it walks the files holding the records it named,
    and stopping short of one leaves that record's cleared disposition unwritten.

    Announced here because only the walk knows whether anything was left unread —
    reaching a limit that equalled the input is not a shortened run. *more_remain*
    is asked only once the limit is reached, so a walk it never bounds pays nothing.
    """
    if runner.retried_records:
        return False
    limit, source = resolve_file_limit(params.action_config)
    if limit is None or count < limit:
        return False
    if more_remain():
        logger.log(
            logging.INFO if source == "file_limit" else logging.WARNING,
            "%s=%d: %s stopped after %d file(s)",
            source,
            limit,
            params.action_name,
            count,
        )
    return True


def should_skip_item(
    item: Path,
    input_path: Path,
    processed_paths: set,
    file_type_filter: set[str] | None = None,
) -> bool:
    """Whether to skip *item*, raising ``OSError`` for one it cannot classify.

    The deliberate exclusions are answered first so that none of them needs the
    filesystem: a dotfile or a filtered suffix would never be processed, and
    reporting it as a lost record because ``stat()`` failed is a false alarm. Only
    an entry that survives all of them is asked whether it is a regular file, and
    that question can fail — the caller has to treat the failure as a loss rather
    than as a skip.
    """
    if "batch" in item.parts:
        return True
    if item.name.startswith("."):
        return True
    relative_path = item.relative_to(input_path)
    if relative_path in processed_paths:
        return True
    if file_type_filter and item.suffix.lstrip(".").lower() not in file_type_filter:
        return True
    return not _is_regular_file(item)


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


def _upstream_relative(item: Path, upstream_data_dirs: list[str]) -> Path:
    """*item* as a path under whichever upstream holds it, falling back to its name.

    A bare basename drops the subdirectory, so a lost ``sub/a.json`` records as
    ``a.json`` — unlike every other record in the merge walk, which is keyed by the
    group path. Two upstreams holding the same relative path still record alike;
    that is the group key's own behaviour, not something this resolves.
    """
    for directory in upstream_data_dirs:
        try:
            relative = item.relative_to(Path(directory))
        except ValueError:
            continue
        return Path(item.name) if relative == Path(".") else relative
    return Path(item.name)


def collect_files_from_upstream(
    upstream_data_dirs: list[str],
) -> tuple[dict[Path, list[Path]], list[tuple[Path, OSError]]]:
    """Collect upstream files by relative path → (grouped, the ones it could not read).

    Returned in sorted key order, not raw walk order: a file limit truncates this
    mapping, so an unordered walk makes "the first N" mean whatever the filesystem
    happened to enumerate first — a different subset on the next run of the same
    command, and interleaved by first-seen when several upstreams contribute.

    Losses are returned rather than logged here because the caller owns the action's
    record count, which a staged file that never reached the grouping leaves short.
    """
    files_by_relative_path: dict[Path, list[Path]] = {}
    lost: list[tuple[Path, OSError]] = []

    for input_directory in upstream_data_dirs:
        input_path = Path(input_directory)
        if not input_path.exists():
            continue

        for item in _walk_files(input_path, lost):
            if "batch" in item.parts:
                continue
            if item.name.startswith("."):
                continue

            try:
                if not _is_regular_file(item):
                    continue
            except OSError as e:
                lost.append((item, e))
                continue

            relative_path = item.relative_to(input_path)
            if relative_path not in files_by_relative_path:
                files_by_relative_path[relative_path] = []
            files_by_relative_path[relative_path].append(item)

    grouped = {path: files_by_relative_path[path] for path in sorted(files_by_relative_path)}
    return grouped, sorted(lost, key=lambda pair: pair[0])


def warn_no_files_found(params: FileProcessParams) -> None:
    """Log warning if no files were found in upstream directories."""
    has_content = any(
        Path(d).exists() and any(Path(d).iterdir()) for d in params.upstream_data_dirs
    )
    if not has_content:
        logger.debug(
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
) -> tuple[int, int, CollectedErrors]:
    """Process a directory → (files_found, files_processed, per_file_errors)."""
    count = 0
    errors = CollectedErrors()
    files_seen = 0
    unreadable: list[tuple[Path, OSError]] = []
    # Sorted, not raw walk order: file_limit truncates this sequence, so an
    # unordered walk makes "the first N files" mean whatever the filesystem
    # happened to enumerate first.
    items = _files_holding_retried_records(
        runner, sorted(_walk_files(input_path, unreadable)), input_path
    )
    # Same reason the walk above is sorted: `errors` keeps only the first
    # _MAX_TRACKED_ERRORS, so filesystem order would decide which losses are named.
    unreadable.sort(key=lambda pair: pair[0])
    for directory, error in unreadable:
        where = _walk_label(directory, input_path)
        files_seen += 1
        errors.record(where, error)
        _lose_file(runner, params.action_name)
        logger.warning(
            "Could not list the staging directory %s, so every file beneath it "
            "went unprocessed: %s",
            where,
            error,
        )
    for position, item in enumerate(items):
        try:
            if should_skip_item(item, input_path, processed_paths, params.file_type_filter):
                continue
        except OSError as e:
            # Counted as found because `files_found == 0` is the one path where
            # process_files neither raises nor warns: a walk that lost every entry
            # would otherwise complete green and empty.
            files_seen += 1
            errors.record(item.relative_to(input_path), e)
            _lose_file(runner, params.action_name)
            logger.warning(
                "Could not read the staged file %s, so it went unprocessed: %s",
                item.relative_to(input_path),
                e,
            )
            continue

        relative_path = item.relative_to(input_path)
        processed_paths.add(relative_path)
        files_seen += 1

        try:
            runner._process_single_file(
                _build_file_params(params, item, input_path, output_path, input_directory)
            )
            count += 1
        except Exception as e:
            errors.record(relative_path, e)
            _lose_file(runner, params.action_name)
            logger.warning(
                "Failed to process file %s: %s",
                relative_path,
                e,
                exc_info=True,
            )

        def _unread(position: int = position) -> bool:
            """Whether any entry past *position* would have been processed.

            An entry that cannot be classified counts as one that would: treating
            it as skippable is how a run stops short of a file and says nothing.
            """

            def _would_process(later: Path) -> bool:
                try:
                    return not should_skip_item(
                        later, input_path, processed_paths, params.file_type_filter
                    )
                except OSError:
                    return True

            return any(_would_process(later) for later in items[position + 1 :])

        if _file_limit_reached(runner, params, count, _unread):
            break

    _log_processing_errors(
        errors.messages, count, files_seen, params.action_name, "Directory processing"
    )
    return (files_seen, count, errors)


def _files_holding_retried_records(
    runner: ActionRunner, items: list[Path], input_path: Path
) -> list[Path]:
    """The subset of *items* a repair needs, or all of them when not repairing.

    A repair names records, not files, and walking every staged file lets
    `file_limit` spend its budget on ones holding none of them. Falls back to
    walking everything when the selection is unresolvable, or when a named record
    shares a repeat chain with another file, which needs every sibling present.
    """
    if not runner.retried_records or runner.storage_backend is None:
        return items
    retried = runner.retried_records
    if runner.storage_backend.records_share_a_repeat_chain(retried):
        logger.info(
            "Repairing %d record(s) that share identity with content staged in "
            "another file — walking every staged file so identity re-derives "
            "with the context it needs",
            len(retried),
        )
        return items
    wanted = runner.storage_backend.source_files_for_records(retried)
    if not wanted:
        logger.warning(
            "Repairing %d record(s) but no source row names the file holding any of them — "
            "walking every staged file",
            len(retried),
        )
        return items
    narrowed = [
        item for item in items if str(item.relative_to(input_path).with_suffix("")) in wanted
    ]
    if len(narrowed) != len(items):
        logger.info(
            "Repair narrowed the walk to %d of %d staged file(s)", len(narrowed), len(items)
        )
    return narrowed


def process_merged_files(
    runner: ActionRunner, params: FileProcessParams
) -> tuple[int, int, CollectedErrors]:
    """Merge and process files from several upstreams → (found, processed, per_file_errors)."""
    output_path = Path(params.output_directory)
    files_by_path, lost = collect_files_from_upstream(params.upstream_data_dirs)
    files_processed_count = 0
    errors = CollectedErrors()
    files_seen = 0
    # Not files_seen, which also counts losses: the limit probe asks how far through
    # the groups the walk is, and a loss-inclusive count compared against the group
    # total suppresses the truncation announcement by exactly the number of losses.
    # Answering in pure group terms is only correct because every loss is drained
    # below before the group loop starts, so none is ever still to come.
    groups_seen = 0

    for item, error in lost:
        files_seen += 1
        errors.record(_upstream_relative(item, params.upstream_data_dirs), error)
        _lose_file(runner, params.action_name)
        logger.warning("Could not read the upstream path %s, so it went unmerged: %s", item, error)

    for relative_path, file_paths in files_by_path.items():
        files_seen += 1
        groups_seen += 1
        try:
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
                unreadable: list[Path] = []
                merged_data = merge_json_files(
                    file_paths, reduce_key=reduce_key, unreadable=unreadable
                )
                if unreadable:
                    # The merge reads fail-open, so a corrupt branch arrives as
                    # a short result rather than an exception the handler below
                    # could catch. Those records never reach a slice either.
                    _lose_file(runner, params.action_name)
                # Guard-`filter` subtraction lives only in the storage-backend
                # fan-in (where FILTERED dispositions exist); this filesystem path
                # is unreachable whenever they do. Add it here if that changes.

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
        except Exception as e:
            errors.record(relative_path, e)
            _lose_file(runner, params.action_name)
            logger.warning(
                "Failed to process merged file %s: %s",
                relative_path,
                e,
                exc_info=True,
            )

        def _unread(seen: int = groups_seen, total: int = len(files_by_path)) -> bool:
            """Whether any group past this one is still to be merged."""
            return seen < total

        if _file_limit_reached(runner, params, files_processed_count, _unread):
            break

    _log_processing_errors(
        errors.messages,
        files_processed_count,
        files_seen,
        params.action_name,
        "Merged file processing",
    )
    return (files_seen, files_processed_count, errors)


def _resolve_upstream_root(file_path: Path, upstream_data_dirs: list[str]) -> Path:
    """Find which upstream directory a file belongs to."""
    for upstream_dir in upstream_data_dirs:
        upstream_path = Path(upstream_dir)
        if file_path.is_relative_to(upstream_path):
            return upstream_path
    return file_path.parent


def _ancestor_action_names(
    storage_backend: Any, action_name: str, upstream_data_dirs: list[str]
) -> list[str]:
    """Transitive upstream actions of ``action_name``.

    A guard ``filter`` is authoritative for the filtering action AND everything
    downstream of it, so a filtered guid must be subtracted even when the
    filtering action is a grandparent reached only via one branch.  Prefer the
    stored dependency graph (precise transitive ancestors); fall back to the
    DIRECT dependency directories — never the flat execution order, which would
    include parallel peers and could drop records that are legitimately live on
    an independent branch.
    """
    try:
        raw = storage_backend.load_metadata("dependency_graph")
    except Exception:
        raw = None
    if raw:
        try:
            graph = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            graph = None
        if isinstance(graph, dict) and isinstance(graph.get(action_name), list):
            return [a for a in graph[action_name] if a != "staging"]
    return [Path(d).name for d in upstream_data_dirs if Path(d).name != "staging"]


def _collect_upstream_filtered_guids(
    storage_backend: Any, action_name: str, upstream_data_dirs: list[str]
) -> set[str]:
    """Return source_guids a guard `filter` excluded anywhere upstream of ``action_name``.

    A filtered record is dead (guards/ARCHITECTURE.md) but leaves a per-record
    FILTERED disposition, so it can re-enter via an unfiltered sibling — these
    guids are subtracted at fan-in.  ``__node__`` markers are rerun signals, not
    record ids.  Fails open on storage errors (a safety net must not abort).
    """
    filtered_guids: set[str] = set()
    for dep in _ancestor_action_names(storage_backend, action_name, upstream_data_dirs):
        try:
            dispositions = storage_backend.get_disposition(dep, disposition=DISPOSITION_FILTERED)
        except (OSError, sqlite3.Error, ValueError) as e:
            logger.warning(
                "Could not read FILTERED dispositions for upstream '%s' — "
                "filter authority not enforced for it this run: %s",
                dep,
                e,
            )
            continue
        for disp in dispositions:
            record_id = disp.get("record_id")
            if record_id and record_id != NODE_LEVEL_RECORD_ID:
                filtered_guids.add(record_id)
    return filtered_guids


def _drop_filtered_records(data: Any, filtered_guids: set[str]) -> tuple[Any, int]:
    """Drop records whose source_guid was guard-filtered upstream. Returns (kept, dropped)."""
    if not filtered_guids or not isinstance(data, list):
        return data, 0
    kept = [
        record
        for record in data
        if not (isinstance(record, dict) and record.get("source_guid") in filtered_guids)
    ]
    return kept, len(data) - len(kept)


def process_from_storage_backend(
    runner: ActionRunner, params: FileProcessParams
) -> tuple[int, int, CollectedErrors]:
    """Process backend data instead of filesystem → (found, processed, per_file_errors)."""

    if runner.storage_backend is None:
        return (0, 0, CollectedErrors())

    output_path = Path(params.output_directory)
    errors = CollectedErrors()

    data_by_path: dict[str, list[tuple[str, Any]]] = {}

    for input_directory in params.upstream_data_dirs:
        input_path = Path(input_directory)
        action_name = input_path.name

        if "staging" in str(input_path):
            continue

        try:
            target_files = runner.storage_backend.list_target_files(action_name)
        except (OSError, sqlite3.Error) as e:
            # Every file of this upstream is gone, and none of them is in
            # data_by_path to be counted or reported. Keyed on the action being
            # run, not the upstream being read.
            _lose_file(runner, params.action_name)
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
            except (OSError, sqlite3.Error, json.JSONDecodeError) as e:
                # Dropped before the processing loop, so it never reaches the
                # handler there, is absent from data_by_path and so from
                # files_found, and lands in no CollectedErrors either.
                _lose_file(runner, params.action_name)
                logger.warning(
                    "Failed to read backend entry %s/%s: %s",
                    action_name,
                    relative_path,
                    e,
                    exc_info=True,
                )

    # Sorted, not upstream-major: a file limit truncates this mapping, and the
    # union of several upstreams is otherwise ordered by which one was read first.
    data_by_path = {path: data_by_path[path] for path in sorted(data_by_path)}

    files_found = len(data_by_path)
    files_processed = 0

    # A guard `filter` anywhere upstream makes those records dead — they must not
    # re-enter here through an unfiltered sibling dependency.
    filtered_guids = _collect_upstream_filtered_guids(
        runner.storage_backend, params.action_name, params.upstream_data_dirs
    )

    for seen, (relative_path, data_sources) in enumerate(data_by_path.items(), start=1):
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

            data, dropped = _drop_filtered_records(data, filtered_guids)
            if dropped:
                logger.info(
                    "%s: dropped %d record(s) filtered by an upstream guard "
                    "(filter is authoritative — dead records are not carried forward)",
                    params.action_name,
                    dropped,
                )

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

        except Exception as e:
            errors.record(relative_path, e)
            _lose_file(runner, params.action_name)
            logger.warning(
                "Failed to process backend entry %s: %s",
                relative_path,
                e,
                exc_info=True,
            )

        def _unread(taken: int = seen, total: int = len(data_by_path)) -> bool:
            """Whether any stored entry past this one is still to be read."""
            return taken < total

        if _file_limit_reached(runner, params, files_processed, _unread):
            break

    _log_processing_errors(
        errors.messages,
        files_processed,
        files_found,
        params.action_name,
        "Storage backend processing",
    )
    return (files_found, files_processed, errors)


def process_files(runner: ActionRunner, params: FileProcessParams) -> None:
    """Walk upstream data directories and process each file with the given strategy."""
    if runner.storage_backend is not None:
        all_targets = all(is_target_directory(d) for d in params.upstream_data_dirs)
        if all_targets:
            files_found, files_processed, errors = process_from_storage_backend(runner, params)
            if files_processed > 0:
                if errors.action_fatal is not None:
                    _raise_action_fatal(
                        params.action_name,
                        files_found,
                        files_processed,
                        params.upstream_data_dirs,
                        errors,
                    )
                return
            if files_found > 0:
                # Data was found in DB but processing failed
                # Don't fall through to filesystem (virtual paths don't exist)
                _raise_all_files_failed(
                    params.action_name, files_found, params.upstream_data_dirs, errors
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

        files_found, files_processed, errors = process_merged_files(runner, params)
        if files_processed == 0:
            if files_found > 0:
                _raise_all_files_failed(
                    params.action_name, files_found, params.upstream_data_dirs, errors
                )
            warn_no_files_found(params)
        elif errors.action_fatal is not None:
            _raise_action_fatal(
                params.action_name, files_found, files_processed, params.upstream_data_dirs, errors
            )
        return

    total_found = 0
    total_processed = 0
    all_errors = CollectedErrors()
    output_path = Path(params.output_directory)
    processed_relative_paths: set = set()

    for input_directory in params.upstream_data_dirs:
        input_path = Path(input_directory)
        if not input_path.exists():
            logger.warning("Upstream directory not found: %s", input_directory)
            continue

        found, processed, errors = process_directory_files(
            runner, input_path, output_path, input_directory, params, processed_relative_paths
        )
        total_found += found
        total_processed += processed
        all_errors.merge(errors)

    if total_processed == 0:
        if total_found > 0:
            _raise_all_files_failed(
                params.action_name, total_found, params.upstream_data_dirs, all_errors
            )
        warn_no_files_found(params)
    elif all_errors.action_fatal is not None:
        _raise_action_fatal(
            params.action_name, total_found, total_processed, params.upstream_data_dirs, all_errors
        )
