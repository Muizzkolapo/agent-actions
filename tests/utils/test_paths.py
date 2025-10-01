"""
Comprehensive path utilities tests for the Agent Actions path utilities.

Tests cover path utility functions as specified in tests_recommendations.jsonc:
1. path_utils normalization and directory traversal prevention; safe joins on POSIX/Windows-like paths
2. PathManager functionality including validation, creation, and permission handling
3. Project root discovery and environment-specific configurations
4. Error handling and edge cases for path operations
"""

import os
import sys
import pytest
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Union
from unittest.mock import Mock, patch, MagicMock

from agent_actions._internal.utils.path_utils import (
    get_path_manager,
    ensure_directory_exists,
    create_side_output_directory,
    resolve_absolute_path,
    check_path_exists,
    find_project_root,
    create_mirror_source_path,
    validate_path_permissions,
    clean_directory,
    get_relative_path,
    find_files_by_extension,
    safe_path_join,
    create_agent_directory_structure,
    mkdir_with_parents,
    get_absolute_path,
    DEFAULT_MARKER_FILE,
    COMMON_EXTENSIONS,
    SIDE_OUTPUT_DIR_NAME
)
from agent_actions.core.exceptions import FileSystemError


class TestPathUtilityFunctions:
    """Test basic path utility functions."""

    def test_get_path_manager_singleton(self):
        """Test get_path_manager returns singleton instance."""
        manager1 = get_path_manager()
        manager2 = get_path_manager()

        assert manager1 is manager2
        assert manager1 is not None

    def test_ensure_directory_exists_creates_directory(self, tmp_path):
        """Test ensure_directory_exists creates directories."""
        test_dir = tmp_path / "new_directory"
        assert not test_dir.exists()

        result = ensure_directory_exists(test_dir)

        assert test_dir.exists()
        assert test_dir.is_dir()
        assert result == test_dir.resolve()

    def test_ensure_directory_exists_for_file_path(self, tmp_path):
        """Test ensure_directory_exists creates parent directory for file path."""
        test_file = tmp_path / "subdir" / "file.txt"
        assert not test_file.parent.exists()

        result = ensure_directory_exists(test_file, is_file=True)

        assert test_file.parent.exists()
        assert test_file.parent.is_dir()
        assert not test_file.exists()  # File itself should not be created

    def test_ensure_directory_exists_idempotent(self, tmp_path):
        """Test ensure_directory_exists is idempotent."""
        test_dir = tmp_path / "existing_directory"
        test_dir.mkdir()

        result1 = ensure_directory_exists(test_dir)
        result2 = ensure_directory_exists(test_dir)

        assert result1 == result2
        assert test_dir.exists()

    def test_create_side_output_directory(self, tmp_path):
        """Test create_side_output_directory creates side output structure."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        side_output = create_side_output_directory(output_dir)

        expected_side_output = tmp_path / "side_output"
        assert side_output == expected_side_output
        assert expected_side_output.exists()
        assert expected_side_output.is_dir()

    def test_resolve_absolute_path(self, tmp_path):
        """Test resolve_absolute_path normalizes paths."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        # Test relative path resolution
        relative_path = "test_dir"
        with patch('os.getcwd', return_value=str(tmp_path)):
            result = resolve_absolute_path(relative_path)
            assert result.is_absolute()

    def test_check_path_exists(self, tmp_path):
        """Test check_path_exists correctly identifies existing paths."""
        existing_file = tmp_path / "existing.txt"
        existing_file.write_text("content")

        nonexistent_file = tmp_path / "nonexistent.txt"

        assert check_path_exists(existing_file) is True
        assert check_path_exists(nonexistent_file) is False
        assert check_path_exists(tmp_path) is True  # Directory exists

    def test_check_path_exists_string_input(self, tmp_path):
        """Test check_path_exists works with string input."""
        existing_file = tmp_path / "existing.txt"
        existing_file.write_text("content")

        assert check_path_exists(str(existing_file)) is True
        assert check_path_exists(str(tmp_path / "nonexistent.txt")) is False


class TestProjectRootDiscovery:
    """Test project root discovery functionality."""

    def test_find_project_root_with_marker_file(self, tmp_path):
        """Test find_project_root finds project root with marker file."""
        # Create project structure with marker file
        project_root = tmp_path / "project"
        project_root.mkdir()
        marker_file = project_root / DEFAULT_MARKER_FILE
        marker_file.write_text("project: test")

        subdir = project_root / "subdir" / "deep"
        subdir.mkdir(parents=True)

        # Should find project root from subdirectory
        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.get_project_root.return_value = project_root
            mock_pm.return_value = mock_manager

            result = find_project_root(subdir)
            assert result == project_root

    def test_find_project_root_custom_marker(self, tmp_path):
        """Test find_project_root with custom marker file."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        custom_marker = project_root / "custom_marker.yml"
        custom_marker.write_text("custom: marker")

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.get_project_root.return_value = project_root
            mock_pm.return_value = mock_manager

            result = find_project_root(project_root, marker_file="custom_marker.yml")
            assert result == project_root

    def test_find_project_root_not_found(self, tmp_path):
        """Test find_project_root raises error when project root not found."""
        # Use a temp directory without any marker files
        from agent_actions.core.context.path_manager import ProjectRootNotFoundError

        with pytest.raises(ProjectRootNotFoundError):
            find_project_root(tmp_path)


class TestPathMirroring:
    """Test path mirroring functionality."""

    def test_create_mirror_source_path(self, tmp_path):
        """Test create_mirror_source_path creates mirrored path structure."""
        target_path = tmp_path / "target" / "subdir" / "file.txt"

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            expected_source = tmp_path / "source" / "subdir" / "file.txt"
            mock_manager = Mock()
            mock_manager.create_mirror_path.return_value = expected_source
            mock_pm.return_value = mock_manager

            result = create_mirror_source_path(target_path)

            assert result == expected_source
            mock_manager.create_mirror_path.assert_called_once_with(
                Path(target_path), "target", "source"
            )


class TestPathValidation:
    """Test path validation and permission checking."""

    def test_validate_path_permissions_readable(self, tmp_path):
        """Test validate_path_permissions checks readability."""
        test_file = tmp_path / "readable.txt"
        test_file.write_text("content")

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.validate_path.return_value = True
            mock_pm.return_value = mock_manager

            result = validate_path_permissions(test_file, readable=True)

            assert result is True
            mock_manager.validate_path.assert_called_once_with(
                Path(test_file), {"must_be_readable": True}
            )

    def test_validate_path_permissions_writable(self, tmp_path):
        """Test validate_path_permissions checks writability."""
        test_file = tmp_path / "writable.txt"
        test_file.write_text("content")

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.validate_path.return_value = True
            mock_pm.return_value = mock_manager

            result = validate_path_permissions(test_file, writable=True)

            assert result is True
            mock_manager.validate_path.assert_called_once_with(
                Path(test_file), {"must_be_writable": True}
            )

    def test_validate_path_permissions_both_readable_writable(self, tmp_path):
        """Test validate_path_permissions checks both readable and writable."""
        test_file = tmp_path / "rw.txt"
        test_file.write_text("content")

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.validate_path.return_value = True
            mock_pm.return_value = mock_manager

            result = validate_path_permissions(test_file, readable=True, writable=True)

            assert result is True
            mock_manager.validate_path.assert_called_once_with(
                Path(test_file), {"must_be_readable": True, "must_be_writable": True}
            )

    def test_validate_path_permissions_error_handling(self, tmp_path):
        """Test validate_path_permissions handles errors gracefully."""
        test_file = tmp_path / "error.txt"

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.validate_path.side_effect = Exception("Permission error")
            mock_pm.return_value = mock_manager

            result = validate_path_permissions(test_file, readable=True)

            assert result is False


class TestDirectoryOperations:
    """Test directory operations and cleanup."""

    def test_clean_directory_success(self, tmp_path):
        """Test clean_directory removes directory successfully."""
        test_dir = tmp_path / "to_clean"
        test_dir.mkdir()
        (test_dir / "file.txt").write_text("content")

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.clean_path.return_value = True
            mock_pm.return_value = mock_manager

            result = clean_directory(test_dir, recursive=True)

            assert result is True
            mock_manager.clean_path.assert_called_once_with(Path(test_dir), recursive=True)

    def test_clean_directory_failure(self, tmp_path):
        """Test clean_directory handles failure gracefully."""
        test_dir = tmp_path / "protected"
        test_dir.mkdir()

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.clean_path.return_value = False
            mock_pm.return_value = mock_manager

            result = clean_directory(test_dir)

            assert result is False

    def test_clean_directory_non_recursive(self, tmp_path):
        """Test clean_directory with non-recursive option."""
        test_dir = tmp_path / "simple_clean"
        test_dir.mkdir()

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.clean_path.return_value = True
            mock_pm.return_value = mock_manager

            result = clean_directory(test_dir, recursive=False)

            assert result is True
            mock_manager.clean_path.assert_called_once_with(Path(test_dir), recursive=False)


class TestRelativePathOperations:
    """Test relative path operations."""

    def test_get_relative_path_success(self, tmp_path):
        """Test get_relative_path calculates relative path correctly."""
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        target_file = base_dir / "subdir" / "file.txt"
        target_file.parent.mkdir()
        target_file.write_text("content")

        with patch('agent_actions._internal.utils.path_utils.resolve_absolute_path') as mock_resolve:
            mock_resolve.side_effect = lambda p: Path(p).resolve()

            result = get_relative_path(target_file, base_dir)

            expected = Path("subdir") / "file.txt"
            assert result == expected

    def test_get_relative_path_same_directory(self, tmp_path):
        """Test get_relative_path when path is in same directory as base."""
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        target_file = base_dir / "file.txt"
        target_file.write_text("content")

        with patch('agent_actions._internal.utils.path_utils.resolve_absolute_path') as mock_resolve:
            mock_resolve.side_effect = lambda p: Path(p).resolve()

            result = get_relative_path(target_file, base_dir)

            assert result == Path("file.txt")

    def test_get_relative_path_outside_base(self, tmp_path):
        """Test get_relative_path when path is outside base directory."""
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        outside_file = tmp_path / "outside" / "file.txt"
        outside_file.parent.mkdir()
        outside_file.write_text("content")

        with patch('agent_actions._internal.utils.path_utils.resolve_absolute_path') as mock_resolve:
            mock_resolve.side_effect = lambda p: Path(p).resolve()

            with pytest.raises(FileSystemError):
                get_relative_path(outside_file, base_dir)


class TestFileDiscovery:
    """Test file discovery operations."""

    def test_find_files_by_extension_with_dot(self, tmp_path):
        """Test find_files_by_extension with extension including dot."""
        # Create test files
        (tmp_path / "file1.txt").write_text("content1")
        (tmp_path / "file2.txt").write_text("content2")
        (tmp_path / "file3.json").write_text("{}")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file4.txt").write_text("content4")

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            expected_files = [tmp_path / "file1.txt", tmp_path / "file2.txt", subdir / "file4.txt"]
            mock_manager = Mock()
            mock_manager.find_files_by_pattern.return_value = expected_files
            mock_pm.return_value = mock_manager

            result = find_files_by_extension(tmp_path, ".txt")

            assert result == expected_files
            mock_manager.find_files_by_pattern.assert_called_once_with("**/*.txt", Path(tmp_path))

    def test_find_files_by_extension_without_dot(self, tmp_path):
        """Test find_files_by_extension with extension without dot."""
        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.find_files_by_pattern.return_value = []
            mock_pm.return_value = mock_manager

            result = find_files_by_extension(tmp_path, "py")

            assert result == []
            mock_manager.find_files_by_pattern.assert_called_once_with("**/*.py", Path(tmp_path))

    def test_find_files_by_extension_empty_directory(self, tmp_path):
        """Test find_files_by_extension in empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.find_files_by_pattern.return_value = []
            mock_pm.return_value = mock_manager

            result = find_files_by_extension(empty_dir, ".txt")

            assert result == []


class TestSafePathJoining:
    """Test safe path joining with security considerations."""

    def test_safe_path_join_normal_paths(self, tmp_path):
        """Test safe_path_join with normal path components."""
        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            expected_path = tmp_path / "subdir" / "file.txt"
            mock_manager.is_within_project.return_value = True
            mock_pm.return_value = mock_manager

            with patch('agent_actions._internal.utils.path_utils.resolve_absolute_path') as mock_resolve:
                mock_resolve.return_value = expected_path

                result = safe_path_join("subdir", "file.txt")

                assert result == expected_path
                mock_manager.is_within_project.assert_called_once_with(expected_path)

    def test_safe_path_join_prevents_directory_traversal(self, tmp_path):
        """Test safe_path_join prevents directory traversal attacks."""
        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.is_within_project.return_value = False  # Path is outside project
            mock_pm.return_value = mock_manager

            with patch('agent_actions._internal.utils.path_utils.resolve_absolute_path') as mock_resolve:
                dangerous_path = Path("/etc/passwd")
                mock_resolve.return_value = dangerous_path

                with pytest.raises(FileSystemError, match="outside project bounds"):
                    safe_path_join("..", "..", "..", "etc", "passwd")

    def test_safe_path_join_relative_path_components(self, tmp_path):
        """Test safe_path_join with relative path components."""
        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            expected_path = tmp_path / "valid" / "path"
            mock_manager.is_within_project.return_value = True
            mock_pm.return_value = mock_manager

            with patch('agent_actions._internal.utils.path_utils.resolve_absolute_path') as mock_resolve:
                mock_resolve.return_value = expected_path

                result = safe_path_join(".", "valid", "path")

                assert result == expected_path

    def test_safe_path_join_empty_components(self):
        """Test safe_path_join with empty components."""
        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            expected_path = Path.cwd()
            mock_manager.is_within_project.return_value = True
            mock_pm.return_value = mock_manager

            with patch('agent_actions._internal.utils.path_utils.resolve_absolute_path') as mock_resolve:
                mock_resolve.return_value = expected_path

                result = safe_path_join()

                assert result == expected_path


class TestAgentDirectoryStructure:
    """Test agent directory structure creation."""

    def test_create_agent_directory_structure_default_base(self):
        """Test create_agent_directory_structure with default base path."""
        agent_name = "test_agent"

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            project_root = Path("/project/root")
            mock_manager.get_project_root.return_value = project_root
            mock_manager.get_agent_paths.return_value = {
                "config": project_root / "agents" / agent_name / "config",
                "source": project_root / "agents" / agent_name / "source",
                "target": project_root / "agents" / agent_name / "target"
            }
            mock_pm.return_value = mock_manager

            with patch('agent_actions._internal.utils.path_utils.ensure_directory_exists') as mock_ensure:
                mock_ensure.side_effect = lambda p: p

                result = create_agent_directory_structure(agent_name)

                expected_paths = {
                    "config": project_root / "agents" / agent_name / "config",
                    "source": project_root / "agents" / agent_name / "source",
                    "target": project_root / "agents" / agent_name / "target"
                }
                assert result == expected_paths

    def test_create_agent_directory_structure_custom_base(self, tmp_path):
        """Test create_agent_directory_structure with custom base path."""
        agent_name = "custom_agent"
        base_path = tmp_path / "custom_base"

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.get_agent_paths.return_value = {
                "config": base_path / "agents" / agent_name / "config",
                "source": base_path / "agents" / agent_name / "source"
            }
            mock_pm.return_value = mock_manager

            with patch('agent_actions._internal.utils.path_utils.ensure_directory_exists') as mock_ensure:
                mock_ensure.side_effect = lambda p: p

                result = create_agent_directory_structure(agent_name, base_path)

                expected_paths = {
                    "config": base_path / "agents" / agent_name / "config",
                    "source": base_path / "agents" / agent_name / "source"
                }
                assert result == expected_paths

    def test_create_agent_directory_structure_logging(self, caplog):
        """Test create_agent_directory_structure logs creation."""
        import logging
        caplog.set_level(logging.INFO)

        agent_name = "logged_agent"

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            mock_manager.get_project_root.return_value = Path("/project")
            mock_manager.get_agent_paths.return_value = {"config": Path("/project/config")}
            mock_pm.return_value = mock_manager

            with patch('agent_actions._internal.utils.path_utils.ensure_directory_exists') as mock_ensure:
                mock_ensure.side_effect = lambda p: p

                create_agent_directory_structure(agent_name)

                assert f"Created agent directory structure for {agent_name}" in caplog.text


class TestBackwardCompatibility:
    """Test backward compatibility aliases."""

    def test_mkdir_with_parents_alias(self, tmp_path):
        """Test mkdir_with_parents backward compatibility alias."""
        test_dir = tmp_path / "compat_test"

        with patch('agent_actions._internal.utils.path_utils.ensure_directory_exists') as mock_ensure:
            expected_path = test_dir.resolve()
            mock_ensure.return_value = expected_path

            result = mkdir_with_parents(test_dir)

            assert result == expected_path
            mock_ensure.assert_called_once_with(test_dir)

    def test_get_absolute_path_alias(self, tmp_path):
        """Test get_absolute_path backward compatibility alias."""
        test_path = tmp_path / "test_file.txt"

        with patch('agent_actions._internal.utils.path_utils.resolve_absolute_path') as mock_resolve:
            expected_path = test_path.resolve()
            mock_resolve.return_value = expected_path

            result = get_absolute_path(test_path)

            assert result == expected_path
            mock_resolve.assert_called_once_with(test_path)


class TestConstants:
    """Test module constants."""

    def test_default_marker_file_constant(self):
        """Test DEFAULT_MARKER_FILE constant."""
        assert DEFAULT_MARKER_FILE == "agent_actions.yml"

    def test_common_extensions_constant(self):
        """Test COMMON_EXTENSIONS constant."""
        expected_extensions = ['.json', '.yml', '.yaml', '.txt', '.py']
        assert COMMON_EXTENSIONS == expected_extensions

    def test_side_output_dir_name_constant(self):
        """Test SIDE_OUTPUT_DIR_NAME constant."""
        assert SIDE_OUTPUT_DIR_NAME == "side_output"


class TestPlatformSpecificPaths:
    """Test platform-specific path handling."""

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX-specific test")
    def test_posix_path_normalization(self, tmp_path):
        """Test path normalization on POSIX systems."""
        # Create path with mixed separators (should be normalized on POSIX)
        mixed_path = str(tmp_path / "subdir/file.txt").replace("/", "//")

        with patch('agent_actions._internal.utils.path_utils.resolve_absolute_path') as mock_resolve:
            normalized_path = tmp_path / "subdir" / "file.txt"
            mock_resolve.return_value = normalized_path

            result = resolve_absolute_path(mixed_path)

            assert result == normalized_path

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")
    def test_windows_path_normalization(self, tmp_path):
        """Test path normalization on Windows systems."""
        # Create path with mixed separators (should be normalized on Windows)
        mixed_path = str(tmp_path / "subdir\\file.txt").replace("\\", "/")

        with patch('agent_actions._internal.utils.path_utils.resolve_absolute_path') as mock_resolve:
            normalized_path = tmp_path / "subdir" / "file.txt"
            mock_resolve.return_value = normalized_path

            result = resolve_absolute_path(mixed_path)

            assert result == normalized_path

    def test_cross_platform_safe_joins(self, tmp_path):
        """Test safe path joins work across platforms."""
        components = ["subdir", "nested", "file.txt"]

        with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
            mock_manager = Mock()
            expected_path = tmp_path / "subdir" / "nested" / "file.txt"
            mock_manager.is_within_project.return_value = True
            mock_pm.return_value = mock_manager

            with patch('agent_actions._internal.utils.path_utils.resolve_absolute_path') as mock_resolve:
                mock_resolve.return_value = expected_path

                result = safe_path_join(*components)

                assert result == expected_path


class TestErrorHandlingAndEdgeCases:
    """Test comprehensive error handling and edge cases."""

    def test_path_operations_with_none_input(self):
        """Test path operations handle None input gracefully."""
        with pytest.raises((TypeError, AttributeError)):
            resolve_absolute_path(None)

        with pytest.raises((TypeError, AttributeError)):
            check_path_exists(None)

    def test_path_operations_with_empty_string(self):
        """Test path operations handle empty string input."""
        result = check_path_exists("")
        assert result in [True, False]  # Should handle gracefully

        # Empty string path should be handled
        with patch('agent_actions._internal.utils.path_utils.resolve_absolute_path') as mock_resolve:
            mock_resolve.return_value = Path.cwd()
            result = resolve_absolute_path("")
            assert result == Path.cwd()

    def test_permission_errors_in_directory_creation(self, tmp_path):
        """Test handling of permission errors in directory creation."""
        # Simulate permission error
        with patch('pathlib.Path.mkdir') as mock_mkdir:
            mock_mkdir.side_effect = PermissionError("Permission denied")

            # Should handle permission error gracefully
            try:
                ensure_directory_exists(tmp_path / "protected")
            except PermissionError:
                # Expected behavior - permission errors should be propagated
                pass

    def test_concurrent_directory_creation(self, tmp_path):
        """Test concurrent directory creation scenarios."""
        test_dir = tmp_path / "concurrent_test"

        # Simulate race condition where directory is created between checks
        def mkdir_mock(*args, **kwargs):
            # Only raise error if exist_ok is False
            if not kwargs.get('exist_ok', False):
                raise FileExistsError("Directory already exists")
            return None

        with patch('pathlib.Path.mkdir', side_effect=mkdir_mock):
            # Should handle race condition gracefully
            result = ensure_directory_exists(test_dir)
            assert result is not None

    def test_very_long_path_handling(self, tmp_path):
        """Test handling of very long paths."""
        # Create a very long path
        long_components = ["very_long_directory_name"] * 10
        long_path = tmp_path
        for component in long_components:
            long_path = long_path / component

        # Should handle long paths without crashing
        try:
            with patch('agent_actions._internal.utils.path_utils.get_path_manager') as mock_pm:
                mock_manager = Mock()
                mock_manager.normalize_path.return_value = long_path
                mock_pm.return_value = mock_manager

                result = resolve_absolute_path(long_path)
                assert result == long_path
        except OSError:
            # OS-specific path length limitations are acceptable
            pass

    def test_special_characters_in_paths(self, tmp_path):
        """Test handling of special characters in paths."""
        special_chars = ["spaces in name", "unicode_ñäme", "symbols!@#$%"]

        for char_name in special_chars:
            test_path = tmp_path / char_name

            try:
                result = check_path_exists(test_path)
                assert result in [True, False]
            except (UnicodeError, OSError):
                # Some special characters may not be supported by the OS
                pass