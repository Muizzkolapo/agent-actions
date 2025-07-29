"""
Unit tests for path configuration components.

Tests cover PathPatterns, EnvironmentConfig, and PathConfigManager.
"""

import pytest
import tempfile
import yaml
from pathlib import Path
from unittest.mock import patch, mock_open
import os

from agent_actions.core.path_config import (
    PathPatterns,
    EnvironmentConfig,
    PathConfigManager,
    get_environment_config,
    get_path_patterns,
    load_project_config
)


class TestPathPatterns:
    """Test suite for PathPatterns class."""
    
    def test_default_patterns(self):
        """Test default path patterns."""
        patterns = PathPatterns()
        
        assert patterns.agent_config_pattern == "{agent_name}/agent_config"
        assert patterns.source_pattern == "{agent_name}/agent_io/source"
        assert patterns.target_pattern == "{agent_name}/agent_io/target/{node_name}"
        assert patterns.schema_pattern == "schema"
    
    def test_custom_patterns(self):
        """Test custom path patterns."""
        patterns = PathPatterns(
            agent_config_pattern="custom/{agent_name}/config",
            schema_pattern="custom_schema"
        )
        
        assert patterns.agent_config_pattern == "custom/{agent_name}/config"
        assert patterns.schema_pattern == "custom_schema"
        # Defaults should remain
        assert patterns.prompt_store_pattern == "prompt_store"
    
    def test_legacy_structure_patterns(self):
        """Test patterns for legacy directory structure."""
        patterns = PathPatterns.for_legacy_structure()
        
        assert patterns.agent_config_pattern == "agent_config"
        assert patterns.agent_io_pattern == "agent_io"
        assert patterns.source_pattern == "agent_io/source"
        assert patterns.target_pattern == "agent_io/target/{node_name}"
    
    def test_from_config_file_success(self):
        """Test loading patterns from YAML config file."""
        config_data = {
            'path_patterns': {
                'agent_config_pattern': 'custom/{agent_name}/config',
                'schema_pattern': 'custom_schema',
                'source_pattern': '{agent_name}/src'
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)
        
        try:
            patterns = PathPatterns.from_config_file(config_path)
            
            assert patterns.agent_config_pattern == 'custom/{agent_name}/config'
            assert patterns.schema_pattern == 'custom_schema'
            assert patterns.source_pattern == '{agent_name}/src'
            # Defaults for unspecified patterns
            assert patterns.prompt_store_pattern == 'prompt_store'
        finally:
            config_path.unlink()
    
    def test_from_config_file_not_found(self):
        """Test loading patterns when config file doesn't exist."""
        non_existent = Path("/does/not/exist.yml")
        patterns = PathPatterns.from_config_file(non_existent)
        
        # Should return defaults
        assert patterns.agent_config_pattern == "{agent_name}/agent_config"
        assert patterns.schema_pattern == "schema"
    
    def test_from_config_file_invalid_yaml(self):
        """Test loading patterns from invalid YAML file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            f.write("invalid: yaml: content: [")
            config_path = Path(f.name)
        
        try:
            patterns = PathPatterns.from_config_file(config_path)
            # Should return defaults on YAML error
            assert patterns.agent_config_pattern == "{agent_name}/agent_config"
        finally:
            config_path.unlink()


class TestEnvironmentConfig:
    """Test suite for EnvironmentConfig class."""
    
    def test_default_config(self):
        """Test default environment configuration."""
        config = EnvironmentConfig("default")
        
        assert config.name == "default"
        assert config.create_missing_dirs is True
        assert config.validate_permissions is True
        assert config.cache_paths is True
        assert config.marker_file == "agent_actions.yml"
        assert config.allow_symlinks is False
    
    def test_development_config(self):
        """Test development environment configuration."""
        config = EnvironmentConfig.development()
        
        assert config.name == "development"
        assert config.create_missing_dirs is True
        assert config.validate_permissions is False  # More permissive
        assert config.allow_symlinks is True
    
    def test_production_config(self):
        """Test production environment configuration."""
        config = EnvironmentConfig.production()
        
        assert config.name == "production"
        assert config.create_missing_dirs is False  # Don't auto-create
        assert config.validate_permissions is True
        assert config.allow_symlinks is False  # Security
        assert "*.tmp" in config.forbidden_patterns
        assert "__pycache__" in config.forbidden_patterns
    
    def test_testing_config(self):
        """Test testing environment configuration."""
        config = EnvironmentConfig.testing()
        
        assert config.name == "testing"
        assert config.create_missing_dirs is True
        assert config.validate_permissions is False
        assert config.cache_paths is False  # Don't cache in tests
        assert config.marker_file == "test_agent_actions.yml"
        assert config.max_path_length == 255


class TestPathConfigManager:
    """Test suite for PathConfigManager class."""
    
    def test_singleton_behavior(self):
        """Test that PathConfigManager is a singleton."""
        manager1 = PathConfigManager()
        manager2 = PathConfigManager()
        
        assert manager1 is manager2
    
    def test_get_environment_config_explicit(self):
        """Test getting environment configuration with explicit environment."""
        manager = PathConfigManager()
        
        dev_config = manager.get_environment_config("development")
        assert dev_config.name == "development"
        assert dev_config.validate_permissions is False
        
        prod_config = manager.get_environment_config("production")
        assert prod_config.name == "production"
        assert prod_config.create_missing_dirs is False
    
    def test_get_environment_config_aliases(self):
        """Test environment configuration aliases (dev, prod, test)."""
        manager = PathConfigManager()
        
        dev_config = manager.get_environment_config("dev")
        assert dev_config.name == "development"
        
        prod_config = manager.get_environment_config("prod")
        assert prod_config.name == "production"
        
        test_config = manager.get_environment_config("test")
        assert test_config.name == "testing"
    
    @patch.dict(os.environ, {}, clear=True)
    def test_detect_environment_default(self):
        """Test environment detection defaults to development."""
        manager = PathConfigManager()
        manager.clear_cache()  # Clear any cached detection
        
        config = manager.get_environment_config()
        assert config.name == "development"
    
    @patch.dict(os.environ, {'AGENT_ACTIONS_ENV': 'production'})
    def test_detect_environment_from_env_var(self):
        """Test environment detection from environment variable."""
        manager = PathConfigManager()
        manager.clear_cache()
        
        config = manager.get_environment_config()
        assert config.name == "production"
    
    @patch.dict(os.environ, {'PATH': '/usr/bin/pytest:/usr/local/bin'})
    def test_detect_environment_testing(self):
        """Test environment detection for testing."""
        manager = PathConfigManager()
        manager.clear_cache()
        
        config = manager.get_environment_config()
        assert config.name == "testing"
    
    @patch.dict(os.environ, {'CI': 'true'})
    def test_detect_environment_ci(self):
        """Test environment detection for CI/CD."""
        manager = PathConfigManager()
        manager.clear_cache()
        
        config = manager.get_environment_config()
        assert config.name == "production"
    
    def test_get_path_patterns_default(self):
        """Test getting default path patterns."""
        manager = PathConfigManager()
        patterns = manager.get_path_patterns()
        
        assert patterns.agent_config_pattern == "{agent_name}/agent_config"
        assert patterns.schema_pattern == "schema"
    
    def test_get_path_patterns_from_file(self):
        """Test getting path patterns from configuration file."""
        config_data = {
            'path_patterns': {
                'schema_pattern': 'custom_schema'
            }
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
            yaml.dump(config_data, f)
            config_path = Path(f.name)
        
        try:
            manager = PathConfigManager()
            patterns = manager.get_path_patterns(config_path)
            
            assert patterns.schema_pattern == 'custom_schema'
        finally:
            config_path.unlink()
    
    def test_load_project_config_found(self):
        """Test loading project configuration when file exists."""
        project_config = {
            'project_name': 'test_project',
            'version': '1.0.0',
            'settings': {
                'debug': True
            }
        }
        
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            config_file = project_root / "agent_actions.yml"
            
            with open(config_file, 'w') as f:
                yaml.dump(project_config, f)
            
            manager = PathConfigManager()
            config = manager.load_project_config(project_root)
            
            assert config['project_name'] == 'test_project'
            assert config['version'] == '1.0.0'
            assert config['settings']['debug'] is True
    
    def test_load_project_config_multiple_locations(self):
        """Test loading project config from multiple possible locations."""
        project_config = {'found': 'in_config_dir'}
        
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            config_dir = project_root / "config"
            config_dir.mkdir()
            
            # Place config in config/ subdirectory
            config_file = config_dir / "agent_actions.yml"
            with open(config_file, 'w') as f:
                yaml.dump(project_config, f)
            
            manager = PathConfigManager()
            config = manager.load_project_config(project_root)
            
            assert config['found'] == 'in_config_dir'
    
    def test_load_project_config_not_found(self):
        """Test loading project config when no config file exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            
            manager = PathConfigManager()
            config = manager.load_project_config(project_root)
            
            assert config == {}
    
    def test_load_project_config_invalid_yaml(self):
        """Test loading project config with invalid YAML."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            config_file = project_root / "agent_actions.yml"
            
            with open(config_file, 'w') as f:
                f.write("invalid: yaml: [")
            
            manager = PathConfigManager()
            
            with pytest.raises(ValueError, match="Invalid YAML"):
                manager.load_project_config(project_root)
    
    def test_config_caching(self):
        """Test configuration caching behavior."""
        manager = PathConfigManager()
        
        # First call should cache
        config1 = manager.get_environment_config("development")
        config2 = manager.get_environment_config("development")
        
        # Should return same instance from cache
        assert config1 is config2
        
        # Clear cache and get again
        manager.clear_cache()
        config3 = manager.get_environment_config("development")
        
        # Should be different instance after cache clear
        assert config1 is not config3
        assert config1.name == config3.name  # But same values


class TestConvenienceFunctions:
    """Test suite for module-level convenience functions."""
    
    def test_get_environment_config_function(self):
        """Test get_environment_config convenience function."""
        config = get_environment_config("development")
        assert config.name == "development"
        
        config = get_environment_config("production")
        assert config.name == "production"
    
    def test_get_path_patterns_function(self):
        """Test get_path_patterns convenience function."""
        patterns = get_path_patterns()
        assert patterns.agent_config_pattern == "{agent_name}/agent_config"
    
    def test_load_project_config_function(self):
        """Test load_project_config convenience function."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            config = load_project_config(project_root)
            assert config == {}


class TestDefaultConfigurations:
    """Test suite for default configuration constants."""
    
    def test_default_patterns_constant(self):
        """Test DEFAULT_PATTERNS constant."""
        from agent_actions.core.path_config import DEFAULT_PATTERNS
        
        assert DEFAULT_PATTERNS.agent_config_pattern == "{agent_name}/agent_config"
        assert DEFAULT_PATTERNS.schema_pattern == "schema"
    
    def test_environment_config_constants(self):
        """Test environment configuration constants."""
        from agent_actions.core.path_config import DEV_CONFIG, PROD_CONFIG, TEST_CONFIG
        
        assert DEV_CONFIG.name == "development"
        assert PROD_CONFIG.name == "production" 
        assert TEST_CONFIG.name == "testing"
        
        # Verify key differences
        assert DEV_CONFIG.validate_permissions is False
        assert PROD_CONFIG.validate_permissions is True
        assert TEST_CONFIG.cache_paths is False