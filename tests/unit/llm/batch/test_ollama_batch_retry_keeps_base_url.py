"""A retry or repair round sends to the host and worker count the first submission used."""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver

_SDK = "agent_actions.llm.providers.ollama.batch_client.Client"
_ACTION_HOST = "http://gpu-box:11434"
_ENV_HOST = "http://env-host:11434"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OLLAMA_TEST_KEY", "k")
    monkeypatch.setenv("OLLAMA_HOST", _ENV_HOST)
    monkeypatch.setenv("OLLAMA_CLOUD_HOST", _ENV_HOST)
    monkeypatch.delenv("OLLAMA_BATCH_MAX_WORKERS", raising=False)


def _agent(vendor: str, **extra) -> dict:
    config = {"model_vendor": vendor, "model_name": "llama3", **extra}
    if vendor == "ollama_cloud":
        config["api_key"] = "OLLAMA_TEST_KEY"
    return config


def _registry(vendor: str) -> MagicMock:
    registry = MagicMock()
    registry.get_batch_job_by_id.return_value = MagicMock(provider=vendor)
    return registry


@pytest.mark.parametrize("vendor", ["ollama_local", "ollama_cloud"])
def test_a_round_in_a_later_run_keeps_the_action_base_url_and_workers(vendor):
    config = _agent(vendor, base_url=_ACTION_HOST, batch_max_workers=6)
    with patch(_SDK) as sdk:
        first = BatchClientResolver().get_for_config(config)
        later = BatchClientResolver().get_for_batch_id("b1", _registry(vendor), agent_config=config)

    assert [call.kwargs["host"] for call in sdk.call_args_list] == [_ACTION_HOST, _ACTION_HOST]
    assert (first._get_max_workers(), later._get_max_workers()) == (6, 6)


@pytest.mark.parametrize("vendor", ["ollama_local", "ollama_cloud"])
def test_a_round_for_an_action_without_base_url_uses_the_environment_host(vendor):
    with patch(_SDK) as sdk:
        client = BatchClientResolver().get_for_batch_id(
            "b1", _registry(vendor), agent_config=_agent(vendor)
        )

    assert sdk.call_args.kwargs["host"] == _ENV_HOST
    assert client._get_max_workers() == 1


@pytest.mark.parametrize("vendor", ["ollama_local", "ollama_cloud"])
def test_two_actions_with_different_worker_counts_get_two_clients(vendor):
    resolver = BatchClientResolver()
    with patch(_SDK):
        two = resolver.get_for_config(_agent(vendor, base_url=_ACTION_HOST, batch_max_workers=2))
        eight = resolver.get_for_config(_agent(vendor, base_url=_ACTION_HOST, batch_max_workers=8))

    assert (two._get_max_workers(), eight._get_max_workers()) == (2, 8)


@pytest.mark.parametrize("vendor", ["ollama_local", "ollama_cloud"])
def test_a_round_does_not_reuse_a_cached_client_for_another_worker_count(vendor):
    resolver = BatchClientResolver()
    with patch(_SDK):
        resolver.get_for_config(_agent(vendor, base_url=_ACTION_HOST, batch_max_workers=2))
        later = resolver.get_for_batch_id(
            "b1",
            _registry(vendor),
            agent_config=_agent(vendor, base_url=_ACTION_HOST, batch_max_workers=8),
        )

    assert later._get_max_workers() == 8


@pytest.mark.parametrize("vendor", ["ollama_local", "ollama_cloud"])
def test_a_round_reuses_the_cached_client_for_the_same_action_config(vendor):
    resolver = BatchClientResolver()
    config = _agent(vendor, base_url=_ACTION_HOST, batch_max_workers=6)
    with patch(_SDK) as sdk:
        resolver.get_for_config(config)
        later = resolver.get_for_batch_id("b1", _registry(vendor), agent_config=config)

    assert [call.kwargs["host"] for call in sdk.call_args_list] == [_ACTION_HOST]
    assert later._get_max_workers() == 6
