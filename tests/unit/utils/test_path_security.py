"""Tests for resolve_seed_path() in path_security module."""

import pytest

from agent_actions.utils.path_security import FILE_PREFIX, resolve_seed_path


class TestResolveSeedPath:
    """Tests for resolve_seed_path()."""

    def test_valid_file_reference_resolves(self, tmp_path):
        """A $file: prefixed reference resolves to the correct absolute path."""
        seed_dir = tmp_path / "seed_data"
        seed_dir.mkdir()
        (seed_dir / "data.json").write_text("{}")

        result = resolve_seed_path("$file:data.json", seed_dir)

        assert result == (seed_dir / "data.json").resolve()

    def test_reference_without_prefix_resolves(self, tmp_path):
        """A reference without $file: prefix resolves correctly."""
        seed_dir = tmp_path / "seed_data"
        seed_dir.mkdir()
        (seed_dir / "data.json").write_text("{}")

        result = resolve_seed_path("data.json", seed_dir)

        assert result == (seed_dir / "data.json").resolve()

    def test_empty_file_spec_raises_value_error(self, tmp_path):
        """Empty file_spec raises ValueError."""
        seed_dir = tmp_path / "seed_data"
        seed_dir.mkdir()

        with pytest.raises(ValueError, match="Empty file spec"):
            resolve_seed_path("", seed_dir)

    def test_path_traversal_raises_value_error(self, tmp_path):
        """Path traversal attempt (../../etc/passwd) raises ValueError."""
        seed_dir = tmp_path / "seed_data"
        seed_dir.mkdir()

        with pytest.raises(ValueError, match="Seed file path escapes base directory"):
            resolve_seed_path("../../etc/passwd", seed_dir)

    def test_path_traversal_with_prefix_raises(self, tmp_path):
        """Path traversal with $file: prefix also raises ValueError."""
        seed_dir = tmp_path / "seed_data"
        seed_dir.mkdir()

        with pytest.raises(ValueError, match="Seed file path escapes base directory"):
            resolve_seed_path("$file:../../etc/passwd", seed_dir)

    def test_empty_path_after_prefix_raises(self, tmp_path):
        """$file: prefix with no path after it raises ValueError."""
        seed_dir = tmp_path / "seed_data"
        seed_dir.mkdir()

        with pytest.raises(ValueError, match="Empty path after prefix"):
            resolve_seed_path("$file:", seed_dir)

    def test_subdirectory_path_resolves(self, tmp_path):
        """Subdirectory paths within base_dir resolve correctly."""
        seed_dir = tmp_path / "seed_data"
        sub = seed_dir / "subdir"
        sub.mkdir(parents=True)
        (sub / "nested.json").write_text("{}")

        result = resolve_seed_path("$file:subdir/nested.json", seed_dir)

        assert result == (sub / "nested.json").resolve()

    def test_file_prefix_constant(self):
        """FILE_PREFIX constant is set correctly."""
        assert FILE_PREFIX == "$file:"
