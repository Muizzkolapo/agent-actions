import pytest
from pydantic import SecretStr

from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)
    monkeypatch.delenv("MY_KEY", raising=False)


def _check(api_key):
    svc = WorkflowResolutionService(
        action_configs={"summarize": {"model_vendor": "openai", "api_key": api_key}}
    )
    return svc._check_api_keys()


@pytest.mark.parametrize("api_key", [SecretStr("MY_KEY"), "MY_KEY", "${MY_KEY}"])
def test_the_probe_key_is_the_value_of_the_named_env_var(monkeypatch, api_key):
    monkeypatch.setenv("MY_KEY", "abc")

    errors, _warnings, targets = _check(api_key)

    assert errors == []
    assert [t.api_key for t in targets] == ["abc"]


@pytest.mark.parametrize("api_key", [SecretStr("MY_KEY"), "MY_KEY", "${MY_KEY}"])
def test_an_unset_named_env_var_is_a_presence_error(api_key):
    errors, _warnings, targets = _check(api_key)

    assert targets == []
    assert [e.location.raw_reference for e in errors] == ["MY_KEY"]
