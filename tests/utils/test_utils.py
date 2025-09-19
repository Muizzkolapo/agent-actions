"""
Shared test utilities for agent-actions framework.

This module provides thread-safe utilities for parallel test implementation,
supporting the comprehensive test plan for all critical framework features.

Key Features:
- Collection management test helpers (remove_collection, side_collection)
- WHERE clause security testing utilities
- Workflow orchestration test data generators
- Schema validation test helpers
- Thread-safe data generators for concurrent testing
- Performance benchmarking utilities
"""

import asyncio
import json
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Generator, Callable, Set
from unittest.mock import Mock, MagicMock, patch
import logging
import tempfile
import shutil


# Thread-safe singleton for test state management
class TestState:
    """Thread-safe singleton for managing test state across concurrent tests."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._test_runs = {}
            self._performance_metrics = {}
            self._security_violations = []
            self._data_integrity_checks = {}
            self._initialized = True

    def register_test_run(self, test_id: str, test_type: str, status: str = "running"):
        """Register a test run for tracking."""
        with self._lock:
            self._test_runs[test_id] = {
                'type': test_type,
                'status': status,
                'start_time': time.time(),
                'thread_id': threading.get_ident()
            }

    def complete_test_run(self, test_id: str, success: bool, metrics: Optional[Dict] = None):
        """Mark test run as complete with optional metrics."""
        with self._lock:
            if test_id in self._test_runs:
                self._test_runs[test_id].update({
                    'status': 'passed' if success else 'failed',
                    'end_time': time.time(),
                    'metrics': metrics or {}
                })

    def add_security_violation(self, test_id: str, violation_type: str, details: str):
        """Record security violation for analysis."""
        with self._lock:
            self._security_violations.append({
                'test_id': test_id,
                'type': violation_type,
                'details': details,
                'timestamp': time.time(),
                'thread_id': threading.get_ident()
            })

    def record_performance_metric(self, test_id: str, metric_name: str, value: float):
        """Record performance metric for benchmarking."""
        with self._lock:
            if test_id not in self._performance_metrics:
                self._performance_metrics[test_id] = {}
            self._performance_metrics[test_id][metric_name] = value

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all test state."""
        with self._lock:
            return {
                'test_runs': dict(self._test_runs),
                'performance_metrics': dict(self._performance_metrics),
                'security_violations': list(self._security_violations),
                'data_integrity_checks': dict(self._data_integrity_checks)
            }


@dataclass
class TestDataPattern:
    """Represents test data patterns based on qanalabs production usage."""

    name: str
    description: str
    remove_collection_fields: List[str] = field(default_factory=list)
    side_collection_fields: List[str] = field(default_factory=list)
    expected_output_schema: Optional[Dict] = None
    performance_threshold_ms: Optional[float] = None
    security_constraints: List[str] = field(default_factory=list)


class CollectionManagementTestHelper:
    """Thread-safe helper for testing collection management operations."""

    @staticmethod
    def create_qanalabs_test_patterns() -> List[TestDataPattern]:
        """Create test patterns based on real qanalabs production usage."""
        return [
            TestDataPattern(
                name="standard_fact_extraction",
                description="Standard pattern from fact_extractor agent",
                remove_collection_fields=['id', 'url', 'topic'],
                side_collection_fields=['id', 'url', 'page_content', 'bloom_details'],
                performance_threshold_ms=50.0
            ),
            TestDataPattern(
                name="secondary_processing",
                description="Secondary pattern for intermediate processing",
                remove_collection_fields=['id', 'url'],
                side_collection_fields=['id', 'url', 'page_content', 'bloom_details', 'summary'],
                performance_threshold_ms=75.0
            ),
            TestDataPattern(
                name="final_stage_processing",
                description="Final stage with minimal removal",
                remove_collection_fields=['id', 'url', 'page_content'],
                side_collection_fields=['id', 'url', 'topic', 'summary', 'page_content', 'bloom_details'],
                performance_threshold_ms=100.0
            ),
            TestDataPattern(
                name="empty_removal",
                description="No fields removed - passthrough scenario",
                remove_collection_fields=[],
                side_collection_fields=['id', 'url', 'page_content', 'bloom_details', 'topic'],
                performance_threshold_ms=25.0
            )
        ]

    @staticmethod
    def generate_test_data(
        pattern: TestDataPattern,
        item_count: int = 100,
        add_nested_objects: bool = True,
        add_large_content: bool = False
    ) -> List[Dict[str, Any]]:
        """Generate test data for collection management testing."""
        test_data = []

        for i in range(item_count):
            item = {
                'id': f'test-id-{i}',
                'url': f'https://test.example.com/item/{i}',
                'topic': f'Test Topic {i}',
                'page_content': _generate_content(large=add_large_content),
                'bloom_details': {
                    'level': f'L{(i % 6) + 1}',
                    'category': ['Remember', 'Understand', 'Apply', 'Analyze', 'Evaluate', 'Create'][i % 6],
                    'complexity': (i % 3) + 1
                },
                'summary': f'Summary for item {i}',
                'metadata': {
                    'created_at': f'2024-01-{(i % 28) + 1:02d}T10:00:00Z',
                    'source': 'test_generator',
                    'version': '1.0'
                }
            }

            if add_nested_objects:
                item['nested_data'] = {
                    'level1': {
                        'level2': {
                            'deep_field': f'deep_value_{i}',
                            'array_field': [f'item_{j}' for j in range(3)]
                        }
                    }
                }

            test_data.append(item)

        return test_data

    @staticmethod
    def validate_data_integrity(
        original_data: List[Dict],
        processed_data: List[Dict],
        pattern: TestDataPattern
    ) -> Dict[str, Any]:
        """Validate data integrity after collection management operations."""
        violations = []
        preserved_count = 0
        removed_count = 0

        for orig, proc in zip(original_data, processed_data):
            # Check that side_collection fields are preserved
            for field in pattern.side_collection_fields:
                if field in orig and field not in proc:
                    violations.append(f"Side collection field '{field}' was removed")
                elif field in orig and orig[field] != proc.get(field):
                    violations.append(f"Side collection field '{field}' was modified")
                else:
                    preserved_count += 1

            # Check that remove_collection fields are removed
            for field in pattern.remove_collection_fields:
                if field in proc:
                    violations.append(f"Remove collection field '{field}' was not removed")
                else:
                    removed_count += 1

        return {
            'violations': violations,
            'preserved_fields_count': preserved_count,
            'removed_fields_count': removed_count,
            'integrity_score': 1.0 - (len(violations) / max(1, len(original_data) * 10))
        }


class WhereClauseSecurityTestHelper:
    """Thread-safe helper for WHERE clause security testing."""

    @staticmethod
    def get_legitimate_test_cases() -> List[Dict[str, Any]]:
        """Get legitimate WHERE clause test cases from qanalabs production."""
        return [
            {
                'name': 'qanalabs_production_example',
                'clause': 'marked_result_is_correct == "Correct" and my_confidence_level == "High"',
                'test_data': {
                    'marked_result_is_correct': 'Correct',
                    'my_confidence_level': 'High'
                },
                'expected_result': True
            },
            {
                'name': 'simple_equality',
                'clause': 'status == "active"',
                'test_data': {'status': 'active'},
                'expected_result': True
            },
            {
                'name': 'numeric_comparison',
                'clause': 'score > 0.8 and attempts < 5',
                'test_data': {'score': 0.9, 'attempts': 3},
                'expected_result': True
            },
            {
                'name': 'string_contains',
                'clause': 'error_message CONTAINS "error"',
                'test_data': {'error_message': 'An error occurred'},
                'expected_result': True
            },
            {
                'name': 'complex_boolean_logic',
                'clause': '(priority == "high" or urgency == "critical") and status != "closed"',
                'test_data': {'priority': 'high', 'urgency': 'medium', 'status': 'open'},
                'expected_result': True
            }
        ]

    @staticmethod
    def get_security_attack_vectors() -> List[Dict[str, Any]]:
        """Get security attack vectors to test injection prevention."""
        return [
            {
                'name': 'code_injection_attempt',
                'clause': '__import__("os").system("rm -rf /")',
                'should_fail': True,
                'attack_type': 'code_injection'
            },
            {
                'name': 'eval_injection',
                'clause': 'eval("__import__(\'subprocess\').call([\'ls\', \'/\'])")',
                'should_fail': True,
                'attack_type': 'eval_injection'
            },
            {
                'name': 'attribute_access_attack',
                'clause': 'data.__class__.__bases__[0].__subclasses__()[104].__init__.__globals__["sys"]',
                'should_fail': True,
                'attack_type': 'attribute_traversal'
            },
            {
                'name': 'infinite_loop_attempt',
                'clause': 'True while True else False',
                'should_fail': True,
                'attack_type': 'infinite_loop'
            },
            {
                'name': 'function_call_injection',
                'clause': 'open("/etc/passwd").read()',
                'should_fail': True,
                'attack_type': 'function_injection'
            }
        ]

    @staticmethod
    def benchmark_performance(clause: str, test_data: Dict, iterations: int = 1000) -> Dict[str, float]:
        """Benchmark WHERE clause parsing and evaluation performance."""
        start_time = time.perf_counter()

        # Simulate parsing phase
        parse_times = []
        eval_times = []

        for _ in range(iterations):
            parse_start = time.perf_counter()
            # Simulate parsing (would call actual parser here)
            time.sleep(0.0001)  # Simulate parsing overhead
            parse_end = time.perf_counter()
            parse_times.append(parse_end - parse_start)

            eval_start = time.perf_counter()
            # Simulate evaluation (would call actual evaluator here)
            time.sleep(0.0001)  # Simulate evaluation overhead
            eval_end = time.perf_counter()
            eval_times.append(eval_end - eval_start)

        total_time = time.perf_counter() - start_time

        return {
            'total_time_ms': total_time * 1000,
            'avg_parse_time_ms': (sum(parse_times) / len(parse_times)) * 1000,
            'avg_eval_time_ms': (sum(eval_times) / len(eval_times)) * 1000,
            'operations_per_second': iterations / total_time,
            'iterations': iterations
        }


class WorkflowOrchestrationTestHelper:
    """Thread-safe helper for workflow orchestration testing."""

    @staticmethod
    def create_qanalabs_workflow_pattern() -> Dict[str, Any]:
        """Create test workflow based on qanalabs 15+ agent sequence."""
        return {
            'workflow_name': 'qanalabs_quiz_generation',
            'agents': [
                {
                    'name': 'fact_extractor',
                    'dependencies': [],
                    'is_operational': True,
                    'expected_execution_order': 1
                },
                {
                    'name': 'flatten_quotes',
                    'dependencies': ['fact_extractor'],
                    'is_operational': True,
                    'expected_execution_order': 2
                },
                {
                    'name': 'fact_questionability',
                    'dependencies': ['flatten_quotes'],
                    'is_operational': True,
                    'expected_execution_order': 3
                },
                {
                    'name': 'fact_explanation',
                    'dependencies': ['fact_questionability'],
                    'is_operational': True,
                    'expected_execution_order': 4
                },
                {
                    'name': 'ScenarioGenerator',
                    'dependencies': ['fact_explanation'],
                    'is_operational': True,
                    'expected_execution_order': 5
                },
                {
                    'name': 'AnswerLengthDistractorEditor_Stage1',
                    'dependencies': ['ScenarioGenerator'],
                    'is_operational': True,
                    'expected_execution_order': 6
                },
                {
                    'name': 'AnswerLengthDistractorEditor_Stage2',
                    'dependencies': ['AnswerLengthDistractorEditor_Stage1'],
                    'is_operational': True,
                    'expected_execution_order': 7
                },
                {
                    'name': 'AnswerLengthDistractorEditor_Stage3',
                    'dependencies': ['AnswerLengthDistractorEditor_Stage2'],
                    'is_operational': True,
                    'expected_execution_order': 8
                },
                {
                    'name': 'QuizTaker',
                    'dependencies': ['AnswerLengthDistractorEditor_Stage3'],
                    'is_operational': False,  # Disabled in production
                    'expected_execution_order': 9
                },
                {
                    'name': 'quiztaker_maker',
                    'dependencies': ['AnswerLengthDistractorEditor_Stage3'],
                    'is_operational': True,
                    'expected_execution_order': 9,
                    'where_clause': 'marked_result_is_correct == "Correct" and my_confidence_level == "High"'
                }
            ]
        }

    @staticmethod
    def create_complex_dependency_scenarios() -> List[Dict[str, Any]]:
        """Create complex dependency scenarios for testing."""
        return [
            {
                'name': 'linear_chain',
                'description': 'Simple linear dependency chain',
                'agents': ['A', 'B', 'C', 'D'],
                'dependencies': {'B': ['A'], 'C': ['B'], 'D': ['C']},
                'expected_order': ['A', 'B', 'C', 'D']
            },
            {
                'name': 'fan_out_fan_in',
                'description': 'Fan out from one agent, fan in to final',
                'agents': ['Start', 'Branch1', 'Branch2', 'Branch3', 'End'],
                'dependencies': {
                    'Branch1': ['Start'],
                    'Branch2': ['Start'],
                    'Branch3': ['Start'],
                    'End': ['Branch1', 'Branch2', 'Branch3']
                },
                'parallel_possibilities': [['Branch1', 'Branch2', 'Branch3']]
            },
            {
                'name': 'diamond_pattern',
                'description': 'Diamond dependency pattern',
                'agents': ['A', 'B', 'C', 'D'],
                'dependencies': {'B': ['A'], 'C': ['A'], 'D': ['B', 'C']},
                'parallel_possibilities': [['B', 'C']]
            },
            {
                'name': 'circular_dependency_invalid',
                'description': 'Invalid circular dependency',
                'agents': ['A', 'B', 'C'],
                'dependencies': {'B': ['A'], 'C': ['B'], 'A': ['C']},
                'should_fail': True,
                'error_type': 'circular_dependency'
            }
        ]


class SchemaValidationTestHelper:
    """Thread-safe helper for schema validation testing."""

    @staticmethod
    def get_qanalabs_schema_patterns() -> List[Dict[str, Any]]:
        """Get schema patterns from qanalabs production usage."""
        return [
            {
                'name': 'candidate_facts_list',
                'schema': {
                    'type': 'object',
                    'properties': {
                        'facts': {
                            'type': 'array',
                            'items': {
                                'type': 'object',
                                'properties': {
                                    'fact_text': {'type': 'string'},
                                    'questionability_score': {'type': 'number'},
                                    'explanation': {'type': 'string'}
                                },
                                'required': ['fact_text']
                            }
                        }
                    },
                    'required': ['facts']
                },
                'vendor_adaptations': {
                    'openai': 'function_calling',
                    'anthropic': 'tool_use',
                    'google': 'function_declaration'
                }
            },
            {
                'name': 'inline_schema_pattern',
                'schema': {
                    'sample_usage_scenario': 'string',
                    'code_example': 'string',
                    'complexity_level': 'integer'
                },
                'vendor_adaptations': {
                    'openai': 'json_schema',
                    'anthropic': 'structured_output'
                }
            }
        ]


class PerformanceBenchmarkHelper:
    """Thread-safe helper for performance benchmarking."""

    def __init__(self):
        self._metrics_lock = threading.Lock()
        self._metrics = {}

    @contextmanager
    def benchmark_context(self, test_name: str, operation: str):
        """Context manager for benchmarking operations."""
        start_time = time.perf_counter()
        start_memory = self._get_memory_usage()

        try:
            yield
        finally:
            end_time = time.perf_counter()
            end_memory = self._get_memory_usage()

            with self._metrics_lock:
                if test_name not in self._metrics:
                    self._metrics[test_name] = {}

                self._metrics[test_name][operation] = {
                    'duration_ms': (end_time - start_time) * 1000,
                    'memory_delta_mb': (end_memory - start_memory) / 1024 / 1024,
                    'timestamp': time.time(),
                    'thread_id': threading.get_ident()
                }

    def get_performance_summary(self) -> Dict[str, Any]:
        """Get summary of all performance metrics."""
        with self._metrics_lock:
            return dict(self._metrics)

    @staticmethod
    def _get_memory_usage() -> int:
        """Get current memory usage in bytes."""
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss
        except ImportError:
            # Fallback if psutil not available
            return 0


class ThreadSafeDataGenerator:
    """Thread-safe data generator for concurrent testing."""

    def __init__(self, seed: Optional[int] = None):
        self._lock = threading.Lock()
        self._counter = 0
        self._seed = seed or int(time.time())

    def generate_unique_id(self, prefix: str = "test") -> str:
        """Generate thread-safe unique ID."""
        with self._lock:
            self._counter += 1
            thread_id = threading.get_ident()
            return f"{prefix}_{thread_id}_{self._counter}_{uuid.uuid4().hex[:8]}"

    def generate_batch_data(self, count: int, data_type: str = "standard") -> List[Dict[str, Any]]:
        """Generate batch test data with thread safety."""
        data = []

        for i in range(count):
            unique_id = self.generate_unique_id("batch_item")

            item = {
                'source_guid': unique_id,
                'node_id': f"node_0_{uuid.uuid4()}",
                'batch_id': f"batch_{uuid.uuid4().hex[:8]}",
                'content': _generate_content(),
                'metadata': {
                    'generated_at': time.time(),
                    'thread_id': threading.get_ident(),
                    'data_type': data_type,
                    'sequence': i
                }
            }

            data.append(item)

        return data


# Utility functions
def _generate_content(large: bool = False) -> str:
    """Generate test content of varying sizes."""
    base_content = "This is test content for agent actions testing. " * 5

    if large:
        # Generate ~10KB of content for performance testing
        return base_content * 200
    else:
        return base_content


@contextmanager
def temporary_test_environment(cleanup: bool = True):
    """Create temporary test environment with proper cleanup."""
    temp_dir = tempfile.mkdtemp(prefix="agent_actions_test_")

    try:
        # Create standard directory structure
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
        if cleanup:
            shutil.rmtree(temp_dir, ignore_errors=True)


def create_mock_logger(name: str = "test_logger") -> Mock:
    """Create a mock logger with standard methods."""
    logger = Mock(spec=logging.Logger)
    logger.name = name
    logger.debug = Mock()
    logger.info = Mock()
    logger.warning = Mock()
    logger.error = Mock()
    logger.critical = Mock()
    return logger


def validate_test_isolation(test_function: Callable) -> Callable:
    """Decorator to validate test isolation and prevent side effects."""
    def wrapper(*args, **kwargs):
        # Record initial state
        initial_modules = set(sys.modules.keys())

        try:
            result = test_function(*args, **kwargs)
            return result
        finally:
            # Verify no new modules were permanently imported
            final_modules = set(sys.modules.keys())
            new_modules = final_modules - initial_modules

            # Log any concerning new modules
            concerning_modules = [m for m in new_modules if not m.startswith('test')]
            if concerning_modules:
                logger = logging.getLogger(__name__)
                logger.warning(f"Test {test_function.__name__} imported modules: {concerning_modules}")

    return wrapper


# Global test state instance
test_state = TestState()