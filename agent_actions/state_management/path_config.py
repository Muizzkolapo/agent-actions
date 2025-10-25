"""
Path configuration templates and patterns for agent-actions.

This module defines configurable path patterns that can be customized
for different project structures and environments.
"""
from typing import Dict, Any, Optional
from pathlib import Path
import os
from dataclasses import dataclass, field

@dataclass
class PathPatterns:
    """Configurable path patterns for different directory structures."""
    agent_config_pattern: str = '{agent_name}/agent_config'
    agent_io_pattern: str = '{agent_name}/agent_io'
    source_pattern: str = '{agent_name}/agent_io/source'
    target_pattern: str = '{agent_name}/agent_io/target/{node_name}'
    schema_pattern: str = 'schema'
    prompt_store_pattern: str = 'prompt_store'
    templates_pattern: str = 'templates'
    rendered_workflows_pattern: str = 'rendered_workflows'
    batch_pattern: str = 'batch'
    side_output_pattern: str = 'side_output'
    legacy_agent_io_pattern: str = 'agent_io'
    legacy_source_pattern: str = 'agent_io/source'
    legacy_target_pattern: str = 'agent_io/target/{node_name}'

    @classmethod
    def from_config_file(cls, config_path: Path) -> 'PathPatterns':
        """Load path patterns from a configuration file."""
        import yaml
        try:
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)
            path_config = config_data.get('path_patterns', {})
            return cls(**path_config)
        except (FileNotFoundError, yaml.YAMLError):
            return cls()

    @classmethod
    def for_legacy_structure(cls) -> 'PathPatterns':
        """Get patterns compatible with legacy directory structure."""
        return cls(agent_config_pattern='agent_config', agent_io_pattern='agent_io', source_pattern='agent_io/source', target_pattern='agent_io/target/{node_name}')

@dataclass
class EnvironmentConfig:
    """Environment-specific configuration for path operations."""
    name: str
    create_missing_dirs: bool = True
    validate_permissions: bool = True
    cache_paths: bool = True
    marker_file: str = 'agent_actions.yml'
    max_path_length: Optional[int] = None
    allowed_extensions: Optional[list] = None
    forbidden_patterns: list = field(default_factory=list)
    allow_symlinks: bool = False
    allow_absolute_paths: bool = True
    sandbox_to_project: bool = True

    @classmethod
    def development(cls) -> 'EnvironmentConfig':
        """Configuration suitable for development environment."""
        return cls(name='development', create_missing_dirs=True, validate_permissions=False, cache_paths=True, allow_symlinks=True)

    @classmethod
    def production(cls) -> 'EnvironmentConfig':
        """Configuration suitable for production environment."""
        return cls(name='production', create_missing_dirs=False, validate_permissions=True, cache_paths=True, allow_symlinks=False, forbidden_patterns=['*.tmp', '*.log', '__pycache__', '.git'])

    @classmethod
    def testing(cls) -> 'EnvironmentConfig':
        """Configuration suitable for testing environment."""
        return cls(name='testing', create_missing_dirs=True, validate_permissions=False, cache_paths=False, marker_file='test_agent_actions.yml', max_path_length=255)

class PathConfigManager:
    """Manages path configuration loading and environment detection."""
    _instance = None
    _config_cache: Dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_environment_config(self, environment: Optional[str]=None) -> EnvironmentConfig:
        """
        Get environment configuration.
        
        Args:
            environment: Environment name (dev, prod, test) or None for auto-detection
            
        Returns:
            EnvironmentConfig for the specified or detected environment
        """
        if environment is None:
            environment = self._detect_environment()
        if environment in self._config_cache:
            return self._config_cache[environment]
        config_map = {'development': EnvironmentConfig.development, 'dev': EnvironmentConfig.development, 'production': EnvironmentConfig.production, 'prod': EnvironmentConfig.production, 'testing': EnvironmentConfig.testing, 'test': EnvironmentConfig.testing}
        config_factory = config_map.get(environment, EnvironmentConfig.development)
        config = config_factory()
        self._config_cache[environment] = config
        return config

    def get_path_patterns(self, config_file: Optional[Path]=None) -> PathPatterns:
        """
        Get path patterns from configuration file or defaults.
        
        Args:
            config_file: Optional path to configuration file
            
        Returns:
            PathPatterns instance
        """
        if config_file and config_file.exists():
            return PathPatterns.from_config_file(config_file)
        return PathPatterns()

    def _detect_environment(self) -> str:
        """
        Auto-detect the current environment.
        
        Returns:
            Detected environment name
        """
        env_var = os.getenv('AGENT_ACTIONS_ENV', '').lower()
        if env_var in ['dev', 'development', 'prod', 'production', 'test', 'testing']:
            return env_var
        if any((test_indicator in os.getenv('PATH', '') for test_indicator in ['pytest', 'unittest'])):
            return 'testing'
        if any((os.getenv(ci_var) for ci_var in ['CI', 'CONTINUOUS_INTEGRATION', 'GITHUB_ACTIONS'])):
            return 'production'
        return 'development'

    def load_project_config(self, project_root: Path) -> Dict[str, Any]:
        """
        Load project-specific configuration.
        
        Args:
            project_root: Path to project root directory
            
        Returns:
            Dictionary of project configuration
        """
        config_files = [project_root / 'agent_actions.yml', project_root / 'agent_actions.yaml', project_root / '.agent_actions.yml', project_root / 'config' / 'agent_actions.yml']
        for config_file in config_files:
            if config_file.exists():
                return self._load_yaml_config(config_file)
        return {}

    def _load_yaml_config(self, config_path: Path) -> Dict[str, Any]:
        """Load YAML configuration file."""
        import yaml
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            from agent_actions.shared.exceptions import ConfigValidationError
            raise ConfigValidationError('path_config_yaml', f'Invalid YAML in config file {config_path}', context={'config_path': str(config_path), 'operation': 'load_config'}, cause=e)

    def clear_cache(self):
        """Clear the configuration cache."""
        self._config_cache.clear()
config_manager = PathConfigManager()

def get_environment_config(environment: Optional[str]=None) -> EnvironmentConfig:
    """Get environment configuration."""
    return config_manager.get_environment_config(environment)

def get_path_patterns(config_file: Optional[Path]=None) -> PathPatterns:
    """Get path patterns from configuration."""
    return config_manager.get_path_patterns(config_file)

def load_project_config(project_root: Path) -> Dict[str, Any]:
    """Load project-specific configuration."""
    return config_manager.load_project_config(project_root)
DEFAULT_PATTERNS = PathPatterns()
DEV_CONFIG = EnvironmentConfig.development()
PROD_CONFIG = EnvironmentConfig.production()
TEST_CONFIG = EnvironmentConfig.testing()