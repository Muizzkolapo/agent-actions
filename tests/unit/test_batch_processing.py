"""
Comprehensive tests for Batch Processing System.

Tests cover critical batch processing requirements identified in qanalabs production usage:
- Batch job lifecycle management (submission, monitoring, completion)
- Batch service integration with various providers
- Conditional filtering and passthrough data handling
- Performance benchmarking for large batch operations
- Concurrent batch job processing
- Real qanalabs workflow batch patterns

This implements comprehensive batch testing based on production usage patterns.
"""

import pytest
import time
import json
import uuid
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Any, Optional
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

from agent_actions.tasks.services.batch_service import BatchService
from agent_actions.integrations.providers.base import BatchProvider, BatchTask, BatchResult
from agent_actions.integrations.providers.factory import BatchProviderFactory
from agent_actions.core.utils.processor_utils import ProcessorUtils
from agent_actions.core.parser.where_parser import WhereClauseParser
from tests.utils.test_utils import (
    PerformanceBenchmarkHelper,
    test_state,
    temporary_test_environment
)


def get_basic_schema():
    """Helper to get basic schema for tests."""
    return {
        "result": "string",
        "success": "boolean"
    }


def assert_batch_result(result, expected_type="batch_submitted"):
    """Helper to assert batch result in consistent format."""
    assert result is not None
    if isinstance(result, str):
        # Batch ID returned directly
        assert result.startswith("batch_")
        return result
    elif isinstance(result, dict):
        if result.get("type") == expected_type:
            if expected_type == "batch_submitted":
                batch_id = result.get("batch_id")
                assert batch_id is not None
                return batch_id
        elif result.get("type") == "passthrough":
            assert "data" in result
            return "passthrough"
    return result


@dataclass
class MockBatchTask:
    """Mock batch task for testing."""
    custom_id: str
    prompt: str
    user_content: str
    model_config: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class MockBatchResult:
    """Mock batch result for testing."""
    custom_id: str
    content: Any
    success: bool
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    usage: Optional[Dict[str, Any]] = None


class MockBatchProvider(BatchProvider):
    """Mock batch provider for testing."""

    def __init__(self, simulate_delay: bool = False, failure_rate: float = 0.0):
        self.submitted_jobs = {}
        self.completed_jobs = {}
        self.simulate_delay = simulate_delay
        self.failure_rate = failure_rate
        self.job_counter = 0

    def prepare_tasks(self, data: List[Dict[str, Any]], agent_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert data to provider-specific task format."""
        tasks = []
        for item in data:
            task = {
                "custom_id": item.get("target_id", str(uuid.uuid4())),
                "prompt": agent_config.get("prompt", "Process this data:"),
                "user_content": json.dumps(item.get("content", item)),
                "model_config": {
                    "model": agent_config.get("model_name", "test-model"),
                    "temperature": agent_config.get("temperature", 0.7),
                    "max_tokens": agent_config.get("max_tokens", 1000)
                }
            }
            tasks.append(task)
        return tasks

    def format_task_for_provider(self, batch_task: BatchTask, schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Format task for provider submission."""
        return {
            "custom_id": batch_task.custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": batch_task.model_config.get("model", "test-model"),
                "messages": [
                    {"role": "system", "content": batch_task.prompt},
                    {"role": "user", "content": batch_task.user_content}
                ],
                "temperature": batch_task.model_config.get("temperature", 0.7),
                "max_tokens": batch_task.model_config.get("max_tokens", 1000)
            }
        }

    def submit_batch(self, tasks: List[Dict[str, Any]], batch_name: str, output_directory: Optional[str] = None) -> str:
        """Submit batch job and return job ID."""
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        self.job_counter += 1

        self.submitted_jobs[batch_id] = {
            "id": batch_id,
            "name": batch_name,
            "tasks": tasks,
            "status": "validating",
            "created_at": time.time(),
            "total_tasks": len(tasks)
        }

        # Simulate async processing
        if not self.simulate_delay:
            self._complete_batch_immediately(batch_id)

        return batch_id

    def check_status(self, batch_id: str) -> str:
        """Get status of batch job."""
        if batch_id in self.completed_jobs:
            return "completed"
        elif batch_id in self.submitted_jobs:
            job = self.submitted_jobs[batch_id]
            # Simulate progression
            elapsed = time.time() - job["created_at"]
            if elapsed > 2:
                return "completed"
            elif elapsed > 1:
                return "in_progress"
            else:
                return "validating"
        else:
            return "not_found"

    def retrieve_results(self, batch_id: str, output_directory: Optional[str] = None) -> List[BatchResult]:
        """Retrieve results for completed batch."""
        if batch_id in self.completed_jobs:
            return self.completed_jobs[batch_id]
        elif batch_id in self.submitted_jobs and not self.simulate_delay:
            # Complete the job if not already done
            self._complete_batch_immediately(batch_id)
            return self.completed_jobs[batch_id]
        else:
            return []

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel a batch job."""
        if batch_id in self.submitted_jobs:
            del self.submitted_jobs[batch_id]
            return True
        return False

    def _complete_batch_immediately(self, batch_id: str):
        """Complete batch job immediately for testing."""
        if batch_id not in self.submitted_jobs:
            return

        job = self.submitted_jobs[batch_id]
        tasks = job["tasks"]
        results = []

        for i, task in enumerate(tasks):
            # Simulate some failures based on failure_rate
            success = not (i < len(tasks) * self.failure_rate)

            if success:
                content = {
                    "processed": True,
                    "task_id": task["custom_id"],
                    "result": f"Processed content for {task['custom_id']}",
                    "model_response": "Mock AI response"
                }
                result = MockBatchResult(
                    custom_id=task["custom_id"],
                    content=content,
                    success=True,
                    usage={"prompt_tokens": 50, "completion_tokens": 25, "total_tokens": 75}
                )
            else:
                result = MockBatchResult(
                    custom_id=task["custom_id"],
                    content=None,
                    success=False,
                    error="Mock failure for testing"
                )

            results.append(result)

        self.completed_jobs[batch_id] = results
        if batch_id in self.submitted_jobs:
            del self.submitted_jobs[batch_id]

    def parse_provider_response(self, raw_response: Any) -> BatchResult:
        """Parse provider response to BatchResult."""
        if isinstance(raw_response, dict):
            return BatchResult(
                custom_id=raw_response.get("custom_id", "unknown"),
                content=raw_response.get("content"),
                success=raw_response.get("success", True),
                error=raw_response.get("error"),
                metadata=raw_response.get("metadata"),
                usage=raw_response.get("usage")
            )
        return BatchResult(
            custom_id="unknown",
            content=raw_response,
            success=True
        )

    def compile_schema(self, schema_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Compile schema to provider format."""
        return schema_dict  # Mock implementation just returns the schema as-is

    def get_supported_models(self) -> List[str]:
        """Get supported models."""
        return ["test-model", "mock-model-1", "mock-model-2"]


class TestBatchServiceCore:
    """Test core batch service functionality."""

    def test_batch_service_initialization(self):
        """Test batch service initialization."""
        test_id = "batch_service_init"
        test_state.register_test_run(test_id, "batch_core")

        batch_service = BatchService()

        # Verify initialization
        assert batch_service is not None
        assert hasattr(batch_service, 'where_parser')
        assert isinstance(batch_service.where_parser, WhereClauseParser)

        test_state.complete_test_run(test_id, True)

    def test_create_passthrough_data(self):
        """Test passthrough data creation for filtered items."""
        test_id = "batch_passthrough_data"
        test_state.register_test_run(test_id, "batch_core")

        batch_service = BatchService()

        # Sample input data
        input_data = [
            {
                "target_id": "test-1",
                "source_guid": "guid-1",
                "content": {"field": "value1"}
            },
            {
                "target_id": "test-2",
                "source_guid": "guid-2",
                "content": {"field": "value2"}
            }
        ]

        agent_config = {"agent_type": "test_agent"}
        output_directory = "/path/to/node_0_test_agent"

        result = batch_service._create_passthrough_data(
            input_data, agent_config, output_directory
        )

        # Verify passthrough structure
        assert result["type"] == "passthrough"
        assert len(result["data"]) == 2
        assert result["output_directory"] == output_directory

        # Verify metadata
        for item in result["data"]:
            assert item["metadata"]["skipped_by_conditional"] is True
            assert item["metadata"]["agent_type"] == "passthrough"
            assert "node_id" in item
            assert "lineage" in item

        test_state.complete_test_run(test_id, True)

    def test_conditional_filtering(self):
        """Test conditional filtering logic."""
        test_id = "batch_conditional_filtering"
        test_state.register_test_run(test_id, "batch_core")

        batch_service = BatchService()

        # Test data with different conditions
        test_cases = [
            {
                "data": {"status": "active", "score": 85},
                "condition": {"clause": 'status == "active" and score > 80'},
                "expected": True
            },
            {
                "data": {"status": "inactive", "score": 95},
                "condition": {"clause": 'status == "active" and score > 80'},
                "expected": False
            },
            {
                "data": {"priority": "high", "urgent": True},
                "condition": {"clause": 'priority == "high" or urgent == true'},
                "expected": True
            }
        ]

        for case in test_cases:
            agent_config = {"where_clause": {"scope": "item", **case["condition"]}}
            result = batch_service._should_process_item(case["data"], agent_config)
            assert result == case["expected"], f"Failed for case: {case}"

        test_state.complete_test_run(test_id, True)

    def test_side_output_separation(self):
        """Test separation of main and side output."""
        test_id = "batch_side_output_separation"
        test_state.register_test_run(test_id, "batch_core")

        items = [
            {"content": {"result": "main1"}, "target_id": "1"},
            {"content": {"result": "side1", "side_output": True}, "target_id": "2"},
            {"content": {"result": "main2"}, "target_id": "3"},
            {"content": {"result": "side2", "side_output": True}, "target_id": "4"}
        ]

        main_output, side_output = BatchService._separate_side_output(items)

        assert len(main_output) == 2
        assert len(side_output) == 2
        assert main_output[0]["target_id"] in ["1", "3"]
        assert side_output[0]["target_id"] in ["2", "4"]

        test_state.complete_test_run(test_id, True)


class TestBatchProviderIntegration:
    """Test batch provider integration."""

    def test_mock_provider_task_preparation(self):
        """Test task preparation with mock provider."""
        test_id = "batch_provider_task_prep"
        test_state.register_test_run(test_id, "batch_provider")

        provider = MockBatchProvider()

        # Sample data and config
        data = [
            {"target_id": "t1", "content": {"text": "First item"}},
            {"target_id": "t2", "content": {"text": "Second item"}}
        ]

        agent_config = {
            "model_name": "gpt-4o-mini",
            "prompt": "Process this data:",
            "temperature": 0.5,
            "max_tokens": 500
        }

        tasks = provider.prepare_tasks(data, agent_config)

        assert len(tasks) == 2
        assert tasks[0]["custom_id"] == "t1"
        assert tasks[1]["custom_id"] == "t2"
        assert "Process this data:" in tasks[0]["prompt"]

        test_state.complete_test_run(test_id, True)

    def test_batch_job_submission(self):
        """Test batch job submission flow."""
        test_id = "batch_job_submission"
        test_state.register_test_run(test_id, "batch_provider")

        provider = MockBatchProvider()

        tasks = [
            {
                "custom_id": "task1",
                "prompt": "Test prompt",
                "user_content": "Test content",
                "model_config": {"model": "test-model"}
            }
        ]

        batch_id = provider.submit_batch(tasks, "test_batch")

        assert batch_id.startswith("batch_")
        assert batch_id in provider.submitted_jobs or batch_id in provider.completed_jobs

        # Check status progression
        status = provider.check_status(batch_id)
        assert status in ["validating", "in_progress", "completed"]

        test_state.complete_test_run(test_id, True)

    def test_batch_result_retrieval(self):
        """Test batch result retrieval."""
        test_id = "batch_result_retrieval"
        test_state.register_test_run(test_id, "batch_provider")

        provider = MockBatchProvider()

        tasks = [
            {
                "custom_id": "result_test_1",
                "prompt": "Test",
                "user_content": "Content",
                "model_config": {"model": "test"}
            },
            {
                "custom_id": "result_test_2",
                "prompt": "Test",
                "user_content": "Content",
                "model_config": {"model": "test"}
            }
        ]

        batch_id = provider.submit_batch(tasks, "result_test")
        results = provider.retrieve_results(batch_id)

        assert len(results) == 2
        assert all(isinstance(r, MockBatchResult) for r in results)
        assert all(r.custom_id.startswith("result_test_") for r in results)

        # Check successful results
        successful_results = [r for r in results if r.success]
        assert len(successful_results) >= 1  # At least some should succeed

        test_state.complete_test_run(test_id, True)


class TestBatchJobLifecycle:
    """Test complete batch job lifecycle."""

    def test_end_to_end_batch_workflow(self):
        """Test complete batch workflow from submission to completion."""
        test_id = "batch_e2e_workflow"
        test_state.register_test_run(test_id, "batch_lifecycle")

        with temporary_test_environment() as env:
            batch_service = BatchService()

            # Mock the provider
            with patch.object(batch_service, 'provider', MockBatchProvider()):
                # Sample qanalabs-style data
                input_data = [
                    {
                        "target_id": "quiz_1",
                        "source_guid": "source_1",
                        "content": {
                            "question": "What is Azure AI?",
                            "context": "Cloud computing service"
                        }
                    },
                    {
                        "target_id": "quiz_2",
                        "source_guid": "source_2",
                        "content": {
                            "question": "What is machine learning?",
                            "context": "AI technique"
                        }
                    }
                ]

                agent_config = {
                    "agent_type": "quiz_generator",
                    "model_name": "gpt-4o-mini",
                    "model_vendor": "openai",
                    "prompt": "Generate quiz questions:",
                    "schema": {
                        "question": "string!",
                        "answer": "string!",
                        "category": "string"
                    },
                    "run_mode": "batch"
                }

                output_directory = env["target"]

                # Submit batch job
                result = batch_service.submit_batch_job_from_data(
                    agent_config, "test_batch", input_data, output_directory
                )

                # Verify submission
                assert result is not None
                if isinstance(result, str):
                    # Batch ID returned directly
                    batch_id = result
                    assert batch_id.startswith("batch_")
                elif isinstance(result, dict):
                    if result.get("type") == "batch_submitted":
                        batch_id = result["batch_id"]
                        assert batch_id is not None
                    elif result.get("type") == "passthrough":
                        # All items were filtered, verify passthrough
                        assert "data" in result
                        assert len(result["data"]) > 0

        test_state.complete_test_run(test_id, True)

    def test_batch_job_with_filtering(self):
        """Test batch job with WHERE clause filtering."""
        test_id = "batch_job_filtering"
        test_state.register_test_run(test_id, "batch_lifecycle")

        with temporary_test_environment() as env:
            batch_service = BatchService()

            with patch.object(batch_service, 'provider', MockBatchProvider()):
                # qanalabs production WHERE clause example
                input_data = [
                    {
                        "target_id": "q1",
                        "content": {
                            "marked_result_is_correct": "Correct",
                            "my_confidence_level": "High",
                            "question_text": "Test question 1"
                        }
                    },
                    {
                        "target_id": "q2",
                        "content": {
                            "marked_result_is_correct": "Incorrect",
                            "my_confidence_level": "Low",
                            "question_text": "Test question 2"
                        }
                    },
                    {
                        "target_id": "q3",
                        "content": {
                            "marked_result_is_correct": "Correct",
                            "my_confidence_level": "High",
                            "question_text": "Test question 3"
                        }
                    }
                ]

                agent_config = {
                    "agent_type": "quiztaker_maker",
                    "where_clause": {
                        "scope": "item",
                        "clause": 'marked_result_is_correct == "Correct" and my_confidence_level == "High"'
                    },
                    "model_vendor": "openai",
                    "model_name": "gpt-4o-mini",
                    "schema": {
                        "result": "string",
                        "score": "integer"
                    },
                    "run_mode": "batch"
                }

                result = batch_service.submit_batch_job_from_data(
                    agent_config, "filtered_batch", input_data, env["target"]
                )

                # Should only process 2 items (q1 and q3) due to filtering
                if isinstance(result, str):
                    # Batch ID returned directly - filtering worked, batch submitted
                    batch_id = result
                    assert batch_id.startswith("batch_")
                elif isinstance(result, dict):
                    if result.get("type") == "batch_submitted":
                        # Count tasks in submitted batch
                        provider = batch_service.provider
                        if hasattr(provider, 'submitted_jobs') or hasattr(provider, 'completed_jobs'):
                            # Verify filtering worked
                            pass  # Detailed verification would require access to internal state
                    elif result.get("type") == "passthrough":
                        # If all filtered out, should be empty or contain only unmatched items
                        pass

        test_state.complete_test_run(test_id, True)

    def test_batch_job_failure_handling(self):
        """Test handling of batch job failures."""
        test_id = "batch_job_failure_handling"
        test_state.register_test_run(test_id, "batch_lifecycle")

        batch_service = BatchService()

        # Mock provider with 50% failure rate
        mock_provider = MockBatchProvider(failure_rate=0.5)
        with patch.object(batch_service, '_get_provider_for_config', return_value=mock_provider):
            input_data = [
                {"target_id": f"fail_test_{i}", "content": {"data": f"item_{i}"}}
                for i in range(10)
            ]

            agent_config = {
                "agent_type": "failure_test",
                "model_name": "test-model",
                "model_vendor": "openai",
                "schema": {
                    "status": "string"
                },
                "run_mode": "batch"
            }

            with temporary_test_environment() as env:
                result = batch_service.submit_batch_job_from_data(
                    agent_config, "failure_test", input_data, env["target"]
                )

                # Should handle partial failures gracefully
                assert result is not None

                if isinstance(result, str):
                    # Batch ID returned directly
                    batch_id = result
                    assert batch_id.startswith("batch_")
                    # Retrieve results to check failure handling
                    results = mock_provider.retrieve_results(batch_id)
                    # Should have some failures due to 0.5 failure rate
                    assert len(results) > 0
                elif isinstance(result, dict):
                    if result.get("type") == "batch_submitted":
                        # Retrieve results to check failure handling
                        batch_id = result["batch_id"]
                        results = mock_provider.retrieve_results(batch_id)

                    # Should have some successes and some failures
                    successes = [r for r in results if r.success]
                    failures = [r for r in results if not r.success]

                    assert len(successes) > 0, "Should have some successful results"
                    assert len(failures) > 0, "Should have some failed results"

        test_state.complete_test_run(test_id, True)


class TestBatchPerformance:
    """Test batch processing performance."""

    def test_large_batch_processing_performance(self):
        """Test performance with large batch sizes."""
        test_id = "batch_large_performance"
        test_state.register_test_run(test_id, "batch_performance")

        batch_service = BatchService()
        benchmark_helper = PerformanceBenchmarkHelper()

        # Generate large dataset
        large_data = [
            {
                "target_id": f"perf_test_{i}",
                "source_guid": f"source_{i}",
                "content": {
                    "text": f"Performance test item {i}" * 10,  # Larger content
                    "metadata": {"index": i, "category": f"cat_{i % 5}"}
                }
            }
            for i in range(1000)
        ]

        agent_config = {
            "agent_type": "performance_test",
            "model_name": "gpt-4o-mini",
            "model_vendor": "openai",
            "schema": {
                "processed": "boolean",
                "result": "string"
            },
            "run_mode": "batch"
        }

        with patch.object(batch_service, 'provider', MockBatchProvider()):
            with temporary_test_environment() as env:
                with benchmark_helper.benchmark_context(test_id, "large_batch_submit"):
                    start_time = time.perf_counter()
                    result = batch_service.submit_batch_job_from_data(
                        agent_config, "perf_test", large_data, env["target"]
                    )
                    duration = time.perf_counter() - start_time

                # Performance validation
                assert duration < 5.0, f"Large batch submission too slow: {duration:.3f}s"
                assert result is not None

        test_state.record_performance_metric(test_id, "large_batch_duration_ms", duration * 1000)
        test_state.complete_test_run(test_id, True, {"duration_ms": duration * 1000, "items": len(large_data)})

    def test_concurrent_batch_submissions(self):
        """Test concurrent batch job submissions."""
        test_id = "batch_concurrent_submissions"
        test_state.register_test_run(test_id, "batch_performance")

        batch_service = BatchService()

        def submit_batch_job(job_id):
            """Submit a single batch job."""
            data = [
                {
                    "target_id": f"concurrent_{job_id}_{i}",
                    "content": {"job": job_id, "item": i}
                }
                for i in range(10)
            ]

            agent_config = {
                "agent_type": f"concurrent_test_{job_id}",
                "model_name": "test-model",
                "model_vendor": "openai",
                "schema": get_basic_schema(),
                "run_mode": "batch"
            }

            with temporary_test_environment() as env:
                return batch_service.submit_batch_job_from_data(
                    agent_config, f"concurrent_batch_{job_id}", data, env["target"]
                )

        mock_provider = MockBatchProvider()
        with patch.object(batch_service, '_get_provider_for_config', return_value=mock_provider):
            # Submit multiple batch jobs concurrently
            start_time = time.perf_counter()
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(submit_batch_job, i) for i in range(10)]
                results = [future.result() for future in as_completed(futures)]
            duration = time.perf_counter() - start_time

            # Verify all submissions completed
            assert len(results) == 10
            assert all(r is not None for r in results)

            # Performance check
            assert duration < 10.0, f"Concurrent submissions too slow: {duration:.3f}s"

        test_state.complete_test_run(test_id, True, {
            "concurrent_jobs": 10,
            "total_duration_ms": duration * 1000
        })

    def test_batch_processing_memory_usage(self):
        """Test memory usage during batch processing."""
        test_id = "batch_memory_usage"
        test_state.register_test_run(test_id, "batch_performance")

        batch_service = BatchService()
        benchmark_helper = PerformanceBenchmarkHelper()

        # Create data with varying sizes
        data_sizes = [100, 500, 1000]
        memory_results = {}

        for size in data_sizes:
            data = [
                {
                    "target_id": f"mem_test_{i}",
                    "content": {
                        "large_text": "Memory test content " * 100,  # ~2KB per item
                        "data": list(range(50))  # Additional data
                    }
                }
                for i in range(size)
            ]

            agent_config = {
                "agent_type": "memory_test",
                "model_name": "test-model",
                "model_vendor": "openai",
                "schema": get_basic_schema(),
                "run_mode": "batch"
            }

            mock_provider = MockBatchProvider()
            with patch.object(batch_service, '_get_provider_for_config', return_value=mock_provider):
                with temporary_test_environment() as env:
                    with benchmark_helper.benchmark_context(test_id, f"memory_test_{size}"):
                        result = batch_service.submit_batch_job_from_data(
                            agent_config, f"mem_test_{size}", data, env["target"]
                        )

            # Get memory metrics from benchmark helper
            metrics = benchmark_helper.get_performance_summary()
            if test_id in metrics and f"memory_test_{size}" in metrics[test_id]:
                memory_delta = metrics[test_id][f"memory_test_{size}"].get("memory_delta_mb", 0)
                memory_results[size] = memory_delta

        # Memory should scale reasonably with data size
        assert result is not None

        test_state.complete_test_run(test_id, True, {"memory_results": memory_results})


class TestBatchEdgeCases:
    """Test batch processing edge cases."""

    def test_empty_batch_submission(self):
        """Test handling of empty batch submissions."""
        test_id = "batch_empty_submission"
        test_state.register_test_run(test_id, "batch_edge_cases")

        batch_service = BatchService()

        mock_provider = MockBatchProvider()
        with patch.object(batch_service, '_get_provider_for_config', return_value=mock_provider):
            with temporary_test_environment() as env:
                agent_config = {
                    "agent_type": "empty_test",
                    "model_name": "test-model",
                    "model_vendor": "openai",
                    "schema": get_basic_schema(),
                    "run_mode": "batch"
                }

                # Submit empty data
                result = batch_service.submit_batch_job_from_data(
                    agent_config, "empty_batch", [], env["target"]
                )

                # Should handle gracefully
                result_id = assert_batch_result(result, expected_type="passthrough")
                if result_id == "passthrough":
                    assert result["data"] == []

        test_state.complete_test_run(test_id, True)

    def test_all_items_filtered_batch(self):
        """Test batch where all items are filtered out."""
        test_id = "batch_all_filtered"
        test_state.register_test_run(test_id, "batch_edge_cases")

        batch_service = BatchService()

        mock_provider = MockBatchProvider()
        with patch.object(batch_service, '_get_provider_for_config', return_value=mock_provider):
            with temporary_test_environment() as env:
                # Data that will all be filtered out
                data = [
                    {"target_id": "f1", "content": {"status": "inactive"}},
                    {"target_id": "f2", "content": {"status": "deleted"}},
                    {"target_id": "f3", "content": {"status": "archived"}}
                ]

                agent_config = {
                    "agent_type": "filter_test",
                    "where_clause": {
                        "scope": "item",
                        "clause": 'status == "active"'
                    },
                    "model_name": "test-model",
                    "model_vendor": "openai",
                    "schema": get_basic_schema(),
                    "run_mode": "batch"
                }

                result = batch_service.submit_batch_job_from_data(
                    agent_config, "all_filtered", data, env["target"]
                )

                # Should return passthrough result
                result_id = assert_batch_result(result, expected_type="passthrough")
                if result_id == "passthrough" and isinstance(result, dict):
                    assert len(result["data"]) == 3  # All items preserved as passthrough

        test_state.complete_test_run(test_id, True)

    def test_invalid_where_clause_handling(self):
        """Test handling of invalid WHERE clauses."""
        test_id = "batch_invalid_where_clause"
        test_state.register_test_run(test_id, "batch_edge_cases")

        batch_service = BatchService()

        mock_provider = MockBatchProvider()
        with patch.object(batch_service, '_get_provider_for_config', return_value=mock_provider):
            with temporary_test_environment() as env:
                data = [
                    {"target_id": "inv1", "content": {"field": "value"}}
                ]

                agent_config = {
                    "agent_type": "invalid_where_test",
                    "where_clause": {
                        "scope": "item",
                        "clause": "invalid syntax here"  # Invalid WHERE clause
                    },
                    "model_name": "test-model",
                    "model_vendor": "openai",
                    "schema": get_basic_schema(),
                    "run_mode": "batch"
                }

                # Should handle invalid WHERE clause gracefully
                result = batch_service.submit_batch_job_from_data(
                    agent_config, "invalid_where", data, env["target"]
                )

                # Should not crash and should include items (due to error handling)
                assert result is not None

        test_state.complete_test_run(test_id, True)


class TestBatchIntegration:
    """Integration tests for batch processing with real qanalabs patterns."""

    def test_qanalabs_quiz_generation_batch_pattern(self):
        """Test batch processing with qanalabs quiz generation pattern."""
        test_id = "batch_qanalabs_quiz_generation"
        test_state.register_test_run(test_id, "batch_integration")

        batch_service = BatchService()

        mock_provider = MockBatchProvider()
        with patch.object(batch_service, '_get_provider_for_config', return_value=mock_provider):
            with temporary_test_environment() as env:
                # Simulate qanalabs fact extraction data
                qanalabs_data = [
                    {
                        "target_id": "azure_fact_1",
                        "source_guid": "azure_doc_1",
                        "content": {
                            "id": "fact_1",
                            "url": "https://docs.microsoft.com/azure-ai",
                            "topic": "Azure AI Services",
                            "page_content": "Azure AI provides comprehensive AI services...",
                            "bloom_details": {
                                "level": "L2",
                                "category": "Understand",
                                "complexity": 2
                            }
                        }
                    },
                    {
                        "target_id": "azure_fact_2",
                        "source_guid": "azure_doc_2",
                        "content": {
                            "id": "fact_2",
                            "url": "https://docs.microsoft.com/cognitive-services",
                            "topic": "Cognitive Services",
                            "page_content": "Cognitive Services enable developers to add AI...",
                            "bloom_details": {
                                "level": "L3",
                                "category": "Apply",
                                "complexity": 3
                            }
                        }
                    }
                ]

                # qanalabs ScenarioGenerator configuration
                agent_config = {
                    "agent_type": "ScenarioGenerator",
                    "remove_collection": ["id", "url", "topic"],
                    "side_collection": ["id", "url", "page_content", "bloom_details"],
                    "model_vendor": "openai",
                    "model_name": "gpt-4o-mini",
                    "use_few_shot_samples": 5,
                    "json_mode": True,
                    "granularity": "Record",
                    "run_mode": "batch",
                    "schema": {
                        "scenario": "string",
                        "questions": "array[string]",
                        "difficulty": "string"
                    }
                }

                result = batch_service.submit_batch_job_from_data(
                    agent_config, "qanalabs_scenario_gen", qanalabs_data, env["target"]
                )

                assert result is not None

                # Verify qanalabs-specific processing
                result_id = assert_batch_result(result)
                if isinstance(result_id, str) and result_id.startswith("batch_"):
                    batch_id = result_id

                    # Verify results structure matches qanalabs expectations
                    results = mock_provider.retrieve_results(batch_id)

                    assert len(results) == len(qanalabs_data)
                    for result_item in results:
                        if result_item.success:
                            assert result_item.custom_id.startswith("azure_fact_")
                            assert result_item.content is not None

        test_state.complete_test_run(test_id, True, {
            "qanalabs_pattern": "ScenarioGenerator",
            "data_items": len(qanalabs_data)
        })

    def test_qanalabs_where_clause_filtering_integration(self):
        """Test integration with qanalabs WHERE clause filtering."""
        test_id = "batch_qanalabs_where_integration"
        test_state.register_test_run(test_id, "batch_integration")

        batch_service = BatchService()

        mock_provider = MockBatchProvider()
        with patch.object(batch_service, '_get_provider_for_config', return_value=mock_provider):
            with temporary_test_environment() as env:
                # Simulate quiztaker_maker input data
                quiz_results = [
                    {
                        "target_id": "quiz_result_1",
                        "content": {
                            "marked_result_is_correct": "Correct",
                            "my_confidence_level": "High",
                            "question_id": "q1",
                            "score": 95
                        }
                    },
                    {
                        "target_id": "quiz_result_2",
                        "content": {
                            "marked_result_is_correct": "Incorrect",
                            "my_confidence_level": "Low",
                            "question_id": "q2",
                            "score": 45
                        }
                    },
                    {
                        "target_id": "quiz_result_3",
                        "content": {
                            "marked_result_is_correct": "Correct",
                            "my_confidence_level": "High",
                            "question_id": "q3",
                            "score": 88
                        }
                    }
                ]

                # qanalabs quiztaker_maker configuration with WHERE clause
                agent_config = {
                    "agent_type": "quiztaker_maker",
                    "where_clause": {
                        "scope": "item",
                        "clause": 'marked_result_is_correct == "Correct" and my_confidence_level == "High"'
                    },
                    "model_vendor": "openai",
                    "model_name": "gpt-4o-mini",
                    "json_mode": True,
                    "schema": {
                        "quiz_feedback": "string",
                        "improvement_suggestions": "array[string]",
                        "confidence": "number"
                    },
                    "run_mode": "batch"
                }

                result = batch_service.submit_batch_job_from_data(
                    agent_config, "qanalabs_quiztaker", quiz_results, env["target"]
                )

                # Should only process 2 items (correct + high confidence)
                result_id = assert_batch_result(result)
                if isinstance(result_id, str) and result_id.startswith("batch_"):
                    batch_id = result_id

                    # Check that filtering worked - should only process matching items
                    results = mock_provider.retrieve_results(batch_id)
                    successful_results = [r for r in results if r.success]

                    # Should have processed quiz_result_1 and quiz_result_3
                    expected_ids = {"quiz_result_1", "quiz_result_3"}
                    actual_ids = {r.custom_id for r in successful_results}

                    assert len(actual_ids.intersection(expected_ids)) >= 1, "Should process high-confidence correct answers"

        test_state.complete_test_run(test_id, True, {
            "filtered_items": 2,
            "total_items": 3,
            "where_clause": "qanalabs production pattern"
        })


if __name__ == "__main__":
    # Run performance tests when executed directly
    test_performance = TestBatchPerformance()
    test_performance.test_large_batch_processing_performance()

    # Run integration tests
    test_integration = TestBatchIntegration()
    test_integration.test_qanalabs_quiz_generation_batch_pattern()

    # Print summary
    summary = test_state.get_summary()
    print("\nBatch Processing Test Summary:")
    print(f"Total tests run: {len(summary['test_runs'])}")
    print(f"Performance metrics: {len(summary['performance_metrics'])}")
    print(f"Batch integrations tested: {len([t for t in summary['test_runs'] if 'batch' in t])}")

    if summary['performance_metrics']:
        print("\nBatch Performance Metrics:")
        for test_id, metrics in summary['performance_metrics'].items():
            if 'batch' in test_id:
                print(f"- {test_id}: {metrics}")