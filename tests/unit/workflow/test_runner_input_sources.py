"""Tests for start-node data source resolution.

Covers resolve_start_node_data_source() with all source types,
default behavior, string shorthand, and security constraints.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.errors import ConfigurationError, FileSystemError
from agent_actions.input.loaders.data_source import resolve_start_node_data_source

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_folder(tmp_path: Path) -> Path:
    """Create a minimal agent_io folder structure."""
    agent_folder = tmp_path / "project" / "agent_io"
    (agent_folder / "staging").mkdir(parents=True)
    return agent_folder


# ---------------------------------------------------------------------------
# Staging (default)
# ---------------------------------------------------------------------------


class TestStagingDataSource:
    def test_missing_data_source_defaults_to_staging(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)
        result = resolve_start_node_data_source(agent_folder, None, "start")
        assert len(result.directories) == 1
        assert result.directories[0] == agent_folder / "staging"
        assert result.file_type_filter is None

    def test_empty_string_defaults_to_staging(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)
        result = resolve_start_node_data_source(agent_folder, "", "start")
        assert result.directories[0] == agent_folder / "staging"

    def test_string_shorthand_staging(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)
        result = resolve_start_node_data_source(agent_folder, "staging", "start")
        assert result.directories[0] == agent_folder / "staging"


# ---------------------------------------------------------------------------
# Local folder
# ---------------------------------------------------------------------------


class TestLocalDataSource:
    def test_local_folder_resolved(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)
        data_dir = tmp_path / "project" / "my_data"
        data_dir.mkdir(parents=True)

        result = resolve_start_node_data_source(
            agent_folder,
            {"type": "local", "folder": str(data_dir)},
            "start",
        )
        assert result.directories[0] == data_dir

    def test_local_folder_with_file_type_filter(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)
        data_dir = tmp_path / "project" / "my_data"
        data_dir.mkdir(parents=True)

        result = resolve_start_node_data_source(
            agent_folder,
            {
                "type": "local",
                "folder": str(data_dir),
                "file_type": [".json", "CSV"],
            },
            "start",
        )
        assert result.file_type_filter == {"json", "csv"}

    def test_local_missing_folder_raises(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)
        missing = tmp_path / "project" / "does_not_exist"

        with pytest.raises(FileSystemError, match="does not exist"):
            resolve_start_node_data_source(
                agent_folder,
                {"type": "local", "folder": str(missing)},
                "start",
            )

    def test_local_requires_project_root_containment(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)
        # Use a second tmp_path-scoped directory to avoid creating persistent /tmp artifacts
        outside = tmp_path / "unrelated_project" / "data"
        outside.mkdir(parents=True)

        with pytest.raises(FileSystemError, match="outside the project root"):
            resolve_start_node_data_source(
                agent_folder,
                {"type": "local", "folder": str(outside)},
                "start",
            )

    def test_bare_local_string_raises_helpful_error(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)

        with pytest.raises(ConfigurationError, match="requires a dict config"):
            resolve_start_node_data_source(agent_folder, "local", "start")

    def test_bare_api_string_raises_helpful_error(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)

        with pytest.raises(ConfigurationError, match="requires a dict config"):
            resolve_start_node_data_source(agent_folder, "api", "start")

    def test_string_shorthand_local(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)
        data_dir = tmp_path / "project" / "my_data"
        data_dir.mkdir(parents=True)

        result = resolve_start_node_data_source(
            agent_folder,
            str(data_dir),
            "start",
        )
        assert result.directories[0] == data_dir


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


class TestAPIDataSource:
    def test_api_writes_json_cache(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)
        sample_data = [{"id": 1, "name": "test"}]

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(sample_data).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = resolve_start_node_data_source(
                agent_folder,
                {"type": "api", "url": "https://example.com/data.json"},
                "fetcher",
            )

        assert len(result.directories) == 1
        cache_dir = result.directories[0]
        cache_file = cache_dir / "fetcher.json"
        assert cache_file.exists()
        assert json.loads(cache_file.read_text()) == sample_data

    def test_api_cache_reuse_skips_fetch(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)
        sample_data = [{"id": 1}]

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(sample_data).encode()
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        ds = {"type": "api", "url": "https://example.com/data.json"}

        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            resolve_start_node_data_source(agent_folder, ds, "fetcher")
            assert mock_urlopen.call_count == 1

            # Second call should reuse cache — no new fetch
            resolve_start_node_data_source(agent_folder, ds, "fetcher")
            assert mock_urlopen.call_count == 1

    def test_api_rejects_non_http_scheme(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)

        with pytest.raises(ConfigurationError, match="http or https"):
            resolve_start_node_data_source(
                agent_folder,
                {"type": "api", "url": "ftp://example.com/data"},
                "start",
            )

    def test_api_rejects_non_json_file_type(self, tmp_path):
        agent_folder = _make_agent_folder(tmp_path)

        with pytest.raises(ConfigurationError, match="only supports JSON"):
            resolve_start_node_data_source(
                agent_folder,
                {
                    "type": "api",
                    "url": "https://example.com/data",
                    "file_type": ["csv"],
                },
                "start",
            )
