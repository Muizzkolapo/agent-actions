"""Tests for key_verifier.py — lightweight API key probing."""

from unittest.mock import MagicMock, patch

from agent_actions.validation.preflight.key_verifier import (
    ProbeResult,
    _probe_openai,
    verify_keys,
)


class TestProbeOpenai:
    """Unit tests for the OpenAI probe function."""

    def test_successful_probe(self):
        mock_client = MagicMock()
        with patch("openai.OpenAI", return_value=mock_client):
            result = _probe_openai("sk-validkey12345678901234567890")
        assert result.ok is True
        assert result.vendor == "openai"
        mock_client.models.list.assert_called_once()

    def test_auth_failure(self):
        from openai import AuthenticationError

        mock_client = MagicMock()
        mock_client.models.list.side_effect = AuthenticationError(
            message="Invalid API Key",
            response=MagicMock(status_code=401),
            body=None,
        )
        with patch("openai.OpenAI", return_value=mock_client):
            result = _probe_openai("sk-expired12345678901234567890")
        assert result.ok is False
        assert "Invalid API Key" in result.error

    def test_network_error_treated_as_ok(self):
        """Timeout/network errors are not auth failures — proceed anyway."""
        mock_client = MagicMock()
        mock_client.models.list.side_effect = TimeoutError("connect timeout")
        with patch("openai.OpenAI", return_value=mock_client):
            result = _probe_openai("sk-validkey12345678901234567890")
        assert result.ok is True

    def test_rate_limit_treated_as_ok(self):
        """429 rate limit is not an auth failure — proceed anyway."""
        from openai import RateLimitError

        mock_client = MagicMock()
        mock_client.models.list.side_effect = RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429),
            body=None,
        )
        with patch("openai.OpenAI", return_value=mock_client):
            result = _probe_openai("sk-validkey12345678901234567890")
        assert result.ok is True


class TestVerifyKeys:
    """Tests for the top-level verify_keys() function."""

    def test_parallel_execution(self):
        """Multiple vendors are probed and results returned."""
        ok_openai = ProbeResult(vendor="openai", ok=True)
        ok_groq = ProbeResult(vendor="groq", ok=True)

        from agent_actions.validation.preflight import key_verifier

        original_registry = key_verifier._PROBE_REGISTRY.copy()
        key_verifier._PROBE_REGISTRY["openai"] = lambda _key: ok_openai
        key_verifier._PROBE_REGISTRY["groq"] = lambda _key: ok_groq
        try:
            results = verify_keys(
                {
                    "openai": "sk-validkey12345678901234567890",
                    "groq": "gsk_validkey1234567890123456",
                }
            )
        finally:
            key_verifier._PROBE_REGISTRY.update(original_registry)

        assert len(results) == 2
        vendors = {r.vendor for r in results}
        assert vendors == {"openai", "groq"}
        assert all(r.ok for r in results)

    def test_vendor_without_probe_skipped(self):
        """Vendors not in the registry are silently skipped."""
        results = verify_keys({"cohere": "some-key-value"})
        assert len(results) == 0

    def test_empty_input(self):
        results = verify_keys({})
        assert len(results) == 0

    def test_auth_failure_propagated(self):
        """Auth failure from a probe is returned as ok=False."""
        fail = ProbeResult(vendor="openai", ok=False, error="Incorrect API key")

        with patch(
            "agent_actions.validation.preflight.key_verifier._probe_openai",
            return_value=fail,
        ):
            results = verify_keys({"openai": "sk-badkey123456789012345678901"})

        assert len(results) == 1
        assert results[0].ok is False
        assert "Incorrect API key" in results[0].error


class TestVerifyKeysIntegration:
    """Integration tests via WorkflowResolutionService.resolve_all()."""

    def test_verify_keys_flag_triggers_probes(self, monkeypatch):
        """When verify_keys=True, probes are called."""
        from agent_actions.validation.preflight.resolution_service import (
            WorkflowResolutionService,
        )

        monkeypatch.setenv("OPENAI_API_KEY", "sk-validkey12345678901234567890")
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        ok = ProbeResult(vendor="openai", ok=True)
        with patch(
            "agent_actions.validation.preflight.key_verifier.verify_keys",
            return_value=[ok],
        ) as mock_verify:
            svc = WorkflowResolutionService(
                action_configs={"summarizer": {"model_vendor": "openai"}},
                verify_keys=True,
            )
            result = svc.resolve_all()

        assert result.is_valid
        mock_verify.assert_called_once()

    def test_verify_keys_false_skips_probes(self, monkeypatch):
        """When verify_keys=False (default), no probes are made."""
        from agent_actions.validation.preflight.resolution_service import (
            WorkflowResolutionService,
        )

        monkeypatch.setenv("OPENAI_API_KEY", "sk-validkey12345678901234567890")
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        with patch(
            "agent_actions.validation.preflight.key_verifier.verify_keys",
        ) as mock_verify:
            svc = WorkflowResolutionService(
                action_configs={"summarizer": {"model_vendor": "openai"}},
                verify_keys=False,
            )
            svc.resolve_all()

        mock_verify.assert_not_called()

    def test_auth_failure_blocks_workflow(self, monkeypatch):
        """Invalid key detected by probe produces a blocking error."""
        from agent_actions.validation.preflight.resolution_service import (
            WorkflowResolutionService,
        )

        monkeypatch.setenv("OPENAI_API_KEY", "sk-expired1234567890123456789")
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        fail = ProbeResult(vendor="openai", ok=False, error="Invalid API Key")
        with patch(
            "agent_actions.validation.preflight.key_verifier.verify_keys",
            return_value=[fail],
        ):
            svc = WorkflowResolutionService(
                action_configs={"summarizer": {"model_vendor": "openai"}},
                verify_keys=True,
            )
            result = svc.resolve_all()

        assert not result.is_valid
        assert len(result.errors) == 1
        assert "invalid" in result.errors[0].message.lower()
        assert "openai" in result.errors[0].message

    def test_skip_env_validation_bypasses_probes(self, monkeypatch):
        """AA_SKIP_ENV_VALIDATION=1 skips probes even with verify_keys=True."""
        from agent_actions.validation.preflight.resolution_service import (
            WorkflowResolutionService,
        )

        monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-expired1234567890123456789")

        with patch(
            "agent_actions.validation.preflight.key_verifier.verify_keys",
        ) as mock_verify:
            svc = WorkflowResolutionService(
                action_configs={"summarizer": {"model_vendor": "openai"}},
                verify_keys=True,
            )
            svc.resolve_all()

        mock_verify.assert_not_called()

    def test_probes_skipped_when_keys_missing(self, monkeypatch):
        """If keys are missing (presence error), don't bother probing."""
        from agent_actions.validation.preflight.resolution_service import (
            WorkflowResolutionService,
        )

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        with patch(
            "agent_actions.validation.preflight.key_verifier.verify_keys",
        ) as mock_verify:
            svc = WorkflowResolutionService(
                action_configs={"summarizer": {"model_vendor": "openai"}},
                verify_keys=True,
            )
            result = svc.resolve_all()

        assert len(result.errors) == 1
        assert "not set" in result.errors[0].message
        mock_verify.assert_not_called()
