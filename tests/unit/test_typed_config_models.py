"""Tests for typed configuration models."""

import pytest
import os
from unittest.mock import patch
from pydantic import ValidationError

from agent_actions.core.context.environment_config import EnvironmentConfig, Environment, LogLevel
from agent_actions.core.parser.config_schema import AgentConfig, WhereClauseConfig, FilterScope
from agent_actions.core.parser.processor_config import ProcessorConfig, DataProcessorConfig, ProcessingMode
from agent_actions.core.parser.vendor_config import OpenAIConfig, AnthropicConfig, VendorType
from agent_actions.core.parser.pipeline_config import PipelineConfig, StageConfig, ExecutionMode


class TestEnvironmentConfig:
    """Test environment configuration validation."""
    
    def test_default_environment_config(self):
        """Test default environment configuration."""
        config = EnvironmentConfig()
        
        assert config.agent_actions_env == Environment.DEVELOPMENT
        assert config.default_api_timeout == 120
        assert config.default_max_retries == 3
        assert config.debug_logging is False
        assert config.enable_parallel_processing is True
        
    @patch.dict(os.environ, {
        'OPENAI_API_KEY': 'test-openai-key-1234567890',
        'ANTHROPIC_API_KEY': 'test-claude-key-1234567890',
        'AGENT_ACTIONS_ENV': 'production'
    })
    def test_environment_config_from_env(self):
        """Test loading configuration from environment variables."""
        config = EnvironmentConfig()
        
        assert config.openai_api_key == 'test-openai-key-1234567890'
        assert config.claude_api_key == 'test-claude-key-1234567890'
        assert config.agent_actions_env == Environment.PRODUCTION
        
    def test_api_key_validation(self):
        """Test API key validation."""
        with pytest.raises(ValidationError) as exc_info:
            EnvironmentConfig(openai_api_key="short")
        
        assert "API key must be at least 10 characters long" in str(exc_info.value)
    
    @patch.dict(os.environ, {
        'ANTHROPIC_API_KEY': 'claude-key-123456789'
    })
    def test_effective_claude_key(self):
        """Test effective Claude key preference."""
        # Test claude_api_key preference (via ANTHROPIC_API_KEY)
        config = EnvironmentConfig()
        assert config.get_effective_claude_key() == "claude-key-123456789"

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'anthropic-key-123456789'})
    def test_effective_claude_key_fallback(self):
        """Test fallback to anthropic_api_key."""
        config = EnvironmentConfig()
        assert config.get_effective_claude_key() == "anthropic-key-123456789"

    def test_effective_claude_key_none(self):
        """Test no key returns None."""
        config = EnvironmentConfig()
        assert config.get_effective_claude_key() is None
    
    def test_environment_helpers(self):
        """Test environment helper methods."""
        dev_config = EnvironmentConfig(agent_actions_env=Environment.DEVELOPMENT)
        assert dev_config.is_development() is True
        assert dev_config.is_production() is False
        
        prod_config = EnvironmentConfig(agent_actions_env=Environment.PRODUCTION)
        assert prod_config.is_development() is False
        assert prod_config.is_production() is True
    
    def test_log_level_determination(self):
        """Test log level determination based on environment and debug setting."""
        # Debug enabled
        config = EnvironmentConfig(debug_logging=True)
        assert config.get_log_level() == LogLevel.DEBUG
        
        # Development environment
        config = EnvironmentConfig(
            agent_actions_env=Environment.DEVELOPMENT,
            debug_logging=False
        )
        assert config.get_log_level() == LogLevel.INFO
        
        # Production environment
        config = EnvironmentConfig(
            agent_actions_env=Environment.PRODUCTION,
            debug_logging=False
        )
        assert config.get_log_level() == LogLevel.WARNING


class TestAgentConfig:
    """Test enhanced agent configuration."""
    
    def test_basic_agent_config(self):
        """Test basic agent configuration."""
        config = AgentConfig(agent_type="test_agent")
        
        assert config.agent_type == "test_agent"
        assert config.is_operational is True
        assert config.dependencies == []
        assert config.parent == []
        assert config.use_few_shot_samples == 0
    
    def test_agent_config_with_all_fields(self):
        """Test agent configuration with all fields."""
        config = AgentConfig(
            agent_type="complex_agent",
            name="Complex Agent",
            model_vendor="openai",
            model_name="gpt-4",
            api_key="test-key-123456789",
            dependencies=["dep1", "dep2"],
            parent=["parent1"],
            prompt="Test prompt",
            schema_name="TestSchema",
            use_few_shot_samples=5,
            anthropic_version="2023-06-01",
            enable_prompt_caching=True
        )
        
        assert config.agent_type == "complex_agent"
        assert config.name == "Complex Agent"
        assert config.model_vendor == "openai"
        assert config.model_name == "gpt-4"
        assert config.dependencies == ["dep1", "dep2"]
        assert config.parent == ["parent1"]
        assert config.use_few_shot_samples == 5
        assert config.anthropic_version == "2023-06-01"
        assert config.enable_prompt_caching is True
    
    def test_where_clause_config(self):
        """Test WHERE clause configuration."""
        where_config = WhereClauseConfig(clause="field > 5")
        
        assert where_config.clause == "field > 5"
        assert where_config.scope == FilterScope.ITEM
        assert where_config.passthrough_on_empty is True
        
    def test_where_clause_validation(self):
        """Test WHERE clause validation."""
        # Valid clause
        config = WhereClauseConfig(clause="valid_field = 'value'")
        assert config.clause == "valid_field = 'value'"
        
        # Empty clause
        with pytest.raises(ValidationError) as exc_info:
            WhereClauseConfig(clause="")
        assert "String should have at least 1 character" in str(exc_info.value)
        
        # Dangerous pattern
        with pytest.raises(ValidationError) as exc_info:
            WhereClauseConfig(clause="__import__('os').system('rm -rf /')")
        assert "potentially dangerous operation: __import__" in str(exc_info.value)


class TestProcessorConfig:
    """Test processor configuration models."""
    
    def test_basic_processor_config(self):
        """Test basic processor configuration."""
        config = ProcessorConfig(name="test_processor")
        
        assert config.name == "test_processor"
        assert config.enabled is True
        assert config.processing_mode == ProcessingMode.AUTO
        assert config.timeout == 300
        assert config.retry_attempts == 3
    
    def test_data_processor_config(self):
        """Test data processor specific configuration."""
        config = DataProcessorConfig(
            name="data_proc",
            transformation_enabled=True,
            side_collection_handling="merge"
        )
        
        assert config.name == "data_proc"
        assert config.transformation_enabled is True
        assert config.side_collection_handling == "merge"
        assert config.validation_enabled is True


class TestVendorConfig:
    """Test vendor configuration models."""
    
    def test_openai_config(self):
        """Test OpenAI configuration."""
        config = OpenAIConfig(model_name="gpt-4o-mini")
        
        assert config.vendor_type == VendorType.OPENAI
        assert config.api_key_env_name == "OPENAI_API_KEY"
        assert config.model_name == "gpt-4o-mini"
        assert config.json_mode is True
    
    def test_anthropic_config(self):
        """Test Anthropic configuration."""
        config = AnthropicConfig(model_name="claude-3-sonnet-20240229")
        
        assert config.vendor_type == VendorType.ANTHROPIC
        assert config.api_key_env_name == "CLAUDE_API_KEY"
        assert config.model_name == "claude-3-sonnet-20240229"
        assert config.anthropic_version == "2023-06-01"
        assert config.enable_prompt_caching is False
    
    def test_model_validation(self):
        """Test model name validation."""
        # Valid OpenAI model
        config = OpenAIConfig(model_name="gpt-4o")
        assert config.model_name == "gpt-4o"
        
        # Invalid OpenAI model
        with pytest.raises(ValidationError):
            OpenAIConfig(model_name="invalid-model")
        
        # Valid Claude model
        config = AnthropicConfig(model_name="claude-3-haiku-20240307")
        assert config.model_name == "claude-3-haiku-20240307"
        
        # Invalid Claude model
        with pytest.raises(ValidationError):
            AnthropicConfig(model_name="gpt-4")


class TestPipelineConfig:
    """Test pipeline configuration models."""
    
    def test_stage_config(self):
        """Test stage configuration."""
        config = StageConfig(
            name="test_stage",
            stage_type="validation",
            description="Test validation stage"
        )
        
        assert config.name == "test_stage"
        assert config.stage_type == "validation"
        assert config.description == "Test validation stage"
        assert config.enabled is True
        assert config.depends_on == []
    
    def test_pipeline_config(self):
        """Test pipeline configuration."""
        stage1 = StageConfig(name="stage1", stage_type="validation")
        stage2 = StageConfig(name="stage2", stage_type="transformation", depends_on=["stage1"])
        
        config = PipelineConfig(
            name="test_pipeline",
            description="Test pipeline",
            execution_mode=ExecutionMode.SEQUENTIAL
        )
        
        config.add_stage(stage1)
        config.add_stage(stage2)
        
        assert config.name == "test_pipeline"
        assert len(config.stages) == 2
        assert config.get_stage("stage1") == stage1
        assert config.get_stage("stage2") == stage2
        
    def test_pipeline_dependency_validation(self):
        """Test pipeline dependency validation."""
        stage1 = StageConfig(name="stage1", stage_type="validation")
        stage2 = StageConfig(name="stage2", stage_type="transformation", depends_on=["stage1"])
        stage3 = StageConfig(name="stage3", stage_type="enrichment", depends_on=["nonexistent"])
        
        config = PipelineConfig(name="test_pipeline")
        config.add_stage(stage1)
        config.add_stage(stage2)
        config.add_stage(stage3)
        
        # Should raise error due to nonexistent dependency
        with pytest.raises(ValueError) as exc_info:
            config.validate_dependencies()
        assert "depends on undefined stage 'nonexistent'" in str(exc_info.value)
    
    def test_execution_order(self):
        """Test execution order determination."""
        stage1 = StageConfig(name="stage1", stage_type="validation")
        stage2 = StageConfig(name="stage2", stage_type="transformation", depends_on=["stage1"])
        stage3 = StageConfig(name="stage3", stage_type="enrichment", depends_on=["stage2"])
        
        config = PipelineConfig(name="test_pipeline")
        config.add_stage(stage3)  # Add in random order
        config.add_stage(stage1)
        config.add_stage(stage2)
        
        execution_order = config.get_execution_order()
        
        # Should be in dependency order
        assert execution_order == ["stage1", "stage2", "stage3"]
        
    def test_circular_dependency_detection(self):
        """Test circular dependency detection."""
        stage1 = StageConfig(name="stage1", stage_type="validation", depends_on=["stage2"])
        stage2 = StageConfig(name="stage2", stage_type="transformation", depends_on=["stage1"])
        
        config = PipelineConfig(name="test_pipeline")
        config.add_stage(stage1)
        config.add_stage(stage2)
        
        # Should detect circular dependency
        with pytest.raises(ValueError) as exc_info:
            config.get_execution_order()
        assert "Circular dependency detected" in str(exc_info.value)


class TestConfigIntegration:
    """Integration tests for configuration models."""
    
    def test_config_model_compatibility(self):
        """Test that all config models work together."""
        # Environment config
        env_config = EnvironmentConfig(
            agent_actions_env=Environment.DEVELOPMENT,
            debug_logging=True
        )
        
        # Agent config
        agent_config = AgentConfig(
            agent_type="test_agent",
            model_vendor="openai",
            model_name="gpt-4o-mini"
        )
        
        # Vendor config
        vendor_config = OpenAIConfig(model_name="gpt-4o-mini")
        
        # Processor config
        processor_config = DataProcessorConfig(name="test_processor")
        
        # Pipeline config
        pipeline_config = PipelineConfig(name="test_pipeline")
        
        # All should be valid
        assert env_config.is_development() is True
        assert agent_config.agent_type == "test_agent"
        assert vendor_config.vendor_type == VendorType.OPENAI
        assert processor_config.name == "test_processor"
        assert pipeline_config.name == "test_pipeline"
        
        # Test serialization/deserialization
        env_dict = env_config.model_dump(exclude_none=True)
        new_env_config = EnvironmentConfig.model_validate(env_dict)
        assert new_env_config.agent_actions_env == env_config.agent_actions_env


if __name__ == "__main__":
    pytest.main([__file__])