"""With --verify-keys, an openai action with base_url is probed at that URL.

The fake SDK below accepts the key only at the local server, so a probe
that reaches the default endpoint is rejected. That makes "the probe went
to the right server" an assertion on the probe's outcome, not on a mock.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from openai import AuthenticationError
from pydantic import SecretStr

from agent_actions.validation.preflight.key_verifier import ProbeTarget, _probe_openai
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService

LOCAL = "http://localhost:8089/v1"
OTHER = "http://localhost:9099/v1"
KEY = "local-key-1234567890"


def _rejection():
    return AuthenticationError(
        message="Invalid API Key", response=MagicMock(status_code=401), body=None
    )


class _ServerThatKnowsTheKeyOnlyLocally:
    """SDK stand-in: models.list() succeeds only when built for LOCAL."""

    def __init__(self, api_key=None, base_url=None, **_: object):
        self.base_url = base_url
        self.models = MagicMock()
        if base_url != LOCAL:
            self.models.list.side_effect = _rejection()


class _ServerThatRejectsEveryKey:
    def __init__(self, api_key=None, base_url=None, **_: object):
        self.base_url = base_url
        self.models = MagicMock()
        self.models.list.side_effect = _rejection()


class TestProbeOpenaiTarget:
    def test_probe_with_base_url_reaches_that_server(self):
        with patch("openai.OpenAI", _ServerThatKnowsTheKeyOnlyLocally):
            result = _probe_openai(ProbeTarget("openai", KEY, base_url=LOCAL))

        assert result.ok is True
        assert result.base_url == LOCAL

    def test_probe_without_base_url_reaches_the_default_endpoint(self):
        with patch("openai.OpenAI", _ServerThatKnowsTheKeyOnlyLocally):
            result = _probe_openai(ProbeTarget("openai", KEY))

        assert result.ok is False
        assert "Invalid API Key" in result.error

    def test_rejection_at_a_base_url_reports_that_url(self):
        with patch("openai.OpenAI", _ServerThatRejectsEveryKey):
            result = _probe_openai(ProbeTarget("openai", KEY, base_url=LOCAL))

        assert result.ok is False
        assert result.base_url == LOCAL


class TestProbeTargetsFromConfig:
    @pytest.fixture(autouse=True)
    def _key_in_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", KEY)
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

    def test_local_and_cloud_actions_with_one_key_become_two_targets(self):
        svc = WorkflowResolutionService(
            action_configs={
                "classify_local": {"model_vendor": "openai", "base_url": LOCAL},
                "summarize_cloud": {"model_vendor": "openai"},
            }
        )

        _errors, _warnings, targets = svc._check_api_keys()

        assert {(t.vendor, t.base_url) for t in targets} == {("openai", LOCAL), ("openai", None)}
        assert {t.api_key for t in targets} == {KEY}

    def test_two_different_local_servers_become_two_targets(self):
        svc = WorkflowResolutionService(
            action_configs={
                "a": {"model_vendor": "openai", "base_url": LOCAL},
                "b": {"model_vendor": "openai", "base_url": OTHER},
            }
        )

        _errors, _warnings, targets = svc._check_api_keys()

        assert sorted(t.base_url for t in targets) == [LOCAL, OTHER]

    def test_only_the_openai_target_carries_a_base_url(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-key")
        svc = WorkflowResolutionService(
            action_configs={
                "classify_local": {"model_vendor": "openai", "base_url": LOCAL},
                "review": {"model_vendor": "anthropic", "base_url": LOCAL},
            }
        )

        _errors, _warnings, targets = svc._check_api_keys()

        assert {(t.vendor, t.base_url) for t in targets} == {
            ("openai", LOCAL),
            ("anthropic", None),
        }

    def test_two_actions_on_the_same_server_become_one_target(self):
        svc = WorkflowResolutionService(
            action_configs={
                "a": {"model_vendor": "openai", "base_url": LOCAL},
                "b": {"model_vendor": "openai", "base_url": LOCAL},
            }
        )

        _errors, _warnings, targets = svc._check_api_keys()

        assert [t.base_url for t in targets] == [LOCAL]


class TestVerifyKeysThroughPreflight:
    @pytest.fixture(autouse=True)
    def _key_in_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", KEY)
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

    def test_local_action_passes_when_only_the_local_server_accepts_the_key(self):
        svc = WorkflowResolutionService(
            action_configs={"classify_local": {"model_vendor": "openai", "base_url": LOCAL}},
            verify_keys=True,
        )

        with patch("openai.OpenAI", _ServerThatKnowsTheKeyOnlyLocally):
            result = svc.resolve_all()

        assert result.is_valid, [e.message for e in result.errors]

    def test_cloud_action_fails_when_the_default_endpoint_rejects_the_key(self):
        svc = WorkflowResolutionService(
            action_configs={"summarize_cloud": {"model_vendor": "openai"}},
            verify_keys=True,
        )

        with patch("openai.OpenAI", _ServerThatKnowsTheKeyOnlyLocally):
            result = svc.resolve_all()

        assert not result.is_valid
        assert "openai" in result.errors[0].message

    def test_rejection_at_a_local_server_names_the_url(self):
        svc = WorkflowResolutionService(
            action_configs={"classify_local": {"model_vendor": "openai", "base_url": LOCAL}},
            verify_keys=True,
        )

        with patch("openai.OpenAI", _ServerThatRejectsEveryKey):
            result = svc.resolve_all()

        assert not result.is_valid
        assert LOCAL in result.errors[0].message


class _ServerThatKnowsOnlyTheEnvKey:
    def __init__(self, api_key=None, base_url=None, **_: object):
        self.models = MagicMock()
        if api_key != KEY:
            self.models.list.side_effect = _rejection()


@pytest.mark.parametrize("api_key", [SecretStr("OPENAI_API_KEY"), "OPENAI_API_KEY"])
def test_the_probe_sends_the_value_of_the_env_var_api_key_names(monkeypatch, api_key):
    monkeypatch.setenv("OPENAI_API_KEY", KEY)
    monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)
    svc = WorkflowResolutionService(
        action_configs={"summarize": {"model_vendor": "openai", "api_key": api_key}},
        verify_keys=True,
    )

    with patch("openai.OpenAI", _ServerThatKnowsOnlyTheEnvKey):
        result = svc.resolve_all()

    assert result.is_valid, [e.message for e in result.errors]
