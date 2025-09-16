"""
Integration tests for TargetContentProcessor with dependency injection.

These tests verify that the TargetContentProcessor works correctly with real
dependencies injected through the DI container.
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch

from agent_actions.core.runtime.application_container import ApplicationContainer
from agent_actions.agents.processors.target_processor.target_content_processor import TargetContentProcessor


class TestTargetContentProcessorIntegration:
    """Integration tests for TargetContentProcessor with DI."""
    
    def test_processor_creation_with_di(self, test_application_container, test_config):
        """Test that processor can be created with dependency injection."""
        # Arrange
        agent_config = test_config
        agent_name = "test_agent"
        idx = 0
        
        # Act
        processor = test_application_container.create_target_content_processor(
            agent_config=agent_config,
            agent_name=agent_name,
            idx=idx
        )
        
        # Assert
        assert isinstance(processor, TargetContentProcessor)
        assert processor.agent_config == agent_config
        assert processor.agent_name == agent_name
        assert processor.idx == idx
        
        # Verify dependencies are injected
        assert processor.source_loader is not None
        assert processor.data_generator is not None
        assert processor.data_processor is not None
        assert processor.batch_service is not None
    
    def test_process_with_mocked_dependencies(self, test_application_container, 
                                            sample_agent_data, test_config):
        """Test processing with mocked dependencies."""
        # Arrange
        processor = test_application_container.create_target_content_processor(
            agent_config=test_config,
            agent_name="test_agent",
            idx=0
        )
        
        file_path = "/test/path/data.json"
        
        # Act
        result = processor.process(sample_agent_data, file_path)
        
        # Assert
        assert isinstance(result, list)
        # Verify mocked dependencies were called
        processor.source_loader.load_source_data.assert_called_once_with(file_path)
        assert processor.data_generator.create_agent_with_data.call_count == len(sample_agent_data)
        assert processor.data_processor.process_item.call_count == len(sample_agent_data)
    
    def test_batch_mode_processing(self, test_application_container, sample_agent_data):
        """Test processing in batch mode."""
        # Arrange
        batch_config = {
            'agent_type': 'test_agent',
            'run_mode': 'batch'
        }
        
        processor = test_application_container.create_target_content_processor(
            agent_config=batch_config,
            agent_name="test_agent",
            idx=0
        )
        
        file_path = "/test/path/data.json"
        output_directory = "/test/output"
        
        # Act
        result = processor.process(sample_agent_data, file_path, output_directory)
        
        # Assert
        assert isinstance(result, list)
        processor.batch_service.submit_batch_job_from_data.assert_called_once_with(
            batch_config, "test_agent", sample_agent_data, output_directory
        )
    
    @pytest.mark.asyncio
    async def test_async_processing(self, test_application_container, 
                                   sample_agent_data, test_config):
        """Test async processing functionality."""
        # Arrange
        processor = test_application_container.create_target_content_processor(
            agent_config=test_config,
            agent_name="test_agent",
            idx=0
        )
        
        file_path = "/test/path/data.json"
        
        # Act
        result = await processor.process_async(sample_agent_data, file_path)
        
        # Assert
        assert isinstance(result, list)
        # Verify async processing called dependencies
        processor.source_loader.load_source_data.assert_called_once_with(file_path)
    
    def test_process_for_side_output(self, test_application_container, 
                                   sample_agent_data, test_config):
        """Test processing with side output separation."""
        # Arrange
        processor = test_application_container.create_target_content_processor(
            agent_config=test_config,
            agent_name="test_agent",
            idx=0
        )
        
        file_path = "/test/path/data.json"
        
        # Act
        main_output, side_output = processor.process_for_side_output(sample_agent_data, file_path)
        
        # Assert
        assert isinstance(main_output, list)
        assert isinstance(side_output, list)
        processor.data_processor.separate_side_output.assert_called_once()
    
    def test_process_file_level(self, test_application_container, test_config):
        """Test file-level processing functionality."""
        # Arrange
        processor = test_application_container.create_target_content_processor(
            agent_config=test_config,
            agent_name="test_agent",
            idx=0
        )
        
        file_level_data = [{
            'content': 'file level content',
            'source_guid': 'file-guid-1'
        }]
        
        # Act
        result = processor.process_file_level(file_level_data)
        
        # Assert
        assert isinstance(result, list)
        processor.data_generator.create_agent_with_data.assert_called_once()
        processor.data_processor.process_item.assert_called_once()
    
    def test_error_handling_in_processing(self, test_application_container, test_config):
        """Test error handling during processing."""
        # Arrange
        processor = test_application_container.create_target_content_processor(
            agent_config=test_config,
            agent_name="test_agent",
            idx=0
        )
        
        # Mock an error in data generation
        processor.data_generator.create_agent_with_data.side_effect = Exception("Generation failed")
        
        invalid_data = [{
            'content': 'content that will fail',
            'source_guid': 'fail-guid'
        }]
        
        # Act & Assert
        with pytest.raises(RuntimeError, match="Failed to process content"):
            processor.process(invalid_data, "/test/path")
    
    def test_dependency_isolation(self, test_application_container, test_config):
        """Test that each processor instance has isolated dependencies."""
        # Arrange & Act
        processor1 = test_application_container.create_target_content_processor(
            agent_config=test_config,
            agent_name="agent1",
            idx=0
        )
        
        processor2 = test_application_container.create_target_content_processor(
            agent_config=test_config,
            agent_name="agent2", 
            idx=1
        )
        
        # Assert
        assert processor1.agent_name != processor2.agent_name
        assert processor1.idx != processor2.idx
        # Dependencies should be separate instances (transient registration)
        assert processor1.data_generator is not processor2.data_generator
        assert processor1.data_processor is not processor2.data_processor
    
    def test_container_health_check(self, test_application_container):
        """Test application container health check."""
        # Act
        health = test_application_container.health_check()
        
        # Assert
        assert health['status'] == 'healthy'
        assert 'services' in health
        assert 'timestamp' in health
        assert health['services']['data_loader'] == 'healthy'
        assert health['services']['data_processor'] == 'healthy'
        assert health['services']['generator'] == 'healthy'
        assert health['services']['batch_service'] == 'healthy'


class TestProcessorWithRealDependencies:
    """Tests with real (non-mocked) dependencies for true integration testing."""
    
    @pytest.fixture
    def real_container(self):
        """Create container with real implementations."""
        return ApplicationContainer.create_for_environment('testing')
    
    @pytest.mark.slow
    def test_full_workflow_integration(self, real_container, temp_test_directory, test_config):
        """Test full processor workflow with real dependencies."""
        # This test would require real file system setup and might be slow
        # Mark with @pytest.mark.slow to run only when needed
        
        # Arrange
        processor = real_container.create_target_content_processor(
            agent_config=test_config,
            agent_name="test_agent",
            idx=0
        )
        
        test_data = [{
            'content': 'Real content for processing',
            'source_guid': 'real-guid-1'
        }]
        
        # Act
        with patch('agent_actions.processors.source_processor.source_data_loader.SourceDataLoader.load_source_data') as mock_load:
            mock_load.return_value = [{'source_guid': 'real-guid-1', 'content': 'source content'}]
            
            # This would test with real dependencies but mocked file system
            result = processor.process(test_data, temp_test_directory['test_files'][0])
        
        # Assert
        assert isinstance(result, list)
        mock_load.assert_called_once()


# Performance and load testing
class TestProcessorPerformance:
    """Performance tests for processor with DI."""
    
    @pytest.mark.performance
    def test_processor_creation_performance(self, test_application_container, test_config):
        """Test that processor creation with DI is performant."""
        import time
        
        # Arrange
        start_time = time.time()
        
        # Act - Create multiple processors
        processors = []
        for i in range(100):
            processor = test_application_container.create_target_content_processor(
                agent_config=test_config,
                agent_name=f"agent_{i}",
                idx=i
            )
            processors.append(processor)
        
        end_time = time.time()
        creation_time = end_time - start_time
        
        # Assert
        assert len(processors) == 100
        assert creation_time < 1.0  # Should create 100 processors in under 1 second
    
    @pytest.mark.performance  
    def test_concurrent_processing(self, test_application_container, test_config):
        """Test concurrent processor usage."""
        import concurrent.futures
        
        # Arrange
        def create_and_process(idx):
            processor = test_application_container.create_target_content_processor(
                agent_config=test_config,
                agent_name=f"concurrent_agent_{idx}",
                idx=idx
            )
            
            test_data = [{
                'content': f'Content {idx}',
                'source_guid': f'guid-{idx}'
            }]
            
            return processor.process(test_data, f"/test/path/{idx}")
        
        # Act
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(create_and_process, i) for i in range(10)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        # Assert
        assert len(results) == 10
        assert all(isinstance(result, list) for result in results)