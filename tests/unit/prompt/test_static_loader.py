"""Unit tests for agent_actions.prompt.context.static_loader module.

Covers:
- StaticDataLoader.__init__ validation
- Loading JSON, YAML, text/markdown, CSV files
- Cache hit / miss behavior
- Path security: absolute paths, traversal attempts
- File not found, unsupported extension, file size limits
- The full load_static_data pipeline
- clear_cache and get_cache_stats
- $file: prefix parsing
"""

import json
from unittest.mock import patch

import pytest
import yaml

from agent_actions.prompt.context.static_loader import (
    StaticDataLoader,
    StaticDataLoadError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def data_dir(tmp_path):
    """Create a populated static data directory."""
    d = tmp_path / "static_data"
    d.mkdir()
    return d


@pytest.fixture()
def loader(data_dir):
    """StaticDataLoader pointed at `data_dir`."""
    return StaticDataLoader(data_dir)


# ---------------------------------------------------------------------------
# __init__ validation
# ---------------------------------------------------------------------------


class TestStaticDataLoaderInit:
    """Constructor validation tests."""

    def test_nonexistent_dir_raises(self, tmp_path):
        with pytest.raises(ValueError, match="does not exist"):
            StaticDataLoader(tmp_path / "no_such_dir")

    def test_file_instead_of_dir_raises(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hi")
        with pytest.raises(ValueError, match="not a directory"):
            StaticDataLoader(f)

    def test_valid_dir_succeeds(self, data_dir):
        loader = StaticDataLoader(data_dir)
        assert loader.static_data_dir == data_dir.resolve()


# ---------------------------------------------------------------------------
# _parse_file_path
# ---------------------------------------------------------------------------


class TestParseFilePath:
    """Tests for $file: prefix stripping."""

    def test_strips_file_prefix(self, loader):
        assert loader._parse_file_path("$file:data.json", "f") == "data.json"

    def test_returns_as_is_without_prefix(self, loader):
        assert loader._parse_file_path("data.json", "f") == "data.json"

    def test_prefix_only(self, loader):
        """$file: with nothing after it returns empty string."""
        assert loader._parse_file_path("$file:", "f") == ""


# ---------------------------------------------------------------------------
# _resolve_path -- absolute and traversal rejection
# ---------------------------------------------------------------------------


class TestResolvePath:
    """Security validation of resolved paths."""

    def test_absolute_path_rejected(self, loader):
        with pytest.raises(StaticDataLoadError, match="Absolute paths not allowed"):
            loader._resolve_path("/etc/passwd", "secret")

    def test_traversal_rejected(self, loader, data_dir):
        with pytest.raises(StaticDataLoadError, match="escapes static data directory"):
            loader._resolve_path("../../etc/passwd", "secret")

    def test_relative_path_resolved(self, loader, data_dir):
        # Create the file so resolution works
        (data_dir / "good.json").write_text("{}")
        result = loader._resolve_path("good.json", "f")
        assert result == (data_dir / "good.json").resolve()


# ---------------------------------------------------------------------------
# _load_file -- file-not-found, size limit, unsupported extension
# ---------------------------------------------------------------------------


class TestLoadFileErrors:
    """Error paths in _load_file."""

    def test_file_not_found_raises(self, loader, data_dir):
        missing = data_dir / "missing.json"
        with pytest.raises(StaticDataLoadError, match="File not found"):
            loader._load_file(missing, "f")

    def test_file_too_large_raises(self, loader, data_dir):
        big = data_dir / "huge.json"
        big.write_text("x" * 100)

        # Temporarily lower the limit
        original = StaticDataLoader.MAX_FILE_SIZE_BYTES
        try:
            StaticDataLoader.MAX_FILE_SIZE_BYTES = 10
            with pytest.raises(StaticDataLoadError, match="File too large"):
                loader._load_file(big, "f")
        finally:
            StaticDataLoader.MAX_FILE_SIZE_BYTES = original

    def test_unsupported_extension_raises(self, loader, data_dir):
        f = data_dir / "data.xyz"
        f.write_text("data")
        with pytest.raises(StaticDataLoadError, match="Unsupported file type"):
            loader._load_file(f, "f")


# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------


class TestLoadJson:
    """Tests for _load_json."""

    def test_valid_json_loaded(self, loader, data_dir):
        f = data_dir / "data.json"
        payload = {"key": "value", "nums": [1, 2, 3]}
        f.write_text(json.dumps(payload))

        result = loader._load_json(f, "field")
        assert result == payload

    def test_invalid_json_raises(self, loader, data_dir):
        f = data_dir / "bad.json"
        f.write_text("{bad json")
        with pytest.raises(StaticDataLoadError, match="Invalid JSON format"):
            loader._load_json(f, "field")


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


class TestLoadYaml:
    """Tests for _load_yaml."""

    def test_valid_yaml_loaded(self, loader, data_dir):
        f = data_dir / "data.yml"
        payload = {"key": "value", "nested": {"a": 1}}
        f.write_text(yaml.dump(payload))

        result = loader._load_yaml(f, "field")
        assert result == payload

    def test_yaml_extension_variant(self, loader, data_dir):
        """Both .yml and .yaml should work via _load_file dispatch."""
        f = data_dir / "data.yaml"
        f.write_text("items:\n  - one\n  - two\n")
        result = loader._load_file(f, "field")
        assert result == {"items": ["one", "two"]}

    def test_invalid_yaml_raises(self, loader, data_dir):
        f = data_dir / "bad.yml"
        f.write_text("key: :\n  [bad")
        with pytest.raises(StaticDataLoadError, match="Invalid YAML format"):
            loader._load_yaml(f, "field")


# ---------------------------------------------------------------------------
# Text / Markdown loading
# ---------------------------------------------------------------------------


class TestLoadText:
    """Tests for _load_text."""

    def test_txt_file_loaded(self, loader, data_dir):
        f = data_dir / "notes.txt"
        f.write_text("Hello world")
        result = loader._load_text(f, "field")
        assert result == "Hello world"

    def test_md_file_loaded(self, loader, data_dir):
        """Markdown files use _load_text path."""
        f = data_dir / "readme.md"
        f.write_text("# Title\nSome content")
        result = loader._load_file(f, "field")
        assert "# Title" in result


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------


class TestLoadCsv:
    """Tests for _load_csv."""

    def test_valid_csv_loaded(self, loader, data_dir):
        f = data_dir / "data.csv"
        f.write_text("name,age\nAlice,30\nBob,25\n")
        result = loader._load_csv(f, "field")

        assert len(result) == 2
        assert result[0]["name"] == "Alice"
        assert result[1]["age"] == "25"

    def test_empty_csv_returns_empty_list(self, loader, data_dir):
        """CSV with only headers returns empty list."""
        f = data_dir / "empty.csv"
        f.write_text("name,age\n")
        result = loader._load_csv(f, "field")
        assert result == []


# ---------------------------------------------------------------------------
# load_static_data -- full pipeline
# ---------------------------------------------------------------------------


class TestLoadStaticData:
    """Integration-style tests for the full pipeline."""

    @patch("agent_actions.prompt.context.static_loader.fire_event")
    def test_empty_config_returns_empty(self, mock_fire, loader):
        result = loader.load_static_data({})
        assert result == {}

    @patch("agent_actions.prompt.context.static_loader.fire_event")
    def test_loads_single_json_field(self, mock_fire, loader, data_dir):
        f = data_dir / "items.json"
        f.write_text(json.dumps(["a", "b"]))

        result = loader.load_static_data({"my_items": "items.json"})
        assert result["my_items"] == ["a", "b"]

    @patch("agent_actions.prompt.context.static_loader.fire_event")
    def test_loads_with_file_prefix(self, mock_fire, loader, data_dir):
        f = data_dir / "items.json"
        f.write_text(json.dumps({"key": 1}))

        result = loader.load_static_data({"field": "$file:items.json"})
        assert result["field"] == {"key": 1}

    @patch("agent_actions.prompt.context.static_loader.fire_event")
    def test_loads_multiple_fields(self, mock_fire, loader, data_dir):
        (data_dir / "a.json").write_text(json.dumps({"a": 1}))
        (data_dir / "b.txt").write_text("text content")

        result = loader.load_static_data({"fa": "a.json", "fb": "b.txt"})
        assert result["fa"] == {"a": 1}
        assert result["fb"] == "text content"

    @patch("agent_actions.prompt.context.static_loader.fire_event")
    def test_missing_file_raises(self, mock_fire, loader):
        with pytest.raises(StaticDataLoadError, match="File not found"):
            loader.load_static_data({"f": "no_such.json"})

    @patch("agent_actions.prompt.context.static_loader.fire_event")
    def test_unexpected_error_wrapped(self, mock_fire, loader, data_dir):
        """Unexpected exceptions are wrapped in StaticDataLoadError."""
        # Cause an unexpected error by patching _parse_file_path to raise something odd
        with patch.object(loader, "_parse_file_path", side_effect=TypeError("weird")):
            with pytest.raises(StaticDataLoadError, match="Failed to load"):
                loader.load_static_data({"f": "data.json"})

    @patch("agent_actions.prompt.context.static_loader.fire_event")
    def test_static_data_load_error_reraised_as_is(self, mock_fire, loader):
        """StaticDataLoadError from sub-methods should not be double-wrapped."""
        with pytest.raises(StaticDataLoadError, match="Absolute paths not allowed"):
            loader.load_static_data({"f": "/etc/passwd"})


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestCaching:
    """Tests for cache hit/miss/clear behavior."""

    @patch("agent_actions.prompt.context.static_loader.fire_event")
    def test_second_load_hits_cache(self, mock_fire, loader, data_dir):
        f = data_dir / "cached.json"
        f.write_text(json.dumps({"v": 1}))

        # First load -- cache miss
        r1 = loader.load_static_data({"f": "cached.json"})
        # Second load -- cache hit (same loader instance)
        r2 = loader.load_static_data({"f": "cached.json"})

        assert r1 == r2
        # Check that CacheHitEvent was fired on the second call
        event_types = [type(call.args[0]).__name__ for call in mock_fire.call_args_list]
        assert "CacheMissEvent" in event_types
        assert "CacheHitEvent" in event_types

    @patch("agent_actions.prompt.context.static_loader.fire_event")
    def test_clear_cache_empties_cache(self, mock_fire, loader, data_dir):
        f = data_dir / "cached.json"
        f.write_text(json.dumps({"v": 1}))

        loader.load_static_data({"f": "cached.json"})
        assert loader._cache  # cache is populated

        loader.clear_cache()
        assert loader._cache == {}

    @patch("agent_actions.prompt.context.static_loader.fire_event")
    def test_clear_cache_fires_invalidation_event(self, mock_fire, loader, data_dir):
        f = data_dir / "cached.json"
        f.write_text(json.dumps({"v": 1}))
        loader.load_static_data({"f": "cached.json"})
        mock_fire.reset_mock()

        loader.clear_cache()

        event_types = [type(call.args[0]).__name__ for call in mock_fire.call_args_list]
        assert "CacheInvalidationEvent" in event_types


# ---------------------------------------------------------------------------
# get_cache_stats
# ---------------------------------------------------------------------------


class TestGetCacheStats:
    """Tests for debugging statistics."""

    @patch("agent_actions.prompt.context.static_loader.fire_event")
    def test_empty_cache_stats(self, mock_fire, loader):
        stats = loader.get_cache_stats()
        assert stats["cached_files"] == 0
        assert stats["cached_file_paths"] == []

    @patch("agent_actions.prompt.context.static_loader.fire_event")
    def test_populated_cache_stats(self, mock_fire, loader, data_dir):
        f = data_dir / "a.json"
        f.write_text(json.dumps([1, 2]))
        loader.load_static_data({"a": "a.json"})

        stats = loader.get_cache_stats()
        assert stats["cached_files"] == 1
        assert len(stats["cached_file_paths"]) == 1
        assert "total_size_bytes" in stats
        assert "total_size_mb" in stats
