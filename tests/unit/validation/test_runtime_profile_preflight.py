"""Preflight refuses what a named runtime cannot run, and warns where it cannot enforce."""

from __future__ import annotations

import pytest

from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService

BATCH_REFUSAL = "Action 'classify_local': vendor 'llamafile' does not support run_mode: batch."
JSON_OBJECT_WARNING = (
    "Action 'classify_local': vendor 'llamafile' does not enforce json_object output."
)
SCHEMA = {"name": "probe_reply", "fields": [{"id": "answer", "type": "string"}]}


def _action(vendor: str = "llamafile", **config: object) -> dict:
    return {
        "kind": "llm",
        "model_vendor": vendor,
        "model_name": "local",
        "api_key": "OPENAI_API_KEY",
        "base_url": None,
        "json_mode": True,
        "schema": SCHEMA,
        "schema_name": "",
        "run_mode": "online",
        **config,
    }


def _resolve(**actions: dict):
    return WorkflowResolutionService(action_configs=actions).resolve_all()


@pytest.fixture
def _no_key_checks(monkeypatch):
    monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")


@pytest.mark.usefixtures("_no_key_checks")
class TestBatch:
    def test_batch_on_llamafile_is_refused_by_name(self):
        result = _resolve(classify_local=_action(run_mode="batch"))

        errors = [e for e in result.errors if "batch" in e.message]
        assert [e.message for e in errors] == [BATCH_REFUSAL]
        assert errors[0].hint == "Set run_mode: online."
        assert errors[0].location.agent_name == "classify_local"

    def test_online_on_llamafile_is_allowed(self):
        result = _resolve(classify_local=_action())

        assert [e.message for e in result.errors if "batch" in e.message] == []

    def test_batch_on_openai_is_still_allowed(self):
        result = _resolve(summarize_cloud=_action("openai", run_mode="batch"))

        assert [e.message for e in result.errors if "batch" in e.message] == []


@pytest.mark.usefixtures("_no_key_checks")
class TestJsonObjectWarning:
    def _warnings(self, result) -> list[str]:
        return [w.message for w in result.warnings if "json_object" in w.message]

    def test_a_json_action_with_no_schema_on_llamafile_warns(self):
        result = _resolve(classify_local=_action(schema=None))

        assert self._warnings(result) == [JSON_OBJECT_WARNING]
        warning = next(w for w in result.warnings if "json_object" in w.message)
        assert warning.hint == "Add a schema to this action."
        assert result.errors == []

    def test_a_json_action_with_a_schema_on_llamafile_does_not_warn(self):
        assert self._warnings(_resolve(classify_local=_action())) == []

    def test_a_named_schema_counts_as_a_schema(self):
        result = _resolve(classify_local=_action(schema=None, schema_name="probe_reply"))

        assert self._warnings(result) == []

    def test_a_non_json_action_on_llamafile_does_not_warn(self):
        result = _resolve(classify_local=_action(schema=None, json_mode=False))

        assert self._warnings(result) == []

    def test_a_json_action_with_no_schema_on_openai_does_not_warn(self):
        result = _resolve(classify_local=_action("openai", schema=None))

        assert self._warnings(result) == []


class TestKeyPresence:
    def test_llamafile_needs_no_key_in_the_environment(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        result = _resolve(classify_local=_action(api_key=None))

        assert [e.message for e in result.errors if "API key" in e.message] == []

    def test_openai_still_needs_its_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        result = _resolve(summarize_cloud=_action("openai", api_key=None))

        assert [e.message for e in result.errors if "API key" in e.message] == [
            "API key environment variable 'OPENAI_API_KEY' is not set "
            "(required by action 'summarize_cloud', vendor 'openai')"
        ]
