"""
Unit tests for PathManager class.

Tests cover path resolution, validation, normalization, and all core functionality.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import os

from agent_actions.core.path_manager import (
    PathManager, 
    PathType, 
    PathConfig, 
    PathManagerError,
    ProjectRootNotFoundError,
    PathValidationError
)


class TestPathManager:
    """Test suite for PathManager class."""
    
    @pytest.fixture
    def temp_project(self):
        """Create a temporary project structure for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        
        # Create project structure
        project_root = temp_dir / "test_project"
        project_root.mkdir()
        
        # Create marker file
        (project_root / "agent_actions.yml").write_text("test: true")
        
        # Create standard directories
        (project_root / "schema").mkdir()
        (project_root / "prompt_store").mkdir()
        (project_root / "agent_config").mkdir()
        
        # Create agent-specific structure
        agent_dir = project_root / "test_agent"
        agent_dir.mkdir()
        (agent_dir / "agent_config").mkdir()
        
        agent_io = agent_dir / "agent_io"
        agent_io.mkdir()
        (agent_io / "source").mkdir()
        (agent_io / "target").mkdir()
        
        yield project_root
        
        # Cleanup
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def path_manager(self, temp_project):
        """Create PathManager instance with test project."""
        return PathManager(project_root=temp_project)
    
    def test_path_manager_initialization(self):
        """Test PathManager initialization with different configurations."""
        # Default initialization
        pm = PathManager()
        assert pm.config.create_if_missing is True
        assert pm.config.validate_permissions is True
        assert pm.config.marker_file == "agent_actions.yml"
        
        # Custom configuration
        config = PathConfig(create_if_missing=False, marker_file="custom.yml")
        pm = PathManager(config=config)
        assert pm.config.create_if_missing is False
        assert pm.config.marker_file == "custom.yml"
    
    def test_get_project_root_success(self, temp_project):
        """Test successful project root discovery."""
        pm = PathManager()
        
        # Test from project root
        with patch('pathlib.Path.cwd', return_value=temp_project):
            root = pm.get_project_root()
            assert root.resolve() == temp_project.resolve()
        
        # Test from subdirectory
        subdir = temp_project / "subdir"
        subdir.mkdir()
        with patch('pathlib.Path.cwd', return_value=subdir):
            root = pm.get_project_root()
            assert root.resolve() == temp_project.resolve()
    
    def test_get_project_root_not_found(self):
        """Test project root discovery failure."""
        pm = PathManager()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            with patch('pathlib.Path.cwd', return_value=temp_path):
                with pytest.raises(ProjectRootNotFoundError):
                    pm.get_project_root()
    
    def test_get_project_root_caching(self, temp_project):
        """Test project root caching behavior."""
        pm = PathManager(config=PathConfig(cache_paths=True))
        
        with patch('pathlib.Path.cwd', return_value=temp_project):
            root1 = pm.get_project_root()
            root2 = pm.get_project_root()
            
            assert root1 == root2
            assert pm._project_root.resolve() == temp_project.resolve()
    
    def test_get_standard_path_project_root(self, path_manager):
        """Test getting project root path."""
        path = path_manager.get_standard_path(PathType.PROJECT_ROOT)
        assert path.name == "test_project"
        assert path.exists()
    
    def test_get_standard_path_agent_specific(self, path_manager):
        """Test getting agent-specific paths."""
        # Agent config path
        config_path = path_manager.get_standard_path(
            PathType.AGENT_CONFIG, 
            agent_name="test_agent"
        )
        expected = path_manager.get_project_root() / "test_agent" / "agent_config"
        assert config_path == expected
        
        # Source path
        source_path = path_manager.get_standard_path(
            PathType.SOURCE,
            agent_name="test_agent"
        )
        expected = path_manager.get_project_root() / "test_agent" / "agent_io" / "source"
        assert source_path == expected
        
        # Target path with node name
        target_path = path_manager.get_standard_path(
            PathType.TARGET,
            agent_name="test_agent",
            node_name="node1"
        )
        expected = path_manager.get_project_root() / "test_agent" / "agent_io" / "target" / "node1"
        assert target_path == expected
    
    def test_get_standard_path_missing_template_vars(self, path_manager):
        """Test error when required template variables are missing."""
        with pytest.raises(PathManagerError, match="Missing required template variable"):
            path_manager.get_standard_path(PathType.AGENT_CONFIG)
    
    def test_get_standard_path_unknown_type(self, path_manager):
        """Test error for unknown path type."""
        # Create a mock PathType enum that doesn't exist in PATH_TEMPLATES
        from unittest.mock import MagicMock
        unknown_type = MagicMock()
        unknown_type.value = "unknown_type"
        
        with pytest.raises(PathManagerError, match="Unknown path type"):
            path_manager.get_standard_path(unknown_type)
    
    def test_get_agent_paths(self, path_manager):
        """Test getting all paths for an agent."""
        paths = path_manager.get_agent_paths("test_agent")
        
        assert "config" in paths
        assert "io" in paths
        assert "source" in paths
        
        expected_config = path_manager.get_project_root() / "test_agent" / "agent_config"
        assert paths["config"] == expected_config
    
    def test_ensure_path_exists_directory(self, path_manager):
        """Test ensuring directory exists."""
        test_dir = path_manager.get_project_root() / "new_directory"
        assert not test_dir.exists()
        
        result = path_manager.ensure_path_exists(test_dir)
        assert test_dir.exists()
        assert test_dir.is_dir()
        assert result == test_dir.resolve()
    
    def test_ensure_path_exists_file(self, path_manager):
        """Test ensuring parent directory exists for file."""
        test_file = path_manager.get_project_root() / "new_dir" / "test_file.txt"
        assert not test_file.parent.exists()
        
        result = path_manager.ensure_path_exists(test_file, is_file=True)
        assert test_file.parent.exists()
        assert test_file.parent.is_dir()
        assert result == test_file.resolve()
    
    def test_ensure_path_exists_disabled(self, temp_project):
        """Test ensure_path_exists when create_if_missing is disabled."""
        config = PathConfig(create_if_missing=False)
        pm = PathManager(config=config, project_root=temp_project)
        
        test_dir = temp_project / "should_not_create"
        result = pm.ensure_path_exists(test_dir)
        
        assert not test_dir.exists()
        assert result == test_dir.resolve()
    
    def test_validate_path_success(self, path_manager):
        """Test successful path validation."""
        existing_path = path_manager.get_project_root() / "schema"
        requirements = {
            "must_exist": True,
            "must_be_directory": True,
            "must_be_readable": True
        }
        
        result = path_manager.validate_path(existing_path, requirements)
        assert result is True
    
    def test_validate_path_failure(self, path_manager):
        """Test path validation failure."""
        non_existing_path = path_manager.get_project_root() / "does_not_exist"
        requirements = {"must_exist": True}
        
        # With validation enabled (should raise)
        with pytest.raises(PathValidationError):
            path_manager.validate_path(non_existing_path, requirements)
        
        # With validation disabled (should return False)
        config = PathConfig(validate_permissions=False)
        pm = PathManager(config=config, project_root=path_manager.get_project_root())
        result = pm.validate_path(non_existing_path, requirements)
        assert result is False
    
    @pytest.mark.skipif(os.name == 'nt', reason="Unix permissions test")
    def test_validate_path_permissions(self, path_manager):
        """Test path permission validation on Unix systems."""
        test_file = path_manager.get_project_root() / "test_permissions.txt"
        test_file.write_text("test")
        
        # Make file read-only
        os.chmod(test_file, 0o444)
        
        # Should pass read requirement
        result = path_manager.validate_path(test_file, {"must_be_readable": True})
        assert result is True
        
        # Should fail write requirement
        with pytest.raises(PathValidationError):
            path_manager.validate_path(test_file, {"must_be_writable": True})
    
    def test_validate_standard_path(self, path_manager):
        """Test validation using standard path type requirements."""
        schema_path = path_manager.get_project_root() / "schema"
        result = path_manager.validate_standard_path(PathType.SCHEMA, schema_path)
        assert result is True
    
    def test_normalize_path(self, path_manager):
        """Test path normalization."""
        # String path
        result = path_manager.normalize_path("test/path")
        assert isinstance(result, Path)
        assert result.is_absolute()
        
        # Path object
        path_obj = Path("another/path")
        result = path_manager.normalize_path(path_obj)
        assert isinstance(result, Path)
        assert result.is_absolute()
    
    def test_is_within_project(self, path_manager):
        """Test checking if path is within project."""
        project_root = path_manager.get_project_root()
        
        # Path within project
        internal_path = project_root / "subdirectory" / "file.txt"
        assert path_manager.is_within_project(internal_path) is True
        
        # Path outside project
        external_path = Path("/tmp/external_file.txt")
        assert path_manager.is_within_project(external_path) is False
        
        # Project root itself
        assert path_manager.is_within_project(project_root) is True
    
    def test_get_relative_to_project(self, path_manager):
        """Test getting path relative to project root."""
        project_root = path_manager.get_project_root()
        absolute_path = project_root / "subdirectory" / "file.txt"
        
        relative = path_manager.get_relative_to_project(absolute_path)
        assert relative == Path("subdirectory") / "file.txt"
        assert not relative.is_absolute()
    
    def test_find_files_by_pattern(self, path_manager):
        """Test finding files by glob pattern."""
        project_root = path_manager.get_project_root()
        
        # Create test files
        (project_root / "test1.txt").write_text("test")
        (project_root / "test2.txt").write_text("test")
        (project_root / "other.py").write_text("test")
        
        # Find txt files
        txt_files = path_manager.find_files_by_pattern("*.txt")
        assert len(txt_files) == 2
        assert all(f.suffix == ".txt" for f in txt_files)
        
        # Find all files
        all_files = path_manager.find_files_by_pattern("*")
        assert len(all_files) >= 3  # At least our test files
    
    def test_clean_path_file(self, path_manager):
        """Test cleaning/removing a file."""
        project_root = path_manager.get_project_root()
        test_file = project_root / "to_delete.txt"
        test_file.write_text("delete me")
        
        assert test_file.exists()
        
        result = path_manager.clean_path(test_file)
        assert result is True
        assert not test_file.exists()
    
    def test_clean_path_directory(self, path_manager):
        """Test cleaning/removing a directory."""
        project_root = path_manager.get_project_root()
        test_dir = project_root / "to_delete_dir"
        test_dir.mkdir()
        
        # Empty directory
        result = path_manager.clean_path(test_dir)
        assert result is True
        assert not test_dir.exists()
        
        # Directory with content (recursive)
        test_dir.mkdir()
        (test_dir / "file.txt").write_text("content")
        
        result = path_manager.clean_path(test_dir, recursive=True)
        assert result is True
        assert not test_dir.exists()
    
    def test_create_mirror_path(self, path_manager):
        """Test creating mirror paths (replaces SourceDataLoader logic)."""
        original_path = Path("/project/agent/agent_io/target/node1/data.json")
        
        # Create source mirror
        source_path = path_manager.create_mirror_path(
            original_path, "target", "source"
        )
        expected = Path("/project/agent/agent_io/source/node1/data.json")
        assert source_path == expected
        
        # Test error when base not found
        with pytest.raises(PathManagerError, match="Source base 'missing' not found"):
            path_manager.create_mirror_path(original_path, "missing", "other")
    
    def test_path_caching(self, path_manager):
        """Test path caching functionality."""
        # Enable caching
        path_manager.config.cache_paths = True
        
        # First call should populate cache
        path1 = path_manager.get_standard_path(PathType.SCHEMA)
        
        # Second call should use cache
        path2 = path_manager.get_standard_path(PathType.SCHEMA)
        
        assert path1 == path2
        assert len(path_manager._path_cache) > 0
        
        # Clear cache
        path_manager.clear_cache()
        assert len(path_manager._path_cache) == 0
        assert path_manager._project_root is None
    
    def test_environment_specific_config(self):
        """Test environment-specific configuration."""
        dev_config = PathConfig.for_environment("dev")
        assert dev_config.create_if_missing is True
        
        prod_config = PathConfig.for_environment("prod")
        assert prod_config.create_if_missing is False
        assert prod_config.validate_permissions is True
        
        test_config = PathConfig.for_environment("test")
        assert test_config.marker_file == "test_agent_actions.yml"