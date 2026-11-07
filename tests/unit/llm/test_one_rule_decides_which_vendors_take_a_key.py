"""`vendor_needs_api_key` is the one rule expansion and preflight read.

Every built-in vendor has a row in `VENDOR_CONFIGS`; a vendor with no row would read as
"unknown" and be asked for a key. A runtime profile and a declared endpoint answer from
their own declarations, and an alias answers as the vendor it names. Expansion and preflight
agree with it for a vendor added later, not only for today's.
"""

from __future__ import annotations

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.llm.config import endpoints
from agent_actions.llm.config.runtime_profiles import RUNTIME_PROFILES, RuntimeProfile
from agent_actions.llm.config.vendor import (
    VENDOR_CONFIGS,
    VendorType,
    api_key_env_var,
    vendor_needs_api_key,
)
from agent_actions.output.response.expander_validation import validate_required_fields
from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService


def test_every_built_in_vendor_has_a_row():
    assert set(VENDOR_CONFIGS) == {v.value for v in VendorType}


@pytest.mark.parametrize(
    ("vendor", "needs", "variable"),
    [
        ("openai", True, "OPENAI_API_KEY"),
        ("anthropic", True, "ANTHROPIC_API_KEY"),
        ("gemini", True, "GEMINI_API_KEY"),
        ("google", True, "GEMINI_API_KEY"),
        ("groq", True, "GROQ_API_KEY"),
        ("cohere", True, "COHERE_API_KEY"),
        ("ollama_cloud", True, "OLLAMA_API_KEY"),
        ("ollama_local", False, None),
        ("agac-provider", False, None),
        ("tool", False, None),
        ("hitl", False, None),
        ("llamafile", False, None),
        ("OpenAI", True, "OPENAI_API_KEY"),
    ],
)
def test_each_vendor_answers_from_its_own_declaration(vendor, needs, variable):
    assert (vendor_needs_api_key(vendor), api_key_env_var(vendor)) == (needs, variable)


def test_an_unknown_vendor_is_assumed_to_need_a_key():
    assert vendor_needs_api_key("totally_unknown_vendor") is True
    assert api_key_env_var("totally_unknown_vendor") is None


def test_a_declared_endpoint_needs_no_key(monkeypatch):
    monkeypatch.setattr(
        endpoints, "project_endpoint", lambda name: object() if name == "lab" else None
    )

    assert vendor_needs_api_key("lab") is False
    assert vendor_needs_api_key("openai") is True


def _profile(api_key_required: bool) -> RuntimeProfile:
    return RuntimeProfile(
        wire="openai_chat",
        default_base_url="http://localhost:9/v1",
        api_key_required=api_key_required,
        supports_batch=False,
        supports_tools=False,
        enforces_json_schema=True,
        enforces_json_object=False,
        verified_with="test",
    )


def _expansion_refuses(vendor: str) -> bool:
    try:
        validate_required_fields({"model_vendor": vendor, "model_name": "m"}, "a")
    except ConfigValidationError:
        return True
    return False


def _preflight_refuses(monkeypatch, vendor: str) -> bool:
    """Whether preflight reports an unset key for an action naming an unset variable."""
    monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)
    monkeypatch.delenv("UNSET_KEY_FOR_PARITY", raising=False)
    config = {"model_vendor": vendor, "api_key": "UNSET_KEY_FOR_PARITY"}
    return bool(WorkflowResolutionService(action_configs={"a": config})._check_api_keys()[0])


@pytest.mark.parametrize(("name", "required"), [("lab-keyless", False), ("lab-keyed", True)])
def test_a_new_runtime_profile_is_held_to_its_own_declaration(monkeypatch, name, required):
    monkeypatch.setitem(RUNTIME_PROFILES, name, _profile(required))

    assert vendor_needs_api_key(name) is required
    assert _expansion_refuses(name) is required
    assert _preflight_refuses(monkeypatch, name) is required


@pytest.mark.parametrize(("vendor", "required"), [("agac-provider", False), ("openai", True)])
def test_preflight_checks_a_named_key_only_where_the_vendor_sends_one(
    monkeypatch, vendor, required
):
    assert _preflight_refuses(monkeypatch, vendor) is required
