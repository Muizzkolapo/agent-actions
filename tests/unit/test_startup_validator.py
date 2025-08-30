"""Tests for startup configuration validation."""

import pytest
import os
import tempfile
from unittest.mock import patch, Mock, MagicMock
from pathlib import Path

from agent_actions.core.startup_validator import (
    StartupValidator, 
    StartupValidationError, 
    validate_startup
)
from agent_actions.models.environment_config import Environment


class TestStartupValidator:
    """Test startup validation functionality."""
    
    def test_startup_validator_initialization(self):
        """Test startup validator initialization."""
        validator = StartupValidator()
        
        assert validator.errors == []
        assert validator.warnings == []
        assert validator.environment_config is None
    
    @patch.dict(os.environ, {
        'OPENAI_API_KEY': 'test-openai-key-1234567890',
        'CLAUDE_API_KEY': 'test-claude-key-1234567890',
        'AGENT_ACTIONS_ENV': 'development'
    })
    def test_validate_environment_variables_success(self):
        """Test successful environment variable validation."""
        validator = StartupValidator()
        result = validator.validate_environment_variables()
        
        assert result is True
        assert validator.environment_config is not None
        assert validator.environment_config.agent_actions_env == Environment.DEVELOPMENT
        assert validator.environment_config.openai_api_key == 'test-openai-key-1234567890'
        assert len(validator.errors) == 0
    
    @patch.dict(os.environ, {
        'AGENT_ACTIONS_ENV': 'production'
    }, clear=True)
    def test_validate_environment_variables_production_no_api_keys(self):
        """Test production environment validation without API keys."""
        validator = StartupValidator()
        result = validator.validate_environment_variables()
        
        assert result is False
        assert len(validator.errors) > 0
        assert any("Production environment requires at least one API key" in error 
                  for error in validator.errors)
    
    @patch.dict(os.environ, {
        'AGENT_ACTIONS_ENV': 'development'
    }, clear=True)
    def test_validate_environment_variables_development_warnings(self):
        """Test development environment validation with missing API keys."""
        validator = StartupValidator()
        result = validator.validate_environment_variables()
        
        assert result is True
        assert len(validator.warnings) > 0
        assert any("OPENAI_API_KEY not set" in warning for warning in validator.warnings)
        assert any("CLAUDE_API_KEY" in warning for warning in validator.warnings)
    
    def test_validate_file_system_access_success(self):
        """Test successful file system access validation."""
        validator = StartupValidator()
        result = validator.validate_file_system_access()
        
        assert result is True
        assert len(validator.errors) == 0
    
    @patch('pathlib.Path.cwd')
    @patch('os.access')
    def test_validate_file_system_access_no_read_permission(self, mock_access, mock_cwd):
        """Test file system validation with no read permission."""
        mock_cwd.return_value = Path('/mock/path')
        mock_access.return_value = False
        
        validator = StartupValidator()
        result = validator.validate_file_system_access()
        
        assert result is False
        assert len(validator.errors) > 0
        assert any("Cannot read from current directory" in error for error in validator.errors)
    
    @patch('pathlib.Path.touch')
    def test_validate_file_system_access_no_write_permission(self, mock_touch):
        """Test file system validation with no write permission."""
        mock_touch.side_effect = PermissionError("No write access")
        
        validator = StartupValidator()
        result = validator.validate_file_system_access()
        
        assert result is False
        assert len(validator.errors) > 0
        assert any("Cannot write to current directory" in error for error in validator.errors)
    
    def test_validate_configuration_files_no_paths(self):
        """Test configuration file validation with no paths provided."""
        validator = StartupValidator()
        result = validator.validate_configuration_files()
        
        assert result is True
        assert len(validator.errors) == 0
    
    @patch('agent_actions.handlers.config_handler.ConfigManager')
    def test_validate_configuration_files_success(self, mock_config_manager):
        """Test successful configuration file validation."""
        # Mock successful config loading
        mock_manager_instance = Mock()
        mock_manager_instance.user_config = {'test': 'config'}
        mock_manager_instance.default_config = {'default': 'config'}
        mock_config_manager.return_value = mock_manager_instance
        
        validator = StartupValidator()
        result = validator.validate_configuration_files('/path/to/user.yml', '/path/to/default.yml')
        
        assert result is True
        assert len(validator.errors) == 0
        mock_config_manager.assert_called_once()
        mock_manager_instance.load_configs.assert_called_once()
    
    @patch('agent_actions.handlers.config_handler.ConfigManager')
    def test_validate_configuration_files_failure(self, mock_config_manager):
        """Test configuration file validation failure."""
        # Mock config loading failure
        mock_manager_instance = Mock()
        mock_manager_instance.load_configs.side_effect = Exception("Config loading failed")
        mock_config_manager.return_value = mock_manager_instance
        
        validator = StartupValidator()
        result = validator.validate_configuration_files('/path/to/user.yml', '/path/to/default.yml')
        
        assert result is False
        assert len(validator.errors) > 0
        assert any("Unexpected error validating configuration files" in error for error in validator.errors)
    
    @patch('builtins.__import__')
    def test_validate_dependencies_success(self, mock_import):
        """Test successful dependency validation."""
        # Mock all imports successful
        mock_import.return_value = Mock()
        
        validator = StartupValidator()
        result = validator.validate_dependencies()
        
        assert result is True
        assert len(validator.errors) == 0
    
    @patch('builtins.__import__')
    def test_validate_dependencies_missing_packages(self, mock_import):
        """Test dependency validation with missing packages."""
        # Mock some imports failing
        def mock_import_side_effect(name):
            if name in ['yaml', 'pydantic']:
                return Mock()
            raise ImportError(f"No module named '{name}'")
        
        mock_import.side_effect = mock_import_side_effect
        
        validator = StartupValidator()
        result = validator.validate_dependencies()
        
        assert result is False
        assert len(validator.errors) > 0
        assert any("Missing required packages" in error for error in validator.errors)
    
    @patch.dict(os.environ, {
        'AGENT_ACTIONS_ENV': 'production',
        'ENABLE_PARALLEL_PROCESSING': 'false',
        'DEFAULT_BATCH_SIZE': '25',
        'OPENAI_API_KEY': 'test-key-1234567890'
    })
    def test_validate_performance_settings_production_warnings(self):
        """Test performance settings validation in production."""
        validator = StartupValidator()
        validator.validate_environment_variables()  # Load config first
        result = validator.validate_performance_settings()
        
        assert result is True
        assert len(validator.warnings) > 0
        assert any("Parallel processing is disabled in production" in warning 
                  for warning in validator.warnings)
        assert any("Batch size is small for production" in warning 
                  for warning in validator.warnings)
    
    @patch('agent_actions.core.startup_validator.StartupValidator.validate_dependencies')
    @patch('agent_actions.core.startup_validator.StartupValidator.validate_environment_variables')
    @patch('agent_actions.core.startup_validator.StartupValidator.validate_file_system_access')
    @patch('agent_actions.core.startup_validator.StartupValidator.validate_configuration_files')
    @patch('agent_actions.core.startup_validator.StartupValidator.validate_performance_settings')
    def test_run_full_validation_success(self, mock_perf, mock_config, mock_fs, mock_env, mock_deps):
        """Test successful full validation."""
        # Mock all validations successful
        mock_deps.return_value = True
        mock_env.return_value = True
        mock_fs.return_value = True
        mock_config.return_value = True
        mock_perf.return_value = True
        
        validator = StartupValidator()
        result = validator.run_full_validation()
        
        assert result is True
        assert len(validator.errors) == 0
        
        # Verify all validations were called
        mock_deps.assert_called_once()
        mock_env.assert_called_once()
        mock_fs.assert_called_once()
        mock_config.assert_called_once()
        mock_perf.assert_called_once()
    
    @patch('agent_actions.core.startup_validator.StartupValidator.validate_dependencies')
    @patch('agent_actions.core.startup_validator.StartupValidator.validate_environment_variables')
    def test_run_full_validation_failure(self, mock_env, mock_deps):
        """Test full validation failure."""
        # Mock one validation failing
        mock_deps.return_value = False
        mock_env.return_value = True
        
        validator = StartupValidator()
        validator.errors = ["Dependency validation failed"]  # Simulate error
        result = validator.run_full_validation()
        
        assert result is False
    
    def test_get_validation_report(self):
        """Test validation report generation."""
        validator = StartupValidator()
        validator.errors = ["Test error"]
        validator.warnings = ["Test warning"]
        
        report = validator.get_validation_report()
        
        assert report['success'] is False
        assert report['errors'] == ["Test error"]
        assert report['warnings'] == ["Test warning"]
        assert 'environment' in report
    
    def test_raise_on_errors(self):
        """Test raising error when validation fails."""
        validator = StartupValidator()
        validator.errors = ["Test error 1", "Test error 2"]
        
        with pytest.raises(StartupValidationError) as exc_info:
            validator.raise_on_errors()
        
        assert "Startup validation failed with 2 error(s)" in str(exc_info.value)
        assert exc_info.value.errors == ["Test error 1", "Test error 2"]
    
    def test_raise_on_errors_no_errors(self):
        """Test no error raised when validation succeeds."""
        validator = StartupValidator()
        # No errors
        
        # Should not raise
        validator.raise_on_errors()


class TestValidateStartupFunction:
    """Test the convenience validate_startup function."""
    
    @patch('agent_actions.core.startup_validator.StartupValidator')
    def test_validate_startup_success(self, mock_validator_class):
        """Test successful startup validation."""
        # Mock validator
        mock_validator = Mock()
        mock_validator.run_full_validation.return_value = True
        mock_validator.environment_config = Mock()
        mock_validator.raise_on_errors.return_value = None
        mock_validator_class.return_value = mock_validator
        
        result = validate_startup('/path/to/user.yml', '/path/to/default.yml')
        
        assert result == mock_validator.environment_config
        mock_validator.run_full_validation.assert_called_once_with('/path/to/user.yml', '/path/to/default.yml')
    
    @patch('agent_actions.core.startup_validator.StartupValidator')
    def test_validate_startup_failure(self, mock_validator_class):
        """Test startup validation failure."""
        # Mock validator failure
        mock_validator = Mock()
        mock_validator.run_full_validation.return_value = False
        mock_validator.raise_on_errors.side_effect = StartupValidationError("Validation failed", ["Error 1"])
        mock_validator_class.return_value = mock_validator
        
        with pytest.raises(StartupValidationError):
            validate_startup('/path/to/user.yml', '/path/to/default.yml')
    
    @patch('agent_actions.core.startup_validator.StartupValidator')
    def test_validate_startup_no_environment_config(self, mock_validator_class):
        """Test startup validation with no environment config loaded."""
        # Mock validator with no environment config
        mock_validator = Mock()
        mock_validator.run_full_validation.return_value = True
        mock_validator.environment_config = None
        mock_validator_class.return_value = mock_validator
        
        with pytest.raises(StartupValidationError) as exc_info:
            validate_startup()
        
        assert "Environment configuration not loaded" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__])