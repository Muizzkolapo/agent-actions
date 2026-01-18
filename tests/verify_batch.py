import unittest
from unittest.mock import MagicMock, patch
import os
import sys

# Ensure we can import from root
sys.path.append(os.getcwd())

from agent_actions.orchestration.processing_pipeline import (
    ProcessingPipeline,
    PipelineConfig,
    BatchPipelineParams,
)


class TestBatchRefactor(unittest.TestCase):
    @patch("agent_actions.orchestration.processing_pipeline.BatchService")
    @patch("agent_actions.orchestration.processing_pipeline.FileReader")
    def test_batch_generation_calls_service_correctly(self, MockFileReader, MockBatchService):
        """Verify _handle_batch_generation calls BatchService.submit_batch_job with correct arguments."""

        # Setup mocks
        mock_batch_service = MockBatchService.return_value
        mock_batch_service.submit_batch_job.return_value = "batch_job_123"

        MockFileReader.return_value.read.return_value = [{"some": "data"}]

        # ProcessingPipeline instance (mocking dependencies)
        config = PipelineConfig(
            agent_config={"run_mode": "batch", "model_vendor": "openai"},
            agent_name="test_agent",
            idx=0,
        )
        mock_factory = MagicMock()

        generator = ProcessingPipeline(config, mock_factory)

        # Call the private method via static access or public process if possible
        # Since _handle_batch_generation is static but used by instance, we can call it via class
        params = BatchPipelineParams(
            pipeline_agent_config=config.agent_config,
            pipeline_agent_name="test_agent",
            batch_file_path="/path/to/input.json",
            batch_base_directory="/path/to",
            batch_output_directory="/path/to/output",
        )

        # Mock Path.mkdir to avoid filesystem access
        with (
            patch("pathlib.Path.mkdir") as mock_mkdir,
            patch("builtins.open", unittest.mock.mock_open()) as mock_file,
        ):
            result_path = ProcessingPipeline._handle_batch_generation(params)

        # Check call
        mock_batch_service.submit_batch_job.assert_called_once()
        args, kwargs = mock_batch_service.submit_batch_job.call_args

        # Verify args - exact signature match [agent_config, batch_name, data, output_directory]
        # (plus force which defaults to False)
        self.assertEqual(args[0], config.agent_config)  # agent_config
        self.assertEqual(args[1], "input.json")  # batch_name (derived from file name)
        self.assertEqual(args[2], [{"some": "data"}])  # data
        self.assertEqual(args[3], "/path/to/output")  # output_directory

        # Verify NO source_file_info in kwargs
        self.assertNotIn("source_file_info", kwargs)

        print("Batch verification passed: submit_batch_job called correctly!")


if __name__ == "__main__":
    unittest.main()
