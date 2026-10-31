"""Tests for resolve_seed_path() in path_security module."""

import pytest

from agent_actions.utils.path_security import FILE_PREFIX, resolve_seed_path


class TestResolveSeedPath:
    """Tests for resolve_seed_path()."""

    @pytest.mark.parametrize(
        ("spec", "relative"),
        [
            pytest.param("$file:data.json", "data.json", id="prefixed"),
            pytest.param("data.json", "data.json", id="bare"),
            pytest.param("$file:subdir/nested.json", "subdir/nested.json", id="subdirectory"),
        ],
    )
    def test_reference_inside_base_dir_resolves(self, tmp_path, spec, relative):
        seed_dir = tmp_path / "seed_data"
        target = seed_dir / relative
        target.parent.mkdir(parents=True)
        target.write_text("{}")

        assert resolve_seed_path(spec, seed_dir) == target.resolve()

    @pytest.mark.parametrize(
        ("spec", "match"),
        [
            pytest.param("", "Empty file spec", id="empty"),
            pytest.param(
                "../../etc/passwd", "Seed file path escapes base directory", id="traversal"
            ),
            pytest.param(
                "$file:../../etc/passwd",
                "Seed file path escapes base directory",
                id="traversal-prefixed",
            ),
            pytest.param("$file:", "Empty path after prefix", id="empty-after-prefix"),
        ],
    )
    def test_bad_spec_raises_value_error(self, tmp_path, spec, match):
        seed_dir = tmp_path / "seed_data"
        seed_dir.mkdir()

        with pytest.raises(ValueError, match=match):
            resolve_seed_path(spec, seed_dir)

    def test_file_prefix_constant(self):
        """FILE_PREFIX constant is set correctly."""
        assert FILE_PREFIX == "$file:"
