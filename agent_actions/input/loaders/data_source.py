"""Data source resolver for start-node input directories."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from agent_actions.config.defaults import ApiDefaults
from agent_actions.errors import ConfigurationError, FileSystemError
from agent_actions.utils.atomic_write import atomic_json_write
from agent_actions.utils.project_root import find_project_root


class DataSourceType(str, Enum):
    """Type of data source for start-node input."""

    STAGING = "staging"
    LOCAL = "local"
    API = "api"


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

    model_config = ConfigDict(extra="forbid")


logger = logging.getLogger(__name__)

# Safety limits for API fetches
_MAX_RESPONSE_BYTES = ApiDefaults.MAX_RESPONSE_BYTES
_REQUEST_TIMEOUT_SECONDS = ApiDefaults.REQUEST_TIMEOUT_SECONDS
_REMOTE_CACHE_DIR = "_remote_cache"

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

    if not cache_file.exists():
        _fetch_api_data(config, cache_file)
    else:
        logger.info("Using cached API data: %s (from %s)", cache_file, config.url)

    return DataSourceResolutionResult(directories=[cache_dir])


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

        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            data = resp.read(_MAX_RESPONSE_BYTES + 1)
            if len(data) > _MAX_RESPONSE_BYTES:
                raise ConfigurationError(
                    f"API response exceeds {_MAX_RESPONSE_BYTES} byte limit",
                    context={"url": config.url, "operation": "fetch_api_data"},
                )

        parsed = json.loads(data)

        atomic_json_write(cache_file, parsed)

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


def resolve_start_node_data_source(
    agent_folder: Path,
    data_source: Any,
    agent_name: str,
) -> DataSourceResolutionResult:
    """Resolve the data source for a start node.

    Single entry point for data source resolution. Falls back to
    ``agent_folder / "staging"`` when data_source is missing, empty, or None.
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

    raise ConfigurationError(
        f"Unsupported data source type: {config.type}",
        context={"data_source": data_source, "agent_name": agent_name},
    )
