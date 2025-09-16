"""
Pytest configuration and fixtures for dependency injection testing.

This module provides test fixtures that support the DI architecture,
making it easy to test components in isolation with mocked dependencies.
"""

import logging
import sys
import types
import pytest
from pathlib import Path
from unittest.mock import Mock
from typing import Any, Dict, List

# Provide a minimal stub for the optional 'ollama' dependency if it's missing
if "ollama" not in sys.modules:  # pragma: no cover - testing utility
    class _DummyClient:
        def __init__(self, host=None):
            pass

        def chat(self, *args, **kwargs):
            class _Resp:
                message = type("msg", (), {"content": "{}"})()

            return _Resp()

    sys.modules["ollama"] = types.SimpleNamespace(Client=_DummyClient)

from agent_actions.core.graph.dependency_injection import (
    DependencyContainer,
    ProcessorFactory,
    registry,
)
from agent_actions.core.application_container import ApplicationContainer
from agent_actions.common.interfaces.interfaces import (
    IDataLoader,
    IDataProcessor,
    IGenerator,
    IOutputHandler,
)
from agent_actions.services.batch_service import BatchService
from agent_actions.core.path_manager import PathManager


@pytest.fixture
def test_config():
    """Provide test configuration."""
    return {
        'environment': 'testing',
        'agent_type': 'test_agent',
        'run_mode': 'sync',
        'logging': {'level': 'ERROR'},
        'processors': {
            'cache_enabled': False,
            'parallel_processing': False
        }
    }


@pytest.fixture
def mock_data_loader():
    """Create a mock data loader."""
    loader = Mock(spec=IDataLoader)
    loader.load_source_data.return_value = [
        {'source_guid': 'test-guid-1', 'content': 'test content 1'},
        {'source_guid': 'test-guid-2', 'content': 'test content 2'}
    ]
    return loader


@pytest.fixture
def mock_data_processor():
    """Create a mock data processor."""
    processor = Mock(spec=IDataProcessor)
    processor.process_item.return_value = [
        {'target_id': 'test-target-1', 'processed': 'data 1'},
        {'target_id': 'test-target-2', 'processed': 'data 2'}
    ]
    processor.separate_side_output.return_value = (
        [{'main': 'output'}],
        [{'side': 'output'}]
    )
    return processor


@pytest.fixture
def mock_data_generator():
    """Create a mock data generator."""
    generator = Mock(spec=IGenerator)
    generator.create_agent_with_data.return_value = (
        [{'generated': 'data'}],
        True  # executed flag
    )
    return generator


@pytest.fixture
def mock_batch_service():
    """Create a mock batch service."""
    service = Mock(spec=BatchService)
    service.submit_batch_job_from_data.return_value = {
        'type': 'passthrough',
        'data': [{'batch': 'processed'}]
    }
    return service


@pytest.fixture
def mock_path_manager():
    """Create a mock path manager."""
    manager = Mock(spec=PathManager)
    manager.get_project_root.return_value = Path('/test/project')
    manager.is_within_project.return_value = True
    return manager


@pytest.fixture
def mock_logger():
    """Create a mock logger."""
    logger = Mock(spec=logging.Logger)
    return logger


@pytest.fixture
def test_container(mock_data_loader, mock_data_processor, mock_data_generator, 
                  mock_batch_service, mock_path_manager, mock_logger):
    """Create a test dependency container with mocked services."""
    container = DependencyContainer()
    
    # Register mock implementations
    container.register_instance(IDataLoader, mock_data_loader)
    container.register_instance(IDataProcessor, mock_data_processor)
    container.register_instance(IGenerator, mock_data_generator)
    container.register_instance(BatchService, mock_batch_service)
    container.register_instance(PathManager, mock_path_manager)
    container.register_instance(logging.Logger, mock_logger)
    
    # Register additional mocks
    container.register_instance(IOutputHandler, Mock(spec=IOutputHandler))
    
    return container


@pytest.fixture
def test_processor_factory(test_container):
    """Create a processor factory with test dependencies."""
    return ProcessorFactory(test_container, registry)


@pytest.fixture
def test_application_container():
    """Create an application container configured for testing."""
    return ApplicationContainer.create_for_testing()


@pytest.fixture
def sample_agent_data():
    """Provide sample agent data for testing."""
    return [
        {
            'source_guid': 'test-guid-1',
            'content': 'Sample content for processing',
            'lineage': ['node_0_test']
        },
        {
            'source_guid': 'test-guid-2', 
            'content': 'Another sample content',
            'lineage': ['node_0_test', 'node_1_intermediate']
        }
    ]


@pytest.fixture
def temp_test_directory(tmp_path):
    """Create a temporary directory structure for testing."""
    # Create agent_io structure
    agent_io = tmp_path / "test_agent" / "agent_io"
    staging = agent_io / "staging"
    target = agent_io / "target"
    
    staging.mkdir(parents=True)
    target.mkdir(parents=True)
    
    # Create test files
    test_file1 = staging / "test_file1.json"
    test_file1.write_text('{"test": "data1"}')
    
    test_file2 = staging / "test_file2.json"
    test_file2.write_text('{"test": "data2"}')
    
    return {
        'agent_io': str(agent_io),
        'staging': str(staging),
        'target': str(target),
        'test_files': [str(test_file1), str(test_file2)]
    }


@pytest.fixture
def integration_container(test_config):
    """Create a container with real implementations for integration testing."""
    container = DependencyContainer()
    
    # Register real implementations for integration tests
    from agent_actions.processors.source_processor.source_data_loader import SourceDataLoader
    from agent_actions.processors.target_processor.data_processor import DataProcessor
    from agent_actions.processors.target_processor.data_generator import DataGenerator
    from agent_actions.services.batch_service import BatchService
    from agent_actions.core.path_manager import PathManager
    from logging import Logger, getLogger
    
    container.register_transient(IDataLoader, SourceDataLoader)
    container.register_transient(IDataProcessor, DataProcessor)
    container.register_transient(IGenerator, DataGenerator)
    container.register_singleton(BatchService, BatchService)
    container.register_singleton(PathManager, PathManager)
    container.register_singleton(Logger, getLogger("agent_actions"))
    
    return container


@pytest.fixture
def integration_processor_factory(integration_container):
    """Create processor factory with real implementations."""
    return ProcessorFactory(integration_container, registry)


# Async testing fixtures
@pytest.fixture
def event_loop():
    """Create an event loop for async testing."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Parametrized fixtures for different test scenarios
@pytest.fixture(params=['sync', 'batch'])
def run_mode(request):
    """Parametrized fixture for different run modes."""
    return request.param


@pytest.fixture(params=[True, False])
def executed_flag(request):
    """Parametrized fixture for generator execution scenarios."""
    return request.param


# Cleanup fixtures
@pytest.fixture(autouse=True)
def cleanup_registry():
    """Clean up registry after each test."""
    yield
    # Registry is global, so we don't clean it up unless necessary
    # This could be extended if needed


class TestDataBuilder:
    """Helper class for building test data."""
    
    @staticmethod
    def create_agent_config(agent_type: str = "test_agent", run_mode: str = "sync") -> Dict[str, Any]:
        """Create a test agent configuration."""
        return {
            'agent_type': agent_type,
            'run_mode': run_mode,
            'model': 'test-model',
            'temperature': 0.7,
            'max_tokens': 1000
        }
    
    @staticmethod
    def create_processor_data(count: int = 2) -> List[Dict[str, Any]]:
        """Create test processor data."""
        return [
            {
                'source_guid': f'test-guid-{i}',
                'content': f'Test content {i}',
                'lineage': [f'node_0_test_{i}']
            }
            for i in range(1, count + 1)
        ]
    
    @staticmethod
    def create_source_data(count: int = 2) -> List[Dict[str, Any]]:
        """Create test source data."""
        return [
            {
                'source_guid': f'test-guid-{i}',
                'content': f'Source content {i}',
                'metadata': {'type': 'test'}
            }
            for i in range(1, count + 1)
        ]


@pytest.fixture
def test_data_builder():
    """Provide the test data builder."""
    return TestDataBuilder