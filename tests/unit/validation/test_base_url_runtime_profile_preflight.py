"""A named OpenAI-compatible runtime sends to base_url, so preflight allows it."""

from __future__ import annotations

import pytest

from agent_actions.llm.config.runtime_profiles import RUNTIME_PROFILES
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService


@pytest.fixture(autouse=True)
def _skip_key_presence_checks(monkeypatch):
    monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")


@pytest.mark.parametrize("vendor", sorted(RUNTIME_PROFILES))
def test_base_url_is_allowed_for_a_runtime_profile_vendor(vendor):
    config = {"model_vendor": vendor, "model_name": "m", "base_url": "http://localhost:8089/v1"}

    result = WorkflowResolutionService(action_configs={"classify_local": config}).resolve_all()

    assert [e for e in result.errors if e.location.config_field == "base_url"] == []
