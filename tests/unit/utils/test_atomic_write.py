"""Tests for atomic_json_write utility."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.utils.atomic_write import atomic_json_write


class TestAtomicJsonWrite:
    """Core behavior of atomic_json_write."""

    def test_writes_valid_json(self, tmp_path):
        """Happy path: data is written and readable."""
        target = tmp_path / "out.json"
        atomic_json_write(target, {"key": "value"}, ensure_ascii=False)

        assert target.exists()
        assert json.loads(target.read_text()) == {"key": "value"}

    def test_no_leftover_temp_file(self, tmp_path):
        """Temp file is removed after successful write."""
        target = tmp_path / "out.json"
        atomic_json_write(target, {"a": 1})
        assert not target.with_suffix(".json.tmp").exists()

    def test_json_kwargs_forwarded(self, tmp_path):
        """indent and other json.dump kwargs are respected."""
        target = tmp_path / "out.json"
        atomic_json_write(target, {"a": 1}, indent=2, ensure_ascii=False)
        content = target.read_text()
        assert "  " in content  # indented

    def test_overwrite_replaces_content(self, tmp_path):
        """Second write replaces first."""
        target = tmp_path / "out.json"
        atomic_json_write(target, {"v": 1})
        atomic_json_write(target, {"v": 2})
        assert json.loads(target.read_text()) == {"v": 2}

    def test_first_write_creates_file(self, tmp_path):
        """Works when target doesn't exist yet (Path.replace handles this)."""
        target = tmp_path / "subdir" / "out.json"
        target.parent.mkdir(parents=True)
        atomic_json_write(target, {"new": True})
        assert json.loads(target.read_text()) == {"new": True}


class TestAtomicJsonWriteAtomicity:
    """Verify the temp-then-rename mechanism."""

    def test_temp_file_observed_before_rename(self, tmp_path):
        """Spy on Path.replace to confirm temp file has valid data before rename."""
        target = tmp_path / "out.json"
        captured = {}
        original_replace = Path.replace

        def spy(self_path, dest):
            captured["tmp_path"] = self_path
            captured["tmp_content"] = json.loads(self_path.read_text())
            return original_replace(self_path, dest)

        with patch.object(Path, "replace", spy):
            atomic_json_write(target, {"spied": True}, ensure_ascii=False)

        assert str(captured["tmp_path"]).endswith(".json.tmp")
        assert captured["tmp_content"] == {"spied": True}

    def test_original_survives_write_failure(self, tmp_path):
        """If json.dump fails, the original file is untouched."""
        target = tmp_path / "out.json"
        atomic_json_write(target, {"v": 1})
        original = target.read_text()

        with patch(
            "agent_actions.utils.atomic_write.json.dump",
            side_effect=OSError("disk full"),
        ):
            with pytest.raises(OSError):
                atomic_json_write(target, {"v": 2})

        assert target.read_text() == original

    def test_original_survives_rename_failure(self, tmp_path):
        """If rename fails after successful write, original is untouched."""
        target = tmp_path / "out.json"
        atomic_json_write(target, {"v": 1})
        original = target.read_text()

        with (
            patch.object(Path, "replace", side_effect=OSError("cross-device")),
            pytest.raises(OSError),
        ):
            atomic_json_write(target, {"v": 2})

        assert target.read_text() == original
        assert not target.with_suffix(".json.tmp").exists()


class TestAtomicJsonWriteErrorHandling:
    """Error wrapping and cleanup."""

    def test_raises_oserror_on_failure(self, tmp_path):
        """Write failures are wrapped in OSError with path context."""
        target = tmp_path / "out.json"
        with patch(
            "agent_actions.utils.atomic_write.json.dump",
            side_effect=ValueError("bad"),
        ):
            with pytest.raises(OSError, match="Failed to write"):
                atomic_json_write(target, {})

    def test_exception_chain_preserved(self, tmp_path):
        """Original exception is chained via 'from'."""
        target = tmp_path / "out.json"
        with patch(
            "agent_actions.utils.atomic_write.json.dump",
            side_effect=ValueError("root cause"),
        ):
            with pytest.raises(OSError) as exc_info:
                atomic_json_write(target, {})
            assert isinstance(exc_info.value.__cause__, ValueError)
            assert "root cause" in str(exc_info.value.__cause__)

    def test_temp_file_cleaned_on_error(self, tmp_path):
        """No .tmp litter after failure."""
        target = tmp_path / "out.json"
        with patch(
            "agent_actions.utils.atomic_write.json.dump",
            side_effect=OSError("fail"),
        ):
            with pytest.raises(OSError):
                atomic_json_write(target, {})

        assert list(tmp_path.glob("*.tmp")) == []

    def test_fsync_disabled(self, tmp_path):
        """fsync=False skips the fsync call (for non-critical data)."""
        target = tmp_path / "out.json"
        with patch("agent_actions.utils.atomic_write.os.fsync") as mock_fsync:
            atomic_json_write(target, {"fast": True}, fsync=False)
        mock_fsync.assert_not_called()
        assert json.loads(target.read_text()) == {"fast": True}
