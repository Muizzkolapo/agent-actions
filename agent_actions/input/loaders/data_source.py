"""Data source resolver for start-node input directories."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from agent_actions.config.defaults import ApiDefaults
from agent_actions.errors import ConfigurationError, FileSystemError
from agent_actions.input.loaders.database_source import (
    DEFAULT_SNAPSHOT_FILES,
    REMOTE_CACHE_DIR,
    refuse_a_statement_that_writes,
    replaces_a_snapshot,
    snapshot_directory,
    snapshot_fingerprint,
    snapshot_needs_reading,
    snapshot_query,
)
from agent_actions.utils import deep_json
from agent_actions.utils.atomic_write import atomic_json_write
from agent_actions.utils.project_root import find_project_root


class DataSourceType(str, Enum):
    """Type of data source for start-node input."""

    STAGING = "staging"
    LOCAL = "local"
    API = "api"
    DATABASE = "database"


class DataSourceConfig(BaseModel):
    """Configuration for a start-node data source, instantiated only at resolution time."""

    type: DataSourceType = Field(default=DataSourceType.STAGING, description="Data source type")
    folder: str | None = Field(default=None, description="Local folder path (for type=local)")
    file_type: list[str] | None = Field(
        default=None, description="File type filter, e.g. ['json', 'csv']"
    )
    url: str | None = Field(default=None, description="API endpoint URL (for type=api)")
    headers: dict[str, str] | None = Field(
        default=None, description="HTTP headers for API requests"
    )
    query: dict[str, str] | None = Field(
        default=None, description="Query parameters for API requests"
    )
    sql: str | None = Field(default=None, description="The query to read (for type=database)")
    connection: str | None = Field(
        default=None, description="Name of a project connection (for type=database)"
    )
    files: int = Field(
        default=DEFAULT_SNAPSHOT_FILES,
        ge=1,
        le=256,
        description="Files the rows are spread over (for type=database)",
    )

    model_config = ConfigDict(extra="forbid")


logger = logging.getLogger(__name__)

# Safety limits for API fetches
_MAX_RESPONSE_BYTES = ApiDefaults.MAX_RESPONSE_BYTES
_REQUEST_TIMEOUT_SECONDS = ApiDefaults.REQUEST_TIMEOUT_SECONDS
_REMOTE_CACHE_DIR = REMOTE_CACHE_DIR

# Type names that require dict config — used to catch bare-string typos early
_KNOWN_TYPES = {t.value for t in DataSourceType}


@dataclass
class DataSourceResolutionResult:
    """Result of resolving a data source to concrete directories."""

    directories: list[Path]
    file_type_filter: set[str] | None = field(default=None)


def _parse_data_source(raw: Any) -> DataSourceConfig:
    """Parse a raw data_source value into a DataSourceConfig."""
    if isinstance(raw, DataSourceConfig):
        return raw

    if isinstance(raw, str):
        raw_lower = raw.strip().lower()
        if raw_lower == "staging" or raw_lower == "":
            return DataSourceConfig(type=DataSourceType.STAGING)
        if raw_lower in _KNOWN_TYPES:
            raise ConfigurationError(
                f"data_source type '{raw_lower}' requires a dict config "
                f"(e.g. {{type: {raw_lower}, ...}}), not a bare string",
                context={"data_source": raw},
            )
        return DataSourceConfig(type=DataSourceType.LOCAL, folder=raw.strip())

    if isinstance(raw, dict):
        return DataSourceConfig(**raw)

    raise ConfigurationError(
        f"Invalid data_source value: expected str, dict, or DataSourceConfig, got {type(raw).__name__}",
        context={"data_source": repr(raw)},
    )


def _resolve_staging(agent_folder: Path) -> DataSourceResolutionResult:
    """Resolve staging data source — just return the staging directory."""
    return DataSourceResolutionResult(directories=[agent_folder / "staging"])


def _validate_project_containment(folder: Path, project_root: Path) -> None:
    """Ensure *folder* is inside *project_root* (security check)."""
    try:
        folder.resolve().relative_to(project_root.resolve())
    except ValueError:
        raise FileSystemError(
            f"Local data source folder '{folder}' is outside the project root '{project_root}'",
            context={
                "folder": str(folder),
                "project_root": str(project_root),
                "operation": "resolve_local_data_source",
            },
        ) from None


def _resolve_local(config: DataSourceConfig, agent_folder: Path) -> DataSourceResolutionResult:
    """Resolve a local-folder data source."""
    if not config.folder:
        raise ConfigurationError(
            "Local data source requires a 'folder' field",
            context={
                "data_source": config.model_dump(exclude={"headers"}),
                "operation": "resolve_local_data_source",
            },
        )

    folder = Path(config.folder)
    if not folder.is_absolute():
        folder = agent_folder / folder

    project_root = find_project_root(str(agent_folder))
    if project_root is None:
        project_root = agent_folder.resolve().parent
    _validate_project_containment(folder, project_root)

    if not folder.exists():
        raise FileSystemError(
            f"Local data source folder does not exist: {folder}",
            context={"folder": str(folder), "operation": "resolve_local_data_source"},
        )

    file_type_filter = None
    if config.file_type:
        file_type_filter = {ft.strip().lower().lstrip(".") for ft in config.file_type}

    return DataSourceResolutionResult(
        directories=[folder],
        file_type_filter=file_type_filter,
    )


def _resolve_api(
    config: DataSourceConfig, agent_folder: Path, agent_name: str
) -> DataSourceResolutionResult:
    """Resolve an API data source -- fetch JSON and cache to disk.

    Responses are cached per (url, query, headers) fingerprint. Delete
    ``_remote_cache/api/`` inside agent_io to force a refresh.
    """
    if not config.url:
        raise ConfigurationError(
            "API data source requires a 'url' field",
            context={
                "data_source": config.model_dump(exclude={"headers"}),
                "operation": "resolve_api_data_source",
            },
        )

    parsed = urlparse(config.url)
    if parsed.scheme not in ("http", "https"):
        raise ConfigurationError(
            f"API data source URL must use http or https scheme, got '{parsed.scheme}'",
            context={"url": config.url, "operation": "resolve_api_data_source"},
        )

    if config.file_type and not all(
        ft.strip().lower().lstrip(".") == "json" for ft in config.file_type
    ):
        raise ConfigurationError(
            "API data source only supports JSON file type",
            context={
                "file_type": config.file_type,
                "operation": "resolve_api_data_source",
            },
        )

    fingerprint_input = config.url
    if config.query:
        fingerprint_input += json.dumps(config.query, sort_keys=True)
    if config.headers:
        fingerprint_input += json.dumps(config.headers, sort_keys=True)
    fingerprint = hashlib.sha256(fingerprint_input.encode()).hexdigest()[:12]

    cache_dir = agent_folder / _REMOTE_CACHE_DIR / "api" / fingerprint / "data"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_file = cache_dir / f"{agent_name}.json"

    if _holds_a_staging_document(cache_file):
        logger.info("Using cached API data: %s (from %s)", cache_file, config.url)
    else:
        _fetch_api_data(config, cache_file)

    return DataSourceResolutionResult(directories=[cache_dir])


def _as_staging_document(payload: Any) -> list[Any]:
    """Read an API response as the staging document the cache file must hold.

    The walk reads that file as a list of records. A response that is not a list
    is the single record it has always staged as — the reader cannot wrap a file
    the framework wrote.
    """
    return payload if isinstance(payload, list) else [payload]


def _holds_a_staging_document(cache_file: Path) -> bool:
    """Whether *cache_file* holds what a fetch writes; a file that does not is fetched again."""
    if cache_file.is_dir():
        # A fetch could not replace it, so refuse before spending a request.
        raise ConfigurationError(
            f"The API cache path {cache_file} is a directory. Remove it to fetch the data again.",
            context={"cache_file": str(cache_file), "operation": "resolve_api_cache"},
        )
    if not cache_file.is_file():
        return False
    try:
        cached = deep_json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("Cached API data at %s cannot be read, fetching it again: %s", cache_file, e)
        return False
    if not isinstance(cached, list):
        logger.warning(
            "Cached API data at %s holds a %s, not a list, fetching it again",
            cache_file,
            type(cached).__name__,
        )
        return False
    return True


def _fetch_api_data(config: DataSourceConfig, cache_file: Path) -> None:
    """Fetch JSON data from API endpoint and write to cache file."""
    try:
        import urllib.request
        from urllib.parse import urlencode

        url = config.url
        if config.query:
            url = f"{url}?{urlencode(config.query)}"
        req = urllib.request.Request(url)  # type: ignore[arg-type]
        if config.headers:
            for key, value in config.headers.items():
                req.add_header(key, value)

        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:  # nosec B310  # _resolve_api rejects non-http(s) schemes
            data = resp.read(_MAX_RESPONSE_BYTES + 1)
            if len(data) > _MAX_RESPONSE_BYTES:
                raise ConfigurationError(
                    f"API response exceeds {_MAX_RESPONSE_BYTES} byte limit",
                    context={"url": config.url, "operation": "fetch_api_data"},
                )

        parsed = deep_json.loads(data)

        atomic_json_write(cache_file, _as_staging_document(parsed), fsync=False)

        logger.info("Fetched and cached API data: %s -> %s", config.url, cache_file)

    except (json.JSONDecodeError, ValueError) as e:
        raise ConfigurationError(
            f"API response is not valid JSON: {e}",
            context={"url": config.url, "operation": "fetch_api_data"},
            cause=e,
        ) from e
    except Exception as e:
        if isinstance(e, ConfigurationError | FileSystemError):
            raise
        raise ConfigurationError(
            f"Failed to fetch API data source: {e}",
            context={"url": config.url, "operation": "fetch_api_data"},
            cause=e,
        ) from e


def _resolve_database(
    config: DataSourceConfig,
    agent_folder: Path,
    agent_name: str,
    project_root: Path | None,
    has_open_batch: Callable[[str], bool] | None = None,
) -> DataSourceResolutionResult:
    """Resolve a database data source -- read the query once and keep its rows on disk.

    A snapshot is kept per action, query, file count and connection settings (a
    ``${NAME}`` setting by its value, a credential by its name), so changing any
    of them reads again. ``agac run --refresh-input`` reads it again too. A change
    that would replace the snapshot while *has_open_batch* says the action's batch
    is open is refused: the batch answers the rows it was sent.
    """
    if not config.connection or not config.sql or not config.sql.strip():
        raise ConfigurationError(
            "Database data source requires a 'connection' and an 'sql' query",
            context={
                "data_source": config.model_dump(exclude={"headers"}),
                "operation": "resolve_database_data_source",
            },
        )
    refuse_a_statement_that_writes(config.sql)

    from agent_actions.connections import connection_settings, open_connection
    from agent_actions.connections.settings import settings_as_resolved

    root = project_root or find_project_root(str(agent_folder)) or agent_folder.resolve().parent
    settings = settings_as_resolved(connection_settings(config.connection, root))
    fingerprint = snapshot_fingerprint(config.connection, config.sql, settings, config.files)
    snapshot_dir = snapshot_directory(agent_folder, agent_name, fingerprint)
    if not snapshot_needs_reading(snapshot_dir):
        logger.info("Using the stored snapshot of '%s': %s", config.connection, snapshot_dir)
        return DataSourceResolutionResult(directories=[snapshot_dir])
    if (
        has_open_batch is not None
        and replaces_a_snapshot(snapshot_dir)
        and has_open_batch(agent_name)
    ):
        raise ConfigurationError(
            f"The database source of '{agent_name}' changed (its sql, files or connection "
            "settings), but a batch is still open for it, and reading the query again "
            "would forget the rows the batch is answering. Put the source back until the "
            "batch is collected, or run with --fresh to discard the batch",
            context={"action": agent_name, "connection": config.connection},
        )

    with open_connection(config.connection, root, read_only=True) as connector:
        snapshot_query(connector, config.sql, snapshot_dir, config.files)
    return DataSourceResolutionResult(directories=[snapshot_dir])


def is_api_data_source(data_source: Any) -> bool:
    """Whether *data_source* names an API, whose resolution may fetch over the network."""
    return bool(data_source) and _parse_data_source(data_source).type == DataSourceType.API


def resolve_start_node_data_source(
    agent_folder: Path,
    data_source: Any,
    agent_name: str,
    project_root: Path | None = None,
    has_open_batch: Callable[[str], bool] | None = None,
) -> DataSourceResolutionResult:
    """Resolve the data source for a start node.

    Single entry point for data source resolution. Falls back to
    ``agent_folder / "staging"`` when data_source is missing, empty, or None.
    *has_open_batch* tells whether an action's batch is still open; a database
    source refuses to replace its snapshot under one.
    """
    if not data_source:
        return _resolve_staging(agent_folder)

    config = _parse_data_source(data_source)

    if config.type == DataSourceType.STAGING:
        return _resolve_staging(agent_folder)

    if config.type == DataSourceType.LOCAL:
        return _resolve_local(config, agent_folder)

    if config.type == DataSourceType.API:
        return _resolve_api(config, agent_folder, agent_name)

    if config.type == DataSourceType.DATABASE:
        return _resolve_database(config, agent_folder, agent_name, project_root, has_open_batch)

    raise ConfigurationError(
        f"Unsupported data source type: {config.type}",
        context={"data_source": data_source, "agent_name": agent_name},
    )
