import unittest
from unittest.mock import MagicMock, patch, ANY
import os
import shutil
from pathlib import Path

# Mock dependencies before importing modules that use them
import sys

# Ensure we can import from root
sys.path.append(os.getcwd())

from agent_actions.workflow.pipeline import ProcessingPipeline, PipelineConfig
from agent_actions.input.preprocessing.staging.initial_stage_pipeline import (
    process_initial_stage,
    InitialStageContext,
)
from agent_actions.config.di.container import ProcessorFactory
from agent_actions.processing.processor import RecordProcessor
from agent_actions.processing.types import ProcessingResult, ProcessingStatus


class TestRefactor(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path("test_output")
        self.test_dir.mkdir(exist_ok=True)
        self.source_dir = self.test_dir / "source"
        self.source_dir.mkdir(exist_ok=True)
        self.output_dir = self.test_dir / "output"
        self.output_dir.mkdir(exist_ok=True)

        # Create dummy input file
        self.input_file = self.test_dir / "input.txt"
        self.input_file.write_text("dummy content")

        # Create dummy JSON input
        self.json_file = self.test_dir / "input.json"
        self.json_file.write_text('[{"content": "dummy", "source_guid": "123"}]')

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    @patch("agent_actions.preprocessing.staging.initial_stage_pipeline.RecordProcessor")
    def test_initial_strategy_calls_record_processor(self, MockRecordProcessor):
        """Verify process_initial_stage uses RecordProcessor."""
        # Setup mock calls
        mock_instance = MockRecordProcessor.return_value
        mock_instance.process_batch.return_value = [
            ProcessingResult.success(data=[{"content": "processed"}])
        ]

        # Added model_vendor to satisfy preflight validation
        ctx = InitialStageContext(
            agent_config={"run_mode": "online", "model_vendor": "openai"},
            agent_name="test_agent",
            file_path=str(self.input_file),
            base_directory=str(self.test_dir),
            output_directory=str(self.output_dir),
        )

        process_initial_stage(ctx)

        # Verify RecordProcessor was instantiated and called
        # Note: RecordProcessor init might verify keys, but we mock it.
        # Check matching call arguments (kwargs)
        MockRecordProcessor.assert_called_with(
            {"run_mode": "online", "model_vendor": "openai"}, "test_agent"
        )
        mock_instance.process_batch.assert_called_once()
        print("InitialStrategy verified to use RecordProcessor!")

    @patch("agent_actions.orchestration.processing_pipeline.RecordProcessor")
    def test_standard_strategy_calls_record_processor(self, MockRecordProcessor):
        """Verify ProcessingPipeline uses RecordProcessor."""
        mock_instance = MockRecordProcessor.return_value
        mock_instance.process_batch.return_value = [
            ProcessingResult.success(data=[{"content": "processed"}])
        ]

        config = PipelineConfig(
            agent_config={"run_mode": "online", "model_vendor": "openai"},
            agent_name="test_agent",
            idx=0,
        )

        # Processor factory mock (not used for RecordProcessor creation anymore but needed for init)
        mock_factory = MagicMock(spec=ProcessorFactory)

        generator = ProcessingPipeline(config, mock_factory)

        generator.process(str(self.json_file), str(self.test_dir), str(self.output_dir))

        # Fixed assertion to match keyword arguments used in implementation
        MockRecordProcessor.assert_called_with(
            agent_config=config.agent_config, agent_name="test_agent"
        )
        mock_instance.process_batch.assert_called_once()
        print("StandardStrategy verified to use RecordProcessor!")


if __name__ == "__main__":
    unittest.main()
