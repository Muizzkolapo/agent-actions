"""
Pytest configuration and fixtures for dependency injection testing.

This module provides test fixtures that support the DI architecture,
making it easy to test components in isolation with mocked dependencies.
"""

import logging
import sys
import types
import time
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
from agent_actions.core.runtime.application_container import ApplicationContainer
from agent_actions.core.contracts.interfaces import (
    IDataLoader,
    IDataProcessor,
    IGenerator,
    IOutputHandler,
)
from agent_actions.tasks.services.batch_service import BatchService
from agent_actions.core.path_manager import PathManager
from tests.utils.env_vars import test_env_context
from tests.mocks.config import create_mock_config, create_mock_vendor, create_mock_data_loader


@pytest.fixture
def test_config():
    """Provide test configuration."""
    return create_mock_config()


@pytest.fixture
def test_env():
    """Provide test environment context."""
    with test_env_context():
        yield


@pytest.fixture
def mock_vendor():
    """Provide a mock vendor for testing."""
    return create_mock_vendor()


@pytest.fixture
def mock_data_loader():
    """Provide a mock data loader for testing."""
    return create_mock_data_loader()


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
    from agent_actions.agents.processors.source_processor.source_data_loader import SourceDataLoader
    from agent_actions.agents.processors.target_processor.data_processor import DataProcessor
    from agent_actions.agents.processors.target_processor.data_generator import DataGenerator
    from agent_actions.tasks.services.batch_service import BatchService
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


# Enhanced test infrastructure for comprehensive testing (CF-001)
# ================================================================

# Test framework imports for comprehensive testing
import hypothesis
from hypothesis import settings

# Framework imports for enhanced testing
from agent_actions.core.utils.processor_utils import ProcessorUtils
from agent_actions.agents.transformers.data_transformer import DataTransformer
from agent_actions.core.parser.where_parser import WhereClauseParser, SimpleWhereFilter

try:
    from agent_actions._internal.filters.secure_parser import SecureWhereClauseParser, SecurityContext
    SECURE_PARSER_AVAILABLE = True
except ImportError:
    SECURE_PARSER_AVAILABLE = False
    SecurityContext = None
    SecureWhereClauseParser = None

try:
    from tests.utils.test_utils import (
        TestState, CollectionManagementTestHelper, WhereClauseSecurityTestHelper,
        WorkflowOrchestrationTestHelper, PerformanceBenchmarkHelper,
        ThreadSafeDataGenerator, test_state, temporary_test_environment
    )
    TEST_UTILS_AVAILABLE = True
except ImportError:
    TEST_UTILS_AVAILABLE = False


# Configure hypothesis for comprehensive property-based testing
settings.register_profile("comprehensive",
    max_examples=50,  # Reduced for CI performance
    deadline=500,     # 0.5 second deadline per test
    database=None,    # Disable example database for CI
    suppress_health_check=[hypothesis.HealthCheck.too_slow]
)
settings.load_profile("comprehensive")


# Enhanced Test Data Generation Fixtures
@pytest.fixture(scope="session")
def qanalabs_test_patterns():
    """qanalabs production test patterns."""
    if not TEST_UTILS_AVAILABLE:
        # Fallback minimal patterns
        return [{
            "name": "basic_pattern",
            "remove_collection_fields": ["id", "url"],
            "side_collection_fields": ["content", "metadata"],
            "performance_threshold_ms": 50.0
        }]
    return CollectionManagementTestHelper.create_qanalabs_test_patterns()


@pytest.fixture(scope="function")
def enhanced_test_data(qanalabs_test_patterns):
    """Generate enhanced test data based on qanalabs patterns."""
    if not TEST_UTILS_AVAILABLE:
        # Fallback test data
        return [
            {"id": "1", "url": "test", "content": "sample", "metadata": {"type": "test"}},
            {"id": "2", "url": "test2", "content": "sample2", "metadata": {"type": "test"}}
        ]

    pattern = qanalabs_test_patterns[0]
    return CollectionManagementTestHelper.generate_test_data(
        pattern, item_count=10, add_nested_objects=True
    )


# Collection Management Test Fixtures
@pytest.fixture(scope="function")
def processor_utils_instance():
    """ProcessorUtils instance for testing."""
    return ProcessorUtils()


@pytest.fixture(scope="function")
def data_transformer_instance():
    """DataTransformer instance for testing."""
    return DataTransformer()


@pytest.fixture(scope="function")
def enhanced_agent_config():
    """Enhanced agent configuration for comprehensive testing."""
    return {
        "agent_type": "test_agent",
        "remove_collection": ["id", "url", "topic"],
        "side_collection": ["id", "url", "page_content", "bloom_details"],
        "json_mode": True,
        "granularity": "Record",
        "run_mode": "batch",
        "is_operational": True,
        "dependencies": [],
        "model_vendor": "openai",
        "model_name": "gpt-4o-mini",
        "use_few_shot_samples": 0
    }


# WHERE Clause Security Test Fixtures
@pytest.fixture(scope="function")
def where_parser():
    """Basic WHERE clause parser for testing."""
    return WhereClauseParser()


@pytest.fixture(scope="function")
def where_filter():
    """Simple WHERE filter for testing."""
    return SimpleWhereFilter()


@pytest.fixture(scope="function")
def secure_parser():
    """Secure WHERE clause parser if available."""
    if not SECURE_PARSER_AVAILABLE:
        pytest.skip("Secure parser not available")

    security_context = SecurityContext(
        allowed_fields=set(),
        max_clause_length=1000,
        max_conditions=10,
        max_evaluation_time_ms=100.0
    )
    return SecureWhereClauseParser(security_context)


@pytest.fixture(scope="function")
def qanalabs_where_test_cases():
    """WHERE clause test cases from qanalabs production."""
    if not TEST_UTILS_AVAILABLE:
        return [{
            'name': 'basic_test',
            'clause': 'status == "active"',
            'test_data': {'status': 'active'},
            'expected_result': True
        }]
    return WhereClauseSecurityTestHelper.get_legitimate_test_cases()


# Performance Testing Fixtures
@pytest.fixture(scope="function")
def performance_helper():
    """Performance benchmark helper."""
    if not TEST_UTILS_AVAILABLE:
        return Mock()
    return PerformanceBenchmarkHelper()


@pytest.fixture(scope="function")
def benchmark_thresholds():
    """Performance benchmark thresholds."""
    return {
        "collection_management": {
            "remove_collection_100_items_ms": 50.0,
            "side_collection_100_items_ms": 100.0,
            "data_integrity_validation_ms": 25.0
        },
        "where_clause": {
            "parse_simple_clause_ms": 5.0,
            "evaluate_1000_items_ms": 100.0,
            "security_validation_ms": 10.0
        },
        "workflow_orchestration": {
            "dependency_resolution_50_agents_ms": 100.0,
            "status_save_1000_agents_ms": 1000.0,
            "status_load_1000_agents_ms": 500.0
        }
    }


# Enhanced File System Test Fixtures
@pytest.fixture(scope="function")
def enhanced_temp_environment():
    """Enhanced temporary test environment with cleanup."""
    if TEST_UTILS_AVAILABLE:
        with temporary_test_environment() as env:
            yield env
    else:
        # Fallback implementation
        import tempfile
        import shutil

        temp_dir = tempfile.mkdtemp(prefix="agent_actions_test_")
        try:
            agent_io = Path(temp_dir) / "agent_io"
            agent_io.mkdir()
            (agent_io / "staging").mkdir()
            (agent_io / "target").mkdir()
            (agent_io / "artifacts").mkdir()

            yield {
                'temp_dir': temp_dir,
                'agent_io': str(agent_io),
                'staging': str(agent_io / "staging"),
                'target': str(agent_io / "target"),
                'artifacts': str(agent_io / "artifacts")
            }
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


# Test State Management
@pytest.fixture(scope="function")
def test_state_manager():
    """Test state manager for tracking test execution."""
    if TEST_UTILS_AVAILABLE:
        # Reset global test state
        test_state._test_runs.clear()
        test_state._performance_metrics.clear()
        test_state._security_violations.clear()
        test_state._data_integrity_checks.clear()
        return test_state
    else:
        return Mock()


# Enhanced pytest configuration
def pytest_configure(config):
    """Enhanced pytest configuration with custom markers."""
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "security: mark test as security-focused"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "performance: mark test as performance test"
    )
    config.addinivalue_line(
        "markers", "collection_management: mark test as collection management test"
    )
    config.addinivalue_line(
        "markers", "where_clause: mark test as WHERE clause test"
    )
    config.addinivalue_line(
        "markers", "workflow: mark test as workflow orchestration test"
    )


def pytest_collection_modifyitems(config, items):
    """Enhanced test collection with automatic marker assignment."""
    for item in items:
        # Add markers based on test names and file locations
        if "performance" in item.name.lower():
            item.add_marker(pytest.mark.performance)
        if "security" in item.name.lower():
            item.add_marker(pytest.mark.security)
        if "integration" in item.name.lower() or "e2e" in item.name.lower():
            item.add_marker(pytest.mark.integration)
        if any(keyword in item.name.lower() for keyword in ["large", "stress", "concurrent"]):
            item.add_marker(pytest.mark.slow)

        # Add markers based on file names
        if "collection_management" in str(item.fspath):
            item.add_marker(pytest.mark.collection_management)
        if "where_clause" in str(item.fspath):
            item.add_marker(pytest.mark.where_clause)
        if "workflow" in str(item.fspath):
            item.add_marker(pytest.mark.workflow)


# Enhanced test execution monitoring
@pytest.fixture(scope="function", autouse=True)
def enhanced_test_monitor(request):
    """Enhanced test execution monitoring."""
    test_name = request.node.name
    start_time = time.perf_counter()

    # Setup
    yield

    # Cleanup and monitoring
    duration = time.perf_counter() - start_time

    # Log slow tests
    if duration > 3.0:  # 3 second threshold
        print(f"\n[PERFORMANCE WARNING] Slow test: {test_name} took {duration:.2f}s")

    # Check for test markers and log appropriately
    if hasattr(request.node, 'iter_markers'):
        markers = [marker.name for marker in request.node.iter_markers()]
        if 'security' in markers and duration > 1.0:
            print(f"\n[SECURITY TEST] {test_name} completed in {duration:.2f}s")


# Enhanced session cleanup
@pytest.fixture(scope="session", autouse=True)
def enhanced_session_cleanup():
    """Enhanced session cleanup with comprehensive reporting."""
    yield

    if TEST_UTILS_AVAILABLE:
        summary = test_state.get_summary()

        print("\n" + "="*80)
        print("ENHANCED AGENT ACTIONS TEST SUITE SUMMARY")
        print("="*80)
        print(f"Total tests executed: {len(summary['test_runs'])}")
        print(f"Performance metrics collected: {len(summary['performance_metrics'])}")
        print(f"Security violations detected and blocked: {len(summary['security_violations'])}")
        print(f"Data integrity checks performed: {len(summary['data_integrity_checks'])}")

        if summary['security_violations']:
            print("\nSecurity Violations Blocked:")
            for violation in summary['security_violations'][-5:]:  # Show last 5
                print(f"  - {violation['type']}: {violation['details'][:60]}...")

        if summary['performance_metrics']:
            print("\nPerformance Metrics (samples):")
            for test_id, metrics in list(summary['performance_metrics'].items())[-3:]:  # Show last 3
                print(f"  - {test_id}: {metrics}")

        print("="*80)