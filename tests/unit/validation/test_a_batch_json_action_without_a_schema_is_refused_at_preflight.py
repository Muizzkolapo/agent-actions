"""A batch action in JSON mode with no schema is refused at preflight, before any work.

Batch submission refuses such an action ("Schema is required for batch processing when json_mode
is enabled"), while online runs it. Raised only at submit, the refusal came after the run had
already prepared the action's records; preflight now says it first, in the same words.
"""

from __future__ import annotations

import pytest

from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService


@pytest.fixture(autouse=True)
def _skip_key_presence_checks(monkeypatch):
    monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")


def _schema_errors(**config) -> list:
    configs = {"write_quiz": {"model_vendor": "openai", "model_name": "m", **config}}
    result = WorkflowResolutionService(action_configs=configs).resolve_all()
    return [e for e in result.errors if e.location.config_field == "schema"]


def test_a_batch_json_action_without_a_schema_is_refused():
    (error,) = _schema_errors(run_mode="batch")

    assert error.message == (
        "Action 'write_quiz': Schema is required for batch processing when json_mode is enabled."
    )
    assert error.hint == "Either provide a schema or set json_mode: false"
    assert error.location.agent_name == "write_quiz"


def test_json_mode_set_explicitly_is_refused_too():
    assert len(_schema_errors(run_mode="batch", json_mode=True)) == 1


def test_the_same_action_online_passes():
    assert _schema_errors(run_mode="online") == []


@pytest.mark.parametrize(
    "config",
    [
        {"schema": "quiz"},
        {"schema": {"type": "object", "properties": {"q": {"type": "string"}}}},
        {"schema_name": "quiz"},
        {"json_mode": False},
        {"kind": "tool"},
    ],
    ids=["schema", "inline-schema", "schema_name", "text-mode", "tool"],
)
def test_a_batch_action_that_needs_no_schema_passes(config):
    assert _schema_errors(run_mode="batch", **config) == []
