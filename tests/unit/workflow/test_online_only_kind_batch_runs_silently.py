"""A tool or hitl action under run_mode: batch runs online with no message."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from agent_actions.config.types import RunMode
from agent_actions.workflow.pipeline import ProcessingPipeline


def _params(config: dict) -> MagicMock:
    params = MagicMock()
    params.action_name = "split"
    params.action_config = config
    params.action_configs = {"split": config}
    return params


def _process(config: dict):
    with (
        patch("agent_actions.workflow.pipeline.create_processing_pipeline_from_params") as online,
        patch.object(ProcessingPipeline, "_build_pipeline_context", return_value=({}, {}, None)),
        patch.object(ProcessingPipeline, "_handle_batch_generation", return_value="batched"),
    ):
        online.return_value.process.return_value = "online"
        return ProcessingPipeline.process_file(_params(config))


@pytest.mark.parametrize("kind", ["tool", "hitl"])
def test_an_online_only_action_under_batch_runs_online_and_logs_no_warning(kind, caplog):
    with caplog.at_level(logging.WARNING, logger="agent_actions.workflow.pipeline"):
        path = _process({"kind": kind, "model_vendor": kind, "run_mode": RunMode.BATCH})

    assert path == "online"
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_an_llm_action_under_batch_still_takes_the_batch_path():
    assert _process({"kind": "llm", "model_vendor": "openai", "run_mode": RunMode.BATCH}) == (
        "batched"
    )
