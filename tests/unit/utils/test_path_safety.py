"""Tests for path safety utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.utils.path_safety import assert_path_contained, sanitize_path_component


class TestAssertPathContained:
    """Tests for assert_path_contained."""

    def test_valid_child_path(self, tmp_path: Path) -> None:
        child = tmp_path / "subdir" / "file.json"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.touch()
        result = assert_path_contained(child, tmp_path)
        assert result == child.resolve()

    def test_rejects_parent_traversal(self, tmp_path: Path) -> None:
        child = tmp_path / ".." / ".." / "etc" / "passwd"
        with pytest.raises(ValueError, match="Path escapes containment"):
            assert_path_contained(child, tmp_path)

    def test_rejects_dot_slash_traversal(self, tmp_path: Path) -> None:
        child = tmp_path / "foo" / "." / ".." / ".." / "bar"
        with pytest.raises(ValueError, match="Path escapes containment"):
            assert_path_contained(child, tmp_path)

    def test_accepts_nested_subdirectory(self, tmp_path: Path) -> None:
        child = tmp_path / "a" / "b" / "c" / "file.json"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.touch()
        result = assert_path_contained(child, tmp_path)
        assert result.is_relative_to(tmp_path.resolve())

    def test_rejects_symlink_traversal(self, tmp_path: Path) -> None:
        """Symlink pointing outside parent must be rejected."""
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.touch()

        inside = tmp_path / "safe"
        inside.mkdir()
        link = inside / "escape"
        link.symlink_to(outside)

        child = link / "secret.txt"
        with pytest.raises(ValueError, match="Path escapes containment"):
            assert_path_contained(child, inside)

    def test_same_directory(self, tmp_path: Path) -> None:
        """Child equal to parent should be accepted."""
        result = assert_path_contained(tmp_path, tmp_path)
        assert result == tmp_path.resolve()


class TestSanitizePathComponent:
    """Tests for sanitize_path_component."""

    def test_short_name_unchanged(self) -> None:
        assert sanitize_path_component("my_action") == "my_action"

    def test_replaces_slashes(self) -> None:
        assert sanitize_path_component("foo/bar\\baz") == "foo_bar_baz"

    def test_replaces_null_bytes(self) -> None:
        assert sanitize_path_component("foo\0bar") == "foo_bar"

    def test_long_name_truncated_with_hash(self) -> None:
        long_name = "a" * 300
        result = sanitize_path_component(long_name)
        encoded = result.encode("utf-8")
        # 200 truncated + 1 underscore + 8 hex chars = 209 max
        assert len(encoded) <= 209
        # Must end with _<8 hex chars>
        assert result[-9] == "_"
        assert len(result[-8:]) == 8
        # Hash is hex
        int(result[-8:], 16)

    def test_deterministic(self) -> None:
        name = "x" * 300
        assert sanitize_path_component(name) == sanitize_path_component(name)

    def test_different_long_names_different_results(self) -> None:
        """Two long names sharing a prefix produce different sanitized names."""
        name_a = "a" * 250 + "_suffix_a"
        name_b = "a" * 250 + "_suffix_b"
        assert sanitize_path_component(name_a) != sanitize_path_component(name_b)

    def test_exact_boundary(self) -> None:
        """Name exactly at max_bytes is not truncated."""
        name = "b" * 200
        result = sanitize_path_component(name)
        assert result == name  # no hash appended

    def test_one_over_boundary(self) -> None:
        """Name one byte over max_bytes IS truncated with hash."""
        name = "c" * 201
        result = sanitize_path_component(name)
        assert len(result.encode("utf-8")) <= 209
        assert "_" in result[-9:]
