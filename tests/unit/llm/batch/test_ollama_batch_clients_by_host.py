"""Two batch actions that send to different hosts never share a client."""

from unittest.mock import patch

import pytest

from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver

_SDK = "agent_actions.llm.providers.ollama.batch_client.Client"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OLLAMA_TEST_KEY", "k")
    monkeypatch.delenv("OLLAMA_BATCH_MAX_WORKERS", raising=False)


def _agent(vendor: str, base_url: str) -> dict:
    config = {"model_vendor": vendor, "model_name": "llama3", "base_url": base_url}
    if vendor == "ollama_cloud":
        config["api_key"] = "OLLAMA_TEST_KEY"
    return config


@pytest.mark.parametrize("vendor", ["ollama_local", "ollama_cloud"])
def test_two_actions_with_different_hosts_get_two_clients(vendor):
    resolver = BatchClientResolver()
    with patch(_SDK) as sdk:
        resolver.get_for_config(_agent(vendor, "http://box-a:11434"))
        resolver.get_for_config(_agent(vendor, "http://box-b:11434"))
        resolver.get_for_config(_agent(vendor, "http://box-a:11434"))

    assert [call.kwargs["host"] for call in sdk.call_args_list] == [
        "http://box-a:11434",
        "http://box-b:11434",
    ]
