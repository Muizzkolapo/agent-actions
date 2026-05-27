"""Tests for BatchDataLoader path traversal protection and data loading."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_actions.llm.batch.infrastructure.batch_data_loader import BatchDataLoader


class TestBatchDataLoaderPathTraversal:
    """Tests for path containment enforcement in load_data."""

    def test_valid_json_inside_allowed_root(self, tmp_path: Path) -> None:
        """File inside allowed_root loads successfully."""
        f = tmp_path / "data.json"
        f.write_text(json.dumps([{"key": "value"}]))
        loader = BatchDataLoader()
        result = loader.load_data(str(f), allowed_root=tmp_path)
        assert result == [{"key": "value"}]

    def test_valid_jsonl_inside_allowed_root(self, tmp_path: Path) -> None:
        """JSONL file inside allowed_root loads successfully."""
        f = tmp_path / "data.jsonl"
        f.write_text('{"a": 1}\n{"b": 2}\n')
        loader = BatchDataLoader()
        result = loader.load_data(str(f), allowed_root=tmp_path)
        assert result == [{"a": 1}, {"b": 2}]

    def test_rejects_parent_traversal(self, tmp_path: Path) -> None:
        """Path with .. escaping allowed_root is rejected."""
        safe = tmp_path / "safe"
        safe.mkdir()
        evil_path = str(safe / ".." / ".." / "etc" / "passwd.json")
        loader = BatchDataLoader()
        with pytest.raises(ValueError, match="Path escapes containment"):
            loader.load_data(evil_path, allowed_root=safe)

    def test_rejects_absolute_path_outside_root(self, tmp_path: Path) -> None:
        """Absolute path outside allowed_root is rejected."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        f = outside / "data.json"
        f.write_text(json.dumps([{"x": 1}]))
        loader = BatchDataLoader()
        with pytest.raises(ValueError, match="Path escapes containment"):
            loader.load_data(str(f), allowed_root=allowed)

    def test_rejects_symlink_traversal(self, tmp_path: Path) -> None:
        """Symlink pointing outside allowed_root is rejected."""
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.json"
        secret.write_text(json.dumps([{"stolen": True}]))

        safe = tmp_path / "safe"
        safe.mkdir()
        link = safe / "escape.json"
        link.symlink_to(secret)

        loader = BatchDataLoader()
        with pytest.raises(ValueError, match="Path escapes containment"):
            loader.load_data(str(link), allowed_root=safe)

    def test_allowed_root_none_skips_check(self, tmp_path: Path) -> None:
        """When allowed_root is None, no containment check is performed."""
        f = tmp_path / "data.json"
        f.write_text(json.dumps([{"ok": True}]))
        loader = BatchDataLoader()
        result = loader.load_data(str(f), allowed_root=None)
        assert result == [{"ok": True}]

    def test_allowed_root_not_passed_skips_check(self, tmp_path: Path) -> None:
        """Omitting allowed_root disables containment enforcement."""
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"single": "object"}))
        loader = BatchDataLoader()
        result = loader.load_data(str(f))
        assert result == [{"single": "object"}]

    def test_nested_subdirectory_inside_root(self, tmp_path: Path) -> None:
        """Deeply nested file inside allowed_root loads fine."""
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        f = nested / "deep.json"
        f.write_text(json.dumps([{"deep": True}]))
        loader = BatchDataLoader()
        result = loader.load_data(str(f), allowed_root=tmp_path)
        assert result == [{"deep": True}]

    def test_sibling_directory_rejected(self, tmp_path: Path) -> None:
        """File in a sibling directory with shared prefix is rejected.

        Validates that is_relative_to is used (not str.startswith),
        so /safe_extra does not pass a check for /safe.
        """
        safe = tmp_path / "safe"
        safe.mkdir()
        safe_extra = tmp_path / "safe_extra"
        safe_extra.mkdir()
        f = safe_extra / "data.json"
        f.write_text(json.dumps([{"sneaky": True}]))
        loader = BatchDataLoader()
        with pytest.raises(ValueError, match="Path escapes containment"):
            loader.load_data(str(f), allowed_root=safe)


class TestBatchDataLoaderAsync:
    """Tests for async path with allowed_root forwarding."""

    async def test_async_loads_valid_file(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text(json.dumps([{"async": True}]))
        loader = BatchDataLoader()
        result = await loader.load_data_async(str(f), allowed_root=tmp_path)
        assert result == [{"async": True}]

    async def test_async_rejects_traversal(self, tmp_path: Path) -> None:
        """load_data_async forwards allowed_root, so traversal is rejected."""
        safe = tmp_path / "safe"
        safe.mkdir()
        evil_path = str(safe / ".." / ".." / "etc" / "passwd.json")
        loader = BatchDataLoader()
        with pytest.raises(ValueError, match="Path escapes containment"):
            await loader.load_data_async(evil_path, allowed_root=safe)


class TestBatchDataLoaderParsing:
    """Tests for JSON and JSONL parsing behavior."""

    def test_unsupported_extension_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("a,b,c")
        loader = BatchDataLoader()
        with pytest.raises(ValueError, match="Unsupported file type"):
            loader.load_data(str(f))

    def test_json_single_object_wrapped_in_list(self, tmp_path: Path) -> None:
        """A single JSON object (not array) is wrapped in a list."""
        f = tmp_path / "single.json"
        f.write_text(json.dumps({"one": 1}))
        loader = BatchDataLoader()
        result = loader.load_data(str(f))
        assert result == [{"one": 1}]

    def test_json_array_returned_directly(self, tmp_path: Path) -> None:
        f = tmp_path / "array.json"
        f.write_text(json.dumps([{"a": 1}, {"b": 2}]))
        loader = BatchDataLoader()
        result = loader.load_data(str(f))
        assert result == [{"a": 1}, {"b": 2}]

    def test_jsonl_skips_blank_lines(self, tmp_path: Path) -> None:
        f = tmp_path / "data.jsonl"
        f.write_text('{"a": 1}\n\n{"b": 2}\n  \n')
        loader = BatchDataLoader()
        result = loader.load_data(str(f))
        assert result == [{"a": 1}, {"b": 2}]

    def test_invalid_json_raises_value_error(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("{not valid json")
        loader = BatchDataLoader()
        with pytest.raises(ValueError, match="Error decoding JSON"):
            loader.load_data(str(f))
