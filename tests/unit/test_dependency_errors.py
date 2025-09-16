"""
Unit tests for DependencyError exception handling.

Tests that classes properly raise DependencyError when required dependencies are not provided.
"""

import pytest
from unittest.mock import Mock, MagicMock

from agent_actions.cli.exceptions import DependencyError
from agent_actions.agents.processors.target_processor.target_content_processor import TargetContentProcessor
from agent_actions.agents.processors.target_processor.target_generator import TargetGenerator
from agent_actions.integrations.loaders.data_loaders.source_data_loader import SourceDataLoader
from agent_actions._internal.common.performance.cache import CacheManager
from agent_actions.core.agent_strategies import AgentStrategy


class TestDependencyErrors:
    """Test suite for DependencyError exception handling."""
    
    def test_target_content_processor_missing_source_loader(self):
        """Test TargetContentProcessor raises DependencyError when source_loader is missing."""
        config = {"agent_type": "test"}
        
        with pytest.raises(DependencyError) as exc_info:
            TargetContentProcessor(
                agent_config=config,
                agent_name="test_agent",
                idx=0,
                source_loader=None,  # Missing dependency
                data_generator=Mock(),
                data_processor=Mock(),
                batch_service=Mock()
            )
        
        assert "TargetContentProcessor" in str(exc_info.value)
        assert "source_loader" in str(exc_info.value)
        assert "Please ensure all dependencies are properly injected" in str(exc_info.value)
    
    def test_target_content_processor_missing_data_generator(self):
        """Test TargetContentProcessor raises DependencyError when data_generator is missing."""
        config = {"agent_type": "test"}
        
        with pytest.raises(DependencyError) as exc_info:
            TargetContentProcessor(
                agent_config=config,
                agent_name="test_agent",
                idx=0,
                source_loader=Mock(),
                data_generator=None,  # Missing dependency
                data_processor=Mock(),
                batch_service=Mock()
            )
        
        assert "TargetContentProcessor" in str(exc_info.value)
        assert "data_generator" in str(exc_info.value)
    
    def test_target_content_processor_missing_data_processor(self):
        """Test TargetContentProcessor raises DependencyError when data_processor is missing."""
        config = {"agent_type": "test"}
        
        with pytest.raises(DependencyError) as exc_info:
            TargetContentProcessor(
                agent_config=config,
                agent_name="test_agent",
                idx=0,
                source_loader=Mock(),
                data_generator=Mock(),
                data_processor=None,  # Missing dependency
                batch_service=Mock()
            )
        
        assert "TargetContentProcessor" in str(exc_info.value)
        assert "data_processor" in str(exc_info.value)
    
    def test_target_content_processor_missing_batch_service(self):
        """Test TargetContentProcessor raises DependencyError when batch_service is missing."""
        config = {"agent_type": "test"}
        
        with pytest.raises(DependencyError) as exc_info:
            TargetContentProcessor(
                agent_config=config,
                agent_name="test_agent",
                idx=0,
                source_loader=Mock(),
                data_generator=Mock(),
                data_processor=Mock(),
                batch_service=None  # Missing dependency
            )
        
        assert "TargetContentProcessor" in str(exc_info.value)
        assert "batch_service" in str(exc_info.value)
    
    def test_target_generator_missing_processor_factory(self):
        """Test TargetGenerator raises DependencyError when processor_factory is missing."""
        config = {"agent_type": "test"}
        
        with pytest.raises(DependencyError) as exc_info:
            TargetGenerator(
                agent_config=config,
                agent_name="test_agent",
                idx=0,
                processor_factory=None  # Missing dependency
            )
        
        assert "TargetGenerator" in str(exc_info.value)
        assert "processor_factory" in str(exc_info.value)
    
    def test_target_generator_static_method_missing_processor_factory(self):
        """Test TargetGenerator.generate raises DependencyError when processor_factory is missing."""
        config = {"agent_type": "test"}
        
        with pytest.raises(DependencyError) as exc_info:
            TargetGenerator.generate(
                agent_config=config,
                agent_name="test_agent",
                file_path="/test/path",
                base_directory="/test",
                output_directory="/output",
                idx=0,
                processor_factory=None  # Missing dependency
            )
        
        assert "TargetGenerator.generate" in str(exc_info.value)
        assert "processor_factory" in str(exc_info.value)
    
    def test_source_data_loader_missing_path_manager(self):
        """Test SourceDataLoader raises DependencyError when path_manager is missing."""
        with pytest.raises(DependencyError) as exc_info:
            SourceDataLoader(
                agent_name="test_agent",
                path_manager=None  # Missing dependency
            )
        
        assert "SourceDataLoader" in str(exc_info.value)
        assert "path_manager" in str(exc_info.value)
    
    def test_cache_manager_missing_logger_factory(self):
        """Test CacheManager raises DependencyError when logger_factory is missing."""
        with pytest.raises(DependencyError) as exc_info:
            CacheManager(logger_factory=None)
        
        assert "CacheManager" in str(exc_info.value)
        assert "logger_factory" in str(exc_info.value)
    
    def test_agent_strategy_missing_processor_factory(self):
        """Test AgentStrategy raises DependencyError when processor_factory is missing."""
        # AgentStrategy is abstract, so we need to test with a concrete implementation
        from agent_actions.core.agent_strategies import InitialStrategy
        
        strategy = InitialStrategy(processor_factory=None)
        config = {"agent_type": "test"}
        
        with pytest.raises(DependencyError) as exc_info:
            strategy._execute_generate_target(
                agent_config=config,
                agent_name="test_agent",
                file_path="/test/path",
                base_directory="/test",
                output_directory="/output",
                idx=0
            )
        
        assert "BaseAgentStrategy" in str(exc_info.value)
        assert "processor_factory" in str(exc_info.value)
    
    def test_dependency_error_attributes(self):
        """Test DependencyError has correct attributes."""
        error = DependencyError("TestClass", "test_dependency")
        
        assert error.class_name == "TestClass"
        assert error.missing_dependency == "test_dependency"
        assert "TestClass requires test_dependency to be provided" in str(error)
    
    def test_all_dependencies_provided_no_error(self):
        """Test that no error is raised when all dependencies are provided."""
        config = {"agent_type": "test"}
        
        # Create mock dependencies
        mock_source_loader = Mock()
        mock_data_generator = Mock()
        mock_data_processor = Mock()
        mock_batch_service = Mock()
        
        # Should not raise any exception
        processor = TargetContentProcessor(
            agent_config=config,
            agent_name="test_agent",
            idx=0,
            source_loader=mock_source_loader,
            data_generator=mock_data_generator,
            data_processor=mock_data_processor,
            batch_service=mock_batch_service
        )
        
        assert processor.source_loader is mock_source_loader
        assert processor.data_generator is mock_data_generator
        assert processor.data_processor is mock_data_processor
        assert processor.batch_service is mock_batch_service