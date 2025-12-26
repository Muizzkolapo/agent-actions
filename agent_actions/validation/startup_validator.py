"""Startup configuration validation for Agent Actions."""
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from agent_actions.errors import ConfigurationError
from agent_actions.llm_invocation.realtime.config_handler import ConfigManager
from agent_actions.state_management.environment_config import EnvironmentConfig

logger = logging.getLogger(__name__)

class StartupValidationError(Exception):
    """Raised when startup validation fails."""

    def __init__(self, message: str, errors: List[str]):
        super().__init__(message)
        self.errors = errors

class StartupValidator:
    """Validates application configuration during startup."""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.environment_config: Optional[EnvironmentConfig] = None

    def validate_environment_variables(
        self,
        constructor_path: Optional[str] = None
    ) -> bool:
        """Validate required environment variables are present."""
        logger.debug('Validating environment variables...')
        try:
            self.environment_config = EnvironmentConfig()
            logger.debug(
                'Environment configuration loaded successfully. '
                'Environment: %s',
                self.environment_config.agent_actions_env
            )
        except ValidationError as e:
            for error in e.errors():
                # Safely access first element of location tuple
                loc = error.get('loc', ('unknown',))
                field_name = loc[0] if loc else 'unknown'
                error_msg = error.get('msg', 'Unknown error')
                self.errors.append(
                    f'Environment variable validation failed for '
                    f'{field_name}: {error_msg}'
                )
            return False
        required_vendors = self._analyze_config_for_vendors(constructor_path)
        self._validate_api_keys(required_vendors)
        return len(self.errors) == 0

    def _check_production_api_keys(self, available_keys: List[Optional[str]]) -> None:
        """Check API keys in production environment."""
        if not any(key for key in available_keys if key):
            self.errors.append(
                'Production environment requires at least one API key '
                '(OPENAI_API_KEY, CLAUDE_API_KEY/ANTHROPIC_API_KEY, '
                'or GOOGLE_API_KEY)'
            )

    def _check_development_all_vendors(self) -> None:
        """Check all vendor API keys in development (legacy behavior)."""
        if not self.environment_config.openai_api_key:
            self.warnings.append(
                'OPENAI_API_KEY not set - OpenAI models will not be available'
            )
        if not self.environment_config.get_effective_claude_key():
            self.warnings.append(
                'CLAUDE_API_KEY/ANTHROPIC_API_KEY not set - Claude '
                'models will not be available'
            )
        if not self.environment_config.google_api_key:
            self.warnings.append(
                'GOOGLE_API_KEY not set - Gemini models will not be available'
            )

    def _get_vendor_key_value(self, key_attr: str) -> Optional[str]:
        """Get vendor key value from environment config."""
        if key_attr == 'get_effective_claude_key':
            return self.environment_config.get_effective_claude_key()
        return getattr(self.environment_config, key_attr)

    def _check_development_required_vendors(
        self,
        required_vendors: set,
        vendor_key_mapping: Dict[str, tuple]
    ) -> None:
        """Check required vendor API keys in development."""
        for vendor in required_vendors:
            if vendor.lower() not in vendor_key_mapping:
                continue
            key_attr, key_name, model_desc = vendor_key_mapping[vendor.lower()]
            key_value = self._get_vendor_key_value(key_attr)
            if not key_value:
                self.warnings.append(
                    f'{key_name} not set - {model_desc} will not be available'
                )

    def _validate_api_keys(self, required_vendors: Optional[set] = None) -> None:
        """Validate that required API keys are available.

        Args:
            required_vendors: Set of vendor types that are actually used in
                the configuration. If None, will warn about all missing keys
                (legacy behavior).
        """
        if not self.environment_config:
            return
        vendor_key_mapping = {
            'openai': ('openai_api_key', 'OPENAI_API_KEY', 'OpenAI models'),
            'anthropic': (
                'get_effective_claude_key',
                'CLAUDE_API_KEY/ANTHROPIC_API_KEY',
                'Claude models'
            ),
            'google': ('google_api_key', 'GOOGLE_API_KEY', 'Gemini models'),
            'gemini': ('google_api_key', 'GOOGLE_API_KEY', 'Gemini models')
        }
        available_keys = [
            self.environment_config.openai_api_key,
            self.environment_config.get_effective_claude_key(),
            self.environment_config.google_api_key
        ]
        if self.environment_config.is_production():
            self._check_production_api_keys(available_keys)
        if self.environment_config.is_development():
            if required_vendors is None:
                self._check_development_all_vendors()
            else:
                self._check_development_required_vendors(
                    required_vendors, vendor_key_mapping
                )

    def _analyze_config_for_vendors(
        self,
        constructor_path: Optional[str]
    ) -> set:
        """Analyze configuration file to determine which vendors are used.

        Args:
            constructor_path: Path to the user configuration file

        Returns:
            Set of vendor types used in the configuration
        """
        required_vendors = set()
        if not constructor_path:
            return required_vendors
        try:
            config_file = Path(constructor_path)
            if not config_file.exists():
                return required_vendors
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
            vendor_pattern = 'model_vendor:\\s*["\\\']?([^"\\\'\\s]+)["\\\']?'
            vendors = re.findall(vendor_pattern, content, re.IGNORECASE)
            for vendor in vendors:
                required_vendors.add(vendor.lower())
            logger.debug(
                'Detected vendors in configuration: %s', required_vendors
            )
        except (OSError, ValueError) as e:
            logger.debug(
                'Could not analyze configuration for vendor requirements: %s',
                e
            )
            return set()
        return required_vendors

    def validate_file_system_access(self) -> bool:
        """Validate file system access permissions."""
        logger.debug('Validating file system access...')
        current_dir = Path.cwd()
        if not current_dir.exists() or not os.access(current_dir, os.R_OK):
            self.errors.append(f'Cannot read from current directory: {current_dir}')
            return False
        try:
            temp_file = current_dir / '.agent_actions_write_test'
            temp_file.touch()
            temp_file.unlink()
        except (OSError, PermissionError) as e:
            self.errors.append(f'Cannot write to current directory: {current_dir} - {e}')
            return False
        templates_dir = current_dir / 'templates'
        if templates_dir.exists() and (not os.access(templates_dir, os.R_OK)):
            self.errors.append(f'Cannot read from templates directory: {templates_dir}')
            return False
        return True

    def validate_configuration_files(
        self,
        constructor_path: Optional[str] = None,
        default_path: Optional[str] = None
    ) -> bool:
        """Validate configuration files can be loaded and parsed."""
        logger.debug('Validating configuration files...')
        if not constructor_path or not default_path:
            logger.debug(
                'Configuration file paths not provided, skipping validation'
            )
            return True
        try:
            config_manager = ConfigManager(constructor_path, default_path)
            config_manager.load_configs()
            if config_manager.user_config is None:
                self.errors.append(
                    f'Failed to load user configuration from: '
                    f'{constructor_path}'
                )
                return False
            if config_manager.default_config is None:
                self.errors.append(
                    f'Failed to load default configuration from: '
                    f'{default_path}'
                )
                return False
            logger.debug('Configuration files validated successfully')
            return True
        except ConfigurationError as e:
            self.errors.append(f'Configuration file validation failed: {e}')
            return False
        except (OSError, ValueError, TypeError) as e:
            self.errors.append(
                f'Unexpected error validating configuration files: {e}'
            )
            return False

    def validate_dependencies(self) -> bool:
        """Validate that required dependencies are available."""
        logger.debug('Validating dependencies...')
        required_packages = [
            'yaml', 'pydantic', 'openai', 'anthropic', 'tiktoken',
            'flask', 'networkx', 'pandas'
        ]
        missing_packages = []
        for package in required_packages:
            try:
                __import__(package)
            except ImportError:
                missing_packages.append(package)
        if missing_packages:
            self.errors.append(
                f"Missing required packages: {', '.join(missing_packages)}"
            )
            return False
        return True

    def validate_performance_settings(self) -> bool:
        """Validate performance-related settings."""
        if not self.environment_config:
            return True
        logger.debug('Validating performance settings...')
        if self.environment_config.is_production():
            if not self.environment_config.enable_parallel_processing:
                self.warnings.append(
                    'Parallel processing is disabled in production - this may '
                    'impact performance'
                )
            if self.environment_config.default_batch_size < 50:
                self.warnings.append(
                    f'Batch size is small for production '
                    f'({self.environment_config.default_batch_size}) - '
                    f'consider increasing for better performance'
                )
        return True

    def run_full_validation(
        self,
        constructor_path: Optional[str] = None,
        default_path: Optional[str] = None
    ) -> bool:
        """Run complete startup validation."""
        logger.debug('Starting full startup validation...')
        self.errors.clear()
        self.warnings.clear()
        validations = [
            self.validate_dependencies(),
            self.validate_environment_variables(constructor_path),
            self.validate_file_system_access(),
            self.validate_configuration_files(constructor_path, default_path),
            self.validate_performance_settings()
        ]
        success = all(validations)
        if self.warnings:
            for warning in self.warnings:
                logger.warning(warning)
        if success:
            logger.info('✅ All startup validations passed successfully')
        else:
            logger.error('❌ Startup validation failed')
            for error in self.errors:
                logger.error('  - %s', error)
        return success

    def get_validation_report(self) -> Dict[str, Any]:
        """Get a detailed validation report."""
        return {
            'success': len(self.errors) == 0,
            'errors': self.errors.copy(),
            'warnings': self.warnings.copy(),
            'environment': {
                'config_loaded': self.environment_config is not None,
                'environment_type': (
                    self.environment_config.agent_actions_env
                    if self.environment_config else None
                ),
                'debug_enabled': (
                    self.environment_config.debug_logging
                    if self.environment_config else None
                )
            }
        }

    def raise_on_errors(self) -> None:
        """Raise StartupValidationError if there are validation errors."""
        if self.errors:
            raise StartupValidationError(
                f'Startup validation failed with {len(self.errors)} error(s)',
                self.errors
            )


def validate_startup(
    constructor_path: Optional[str] = None,
    default_path: Optional[str] = None
) -> EnvironmentConfig:
    """Convenience function to run startup validation.

    Args:
        constructor_path: Path to user configuration file
        default_path: Path to default configuration file

    Returns:
        EnvironmentConfig: Validated environment configuration

    Raises:
        StartupValidationError: If validation fails
    """
    validator = StartupValidator()
    success = validator.run_full_validation(constructor_path, default_path)
    if not success:
        validator.raise_on_errors()
    if not validator.environment_config:
        raise StartupValidationError(
            'Environment configuration not loaded', []
        )
    return validator.environment_config


__all__ = ['StartupValidator', 'StartupValidationError', 'validate_startup']
