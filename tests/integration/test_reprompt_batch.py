"""
Integration tests for batch reprompt processing.

Tests the full batch reprompt flow through BatchProcessingService with validation UDFs.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from agent_actions.processing.recovery.validation import (
    reprompt_validation,
    _VALIDATION_REGISTRY,
)
from agent_actions.llm.providers.batch_client_base import BatchResult
from agent_actions.processing.types import RecoveryMetadata, RepromptMetadata


class TestBatchRepromptIntegration:
    """Integration tests for batch reprompt with BatchProcessingService."""

    def setup_method(self):
        """Clear registry and register test UDFs."""
        _VALIDATION_REGISTRY.clear()

        # Register validation UDF that checks for forbidden words
        @reprompt_validation("Response must not contain the word 'forbidden'")
        def check_no_forbidden_words(response: dict) -> bool:
            text = str(response).lower()
            return "forbidden" not in text

        # Register validation UDF for required fields
        @reprompt_validation("Response must contain 'title' and 'summary' fields")
        def check_required_fields(response: dict) -> bool:
            return "title" in response and "summary" in response

    def test_batch_reprompt_feedback_injected_into_resubmitted_batch(self):
        """
        CRITICAL TEST: Verify feedback is injected into prompts for reprompt batch.

        Flow:
        1. Initial batch returns 3 results, 1 fails validation
        2. Failed record resubmitted with feedback appended to prompt
        3. Verify resubmitted batch task has feedback in user_content
        4. Verify final result has reprompt metadata
        """
        from agent_actions.llm.batch.services.batch_processing_service import (
            BatchProcessingService,
        )
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        # Track submitted batch tasks to verify feedback injection
        submitted_tasks = []
        reprompt_records_captured = []

        def mock_prepare_tasks(
            agent_config, data, provider, output_directory=None, batch_name=None
        ):
            """Capture the records being prepared (which have feedback injected)."""
            reprompt_records_captured.extend(data)
            # Return mock PreparedBatchTasks
            from agent_actions.llm.batch.core.batch_models import (
                PreparedBatchTasks,
                BatchTaskPreparationStats,
            )

            tasks = [
                {"target_id": rec.get("target_id"), "user_content": rec.get("user_content")}
                for rec in data
            ]
            return PreparedBatchTasks(
                tasks=tasks,
                context_map={},
                stats=BatchTaskPreparationStats(total_items=len(data), included_items=len(data)),
            )

        def mock_submit_batch(tasks, batch_name, output_directory):
            submitted_tasks.append(tasks)
            return "reprompt_batch_123", BatchStatus.COMPLETED

        # Setup mock provider
        mock_provider = Mock()
        mock_provider.submit_batch = Mock(side_effect=mock_submit_batch)
        mock_provider.check_status = Mock(return_value=BatchStatus.COMPLETED)

        # First call: return initial results (one fails validation)
        # Second call: return reprompt result (passes validation)
        initial_results = [
            BatchResult(
                custom_id="rec1",
                content={"description": "safe content"},
                success=True,
                recovery_metadata=None,
            ),
            BatchResult(
                custom_id="rec2",
                content={"description": "This is a forbidden topic"},  # Fails validation
                success=True,
                recovery_metadata=None,
            ),
        ]

        reprompt_results = [
            BatchResult(
                custom_id="rec2",
                content={"description": "safe content after reprompt"},
                success=True,
                recovery_metadata=None,
            ),
        ]

        mock_provider.retrieve_results = Mock(return_value=reprompt_results)

        # Setup context map
        context_map = {
            "rec1": {
                "user_content": "Classify this book: Book 1",
                "target_id": "rec1",
            },
            "rec2": {
                "user_content": "Classify this book: Book 2",
                "target_id": "rec2",
            },
        }

        # Setup service
        mock_client_resolver = Mock()
        mock_context_manager = Mock()
        mock_result_processor = Mock()
        mock_registry_factory = Mock()

        service = BatchProcessingService(
            client_resolver=mock_client_resolver,
            context_manager=mock_context_manager,
            result_processor=mock_result_processor,
            registry_manager_factory=mock_registry_factory,
        )

        # Mock _wait_for_batch
        service._wait_for_batch = Mock(return_value=BatchStatus.COMPLETED)

        # Configure reprompt
        agent_config = {
            "reprompt": {
                "validation": "check_no_forbidden_words",
                "max_attempts": 2,
                "on_exhausted": "return_last",
            }
        }

        # Mock BatchTaskPreparator.prepare_tasks
        with patch(
            "agent_actions.llm_invocation.batch.processing.batch_task_preparator.BatchTaskPreparator"
        ) as mock_preparator_class:
            mock_preparator_instance = Mock()
            mock_preparator_instance.prepare_tasks = Mock(side_effect=mock_prepare_tasks)
            mock_preparator_class.return_value = mock_preparator_instance

            # Execute validation and reprompt
            final_results = service._validate_and_reprompt(
                results=initial_results,
                provider=mock_provider,
                context_map=context_map,
                output_directory="/tmp/test",
                file_name="test_batch",
                agent_config=agent_config,
            )

        # CRITICAL ASSERTION: Verify feedback was injected into resubmitted batch
        assert len(reprompt_records_captured) > 0, "No reprompt records were prepared"

        reprompt_record = reprompt_records_captured[0]  # First reprompted record
        user_content = reprompt_record.get("user_content", "")

        assert "---" in user_content, "Feedback separator not found in reprompt task"
        assert "Your response failed validation" in user_content, "Feedback message not found"
        assert "Response must not contain the word 'forbidden'" in user_content, (
            "UDF feedback not found"
        )
        assert "forbidden topic" in user_content, "Failed response not included in feedback"

        # Verify final results
        assert len(final_results) == 2

        # Find the reprompted record
        reprompted = [r for r in final_results if r.custom_id == "rec2"][0]
        assert reprompted.recovery_metadata is not None
        assert reprompted.recovery_metadata.reprompt is not None
        assert reprompted.recovery_metadata.reprompt.attempts == 1
        assert reprompted.recovery_metadata.reprompt.passed == True
        assert reprompted.recovery_metadata.reprompt.validation == "check_no_forbidden_words"

    def test_batch_reprompt_all_pass_validation_no_resubmit(self):
        """When all records pass validation, no reprompt batch should be submitted."""
        from agent_actions.llm.batch.services.batch_processing_service import (
            BatchProcessingService,
        )

        # Setup mock provider
        mock_provider = Mock()

        # All results pass validation
        initial_results = [
            BatchResult(
                custom_id="rec1",
                content={"description": "safe content"},
                success=True,
                recovery_metadata=None,
            ),
            BatchResult(
                custom_id="rec2",
                content={"description": "also safe content"},
                success=True,
                recovery_metadata=None,
            ),
        ]

        # Setup context map
        context_map = {
            "rec1": {"user_content": "Content 1", "target_id": "rec1"},
            "rec2": {"user_content": "Content 2", "target_id": "rec2"},
        }

        # Setup service
        service = BatchProcessingService(
            client_resolver=Mock(),
            context_manager=Mock(),
            result_processor=Mock(),
            registry_manager_factory=Mock(),
        )

        # Configure reprompt
        agent_config = {
            "reprompt": {
                "validation": "check_no_forbidden_words",
                "max_attempts": 2,
            }
        }

        # Execute validation and reprompt
        final_results = service._validate_and_reprompt(
            results=initial_results,
            provider=mock_provider,
            context_map=context_map,
            output_directory="/tmp/test",
            file_name="test_batch",
            agent_config=agent_config,
        )

        # ASSERTION: No batch should be submitted (all passed first time)
        mock_provider.submit_batch.assert_not_called()

        # Verify no reprompt metadata added (no reprompts occurred)
        for result in final_results:
            assert result.recovery_metadata is None or result.recovery_metadata.reprompt is None

    def test_batch_reprompt_partial_failure_only_failed_resubmitted(self):
        """Only records that fail validation should be resubmitted."""
        from agent_actions.llm.batch.services.batch_processing_service import (
            BatchProcessingService,
        )
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        # Track submitted tasks
        reprompt_records_captured = []

        def mock_prepare_tasks(
            agent_config, data, provider, output_directory=None, batch_name=None
        ):
            """Capture the records being prepared."""
            reprompt_records_captured.extend(data)
            from agent_actions.llm.batch.core.batch_models import (
                PreparedBatchTasks,
                BatchTaskPreparationStats,
            )

            tasks = [{"target_id": rec.get("target_id")} for rec in data]
            return PreparedBatchTasks(
                tasks=tasks,
                context_map={},
                stats=BatchTaskPreparationStats(total_items=len(data), included_items=len(data)),
            )

        def mock_submit_batch(tasks, batch_name, output_directory):
            return "reprompt_batch_123", BatchStatus.COMPLETED

        # Setup mock provider
        mock_provider = Mock()
        mock_provider.submit_batch = Mock(side_effect=mock_submit_batch)
        mock_provider.check_status = Mock(return_value=BatchStatus.COMPLETED)

        # Initial results: 3 records, 2 fail validation
        initial_results = [
            BatchResult(
                custom_id="rec1",
                content={"description": "safe content"},
                success=True,
                recovery_metadata=None,
            ),
            BatchResult(
                custom_id="rec2",
                content={"description": "forbidden topic"},
                success=True,
                recovery_metadata=None,
            ),
            BatchResult(
                custom_id="rec3",
                content={"description": "another forbidden topic"},
                success=True,
                recovery_metadata=None,
            ),
        ]

        # Reprompt results: only the 2 failed records
        reprompt_results = [
            BatchResult(
                custom_id="rec2",
                content={"description": "safe after reprompt"},
                success=True,
                recovery_metadata=None,
            ),
            BatchResult(
                custom_id="rec3",
                content={"description": "also safe after reprompt"},
                success=True,
                recovery_metadata=None,
            ),
        ]

        mock_provider.retrieve_results = Mock(return_value=reprompt_results)

        # Setup context map
        context_map = {
            "rec1": {"user_content": "Content 1", "target_id": "rec1"},
            "rec2": {"user_content": "Content 2", "target_id": "rec2"},
            "rec3": {"user_content": "Content 3", "target_id": "rec3"},
        }

        # Setup service
        service = BatchProcessingService(
            client_resolver=Mock(),
            context_manager=Mock(),
            result_processor=Mock(),
            registry_manager_factory=Mock(),
        )

        service._wait_for_batch = Mock(return_value=BatchStatus.COMPLETED)

        agent_config = {
            "reprompt": {
                "validation": "check_no_forbidden_words",
                "max_attempts": 2,
            }
        }

        # Mock BatchTaskPreparator
        with patch(
            "agent_actions.llm_invocation.batch.processing.batch_task_preparator.BatchTaskPreparator"
        ) as mock_preparator_class:
            mock_preparator_instance = Mock()
            mock_preparator_instance.prepare_tasks = Mock(side_effect=mock_prepare_tasks)
            mock_preparator_class.return_value = mock_preparator_instance

            # Execute
            final_results = service._validate_and_reprompt(
                results=initial_results,
                provider=mock_provider,
                context_map=context_map,
                output_directory="/tmp/test",
                file_name="test_batch",
                agent_config=agent_config,
            )

        # ASSERTION: Only 2 records should be resubmitted (not rec1)
        assert len(reprompt_records_captured) == 2, "Should only resubmit 2 failed records"

        # Verify only failed records have custom_ids rec2 and rec3
        resubmitted_ids = {rec.get("target_id") for rec in reprompt_records_captured}
        assert resubmitted_ids == {"rec2", "rec3"}

        # Verify rec1 has no reprompt metadata (never failed)
        rec1 = [r for r in final_results if r.custom_id == "rec1"][0]
        assert rec1.recovery_metadata is None or rec1.recovery_metadata.reprompt is None

    def test_batch_reprompt_exhausted_returns_last_response(self):
        """When reprompt exhausts attempts with on_exhausted=return_last."""
        from agent_actions.llm.batch.services.batch_processing_service import (
            BatchProcessingService,
        )
        from agent_actions.llm.batch.core.batch_constants import BatchStatus

        def mock_prepare_tasks(
            agent_config, data, provider, output_directory=None, batch_name=None
        ):
            """Mock task preparation."""
            from agent_actions.llm.batch.core.batch_models import (
                PreparedBatchTasks,
                BatchTaskPreparationStats,
            )

            tasks = [{"target_id": rec.get("target_id")} for rec in data]
            return PreparedBatchTasks(
                tasks=tasks,
                context_map={},
                stats=BatchTaskPreparationStats(total_items=len(data), included_items=len(data)),
            )

        # Setup mock provider
        mock_provider = Mock()
        mock_provider.submit_batch = Mock(return_value=("batch_123", BatchStatus.COMPLETED))
        mock_provider.check_status = Mock(return_value=BatchStatus.COMPLETED)

        # All reprompt attempts return invalid responses
        # Simulate 2 attempts, both fail validation
        reprompt_results_attempt1 = [
            BatchResult(
                custom_id="rec1",
                content={"description": "still forbidden"},
                success=True,
                recovery_metadata=None,
            ),
        ]

        mock_provider.retrieve_results = Mock(return_value=reprompt_results_attempt1)

        # Setup service
        service = BatchProcessingService(
            client_resolver=Mock(),
            context_manager=Mock(),
            result_processor=Mock(),
            registry_manager_factory=Mock(),
        )

        service._wait_for_batch = Mock(return_value=BatchStatus.COMPLETED)

        # Initial result fails validation
        initial_results = [
            BatchResult(
                custom_id="rec1",
                content={"description": "forbidden topic"},
                success=True,
                recovery_metadata=None,
            ),
        ]

        context_map = {
            "rec1": {"user_content": "Content 1", "target_id": "rec1"},
        }

        agent_config = {
            "reprompt": {
                "validation": "check_no_forbidden_words",
                "max_attempts": 2,
                "on_exhausted": "return_last",
            }
        }

        # Mock BatchTaskPreparator
        with patch(
            "agent_actions.llm_invocation.batch.processing.batch_task_preparator.BatchTaskPreparator"
        ) as mock_preparator_class:
            mock_preparator_instance = Mock()
            mock_preparator_instance.prepare_tasks = Mock(side_effect=mock_prepare_tasks)
            mock_preparator_class.return_value = mock_preparator_instance

            # Execute
            final_results = service._validate_and_reprompt(
                results=initial_results,
                provider=mock_provider,
                context_map=context_map,
                output_directory="/tmp/test",
                file_name="test_batch",
                agent_config=agent_config,
            )

        # ASSERTION: Should return last response even though validation failed
        assert len(final_results) == 1
        result = final_results[0]

        # Should have reprompt metadata showing exhaustion
        assert result.recovery_metadata is not None
        assert result.recovery_metadata.reprompt is not None
        assert result.recovery_metadata.reprompt.attempts == 2
        assert result.recovery_metadata.reprompt.passed == False
        assert result.recovery_metadata.reprompt.validation == "check_no_forbidden_words"

        # Content should be the last attempted response
        assert "forbidden" in result.content["description"].lower()

    def test_batch_reprompt_with_retry_both_metadata_present(self):
        """When both retry and reprompt enabled, both metadata should be present."""
        from agent_actions.llm.batch.services.batch_processing_service import (
            BatchProcessingService,
        )
        from agent_actions.llm.batch.core.batch_constants import BatchStatus
        from agent_actions.processing.types import RecoveryMetadata, RetryMetadata

        def mock_prepare_tasks(
            agent_config, data, provider, output_directory=None, batch_name=None
        ):
            """Mock task preparation."""
            from agent_actions.llm.batch.core.batch_models import (
                PreparedBatchTasks,
                BatchTaskPreparationStats,
            )

            tasks = [{"target_id": rec.get("target_id")} for rec in data]
            return PreparedBatchTasks(
                tasks=tasks,
                context_map={},
                stats=BatchTaskPreparationStats(total_items=len(data), included_items=len(data)),
            )

        # Setup mock provider
        mock_provider = Mock()
        mock_provider.submit_batch = Mock(return_value=("batch_123", BatchStatus.COMPLETED))
        mock_provider.check_status = Mock(return_value=BatchStatus.COMPLETED)

        reprompt_results = [
            BatchResult(
                custom_id="rec1",
                content={"description": "safe after reprompt"},
                success=True,
                recovery_metadata=None,
            ),
        ]

        mock_provider.retrieve_results = Mock(return_value=reprompt_results)

        # Setup service
        service = BatchProcessingService(
            client_resolver=Mock(),
            context_manager=Mock(),
            result_processor=Mock(),
            registry_manager_factory=Mock(),
        )

        service._wait_for_batch = Mock(return_value=BatchStatus.COMPLETED)

        # Initial result: already has retry metadata, fails reprompt validation
        initial_results = [
            BatchResult(
                custom_id="rec1",
                content={"description": "forbidden topic"},
                success=True,
                recovery_metadata=RecoveryMetadata(
                    retry=RetryMetadata(
                        attempts=2,
                        failures=1,
                        succeeded=True,
                        reason="timeout",
                        timestamp="2024-01-13T12:00:00Z",
                    )
                ),
            ),
        ]

        context_map = {
            "rec1": {"user_content": "Content 1", "target_id": "rec1"},
        }

        agent_config = {
            "reprompt": {
                "validation": "check_no_forbidden_words",
                "max_attempts": 2,
            }
        }

        # Mock BatchTaskPreparator
        with patch(
            "agent_actions.llm_invocation.batch.processing.batch_task_preparator.BatchTaskPreparator"
        ) as mock_preparator_class:
            mock_preparator_instance = Mock()
            mock_preparator_instance.prepare_tasks = Mock(side_effect=mock_prepare_tasks)
            mock_preparator_class.return_value = mock_preparator_instance

            # Execute
            final_results = service._validate_and_reprompt(
                results=initial_results,
                provider=mock_provider,
                context_map=context_map,
                output_directory="/tmp/test",
                file_name="test_batch",
                agent_config=agent_config,
            )

        # ASSERTION: Both retry and reprompt metadata should be present
        assert len(final_results) == 1
        result = final_results[0]

        assert result.recovery_metadata is not None

        # Verify retry metadata is preserved
        assert result.recovery_metadata.retry is not None
        assert result.recovery_metadata.retry.attempts == 2
        assert result.recovery_metadata.retry.succeeded == True

        # Verify reprompt metadata is added
        assert result.recovery_metadata.reprompt is not None
        assert result.recovery_metadata.reprompt.attempts == 1
        assert result.recovery_metadata.reprompt.passed == True
