"""The in-process ollama batch waits an action's `request_timeout`, or 600 seconds unset.

Retry and repair rounds take their client by batch id, so that path is held to it too.
"""

from unittest.mock import MagicMock, patch

import pytest

from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver

_SDK = "agent_actions.llm.providers.ollama.batch_client.Client"


def _agent(vendor: str, **extra) -> dict:
    config = {"model_vendor": vendor, "model_name": "llama3", **extra}
    if vendor == "ollama_cloud":
        config["api_key"] = "OLLAMA_TEST_KEY"
    return config


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("OLLAMA_TEST_KEY", "k")


@pytest.mark.parametrize("vendor", ["ollama_local", "ollama_cloud"])
@pytest.mark.parametrize(
    ("extra", "expected"),
    [({"request_timeout": 1800}, 1800), ({}, 600.0), ({"request_timeout": None}, 600.0)],
    ids=["set", "unset", "null"],
)
def test_the_batch_client_waits_the_action_request_timeout(vendor, extra, expected):
    with patch(_SDK) as sdk:
        BatchClientResolver().get_for_config(_agent(vendor, **extra))

    assert sdk.call_args.kwargs["timeout"] == expected


@pytest.mark.parametrize("vendor", ["ollama_local", "ollama_cloud"])
def test_two_actions_with_different_timeouts_get_two_clients(vendor):
    resolver = BatchClientResolver()
    with patch(_SDK) as sdk:
        resolver.get_for_config(_agent(vendor, request_timeout=1800))
        resolver.get_for_config(_agent(vendor, request_timeout=30))
        resolver.get_for_config(_agent(vendor, request_timeout=1800))

    assert [call.kwargs["timeout"] for call in sdk.call_args_list] == [1800, 30]


def _registry(vendor: str) -> MagicMock:
    registry = MagicMock()
    registry.get_batch_job_by_id.return_value = MagicMock(provider=vendor)
    return registry


@pytest.mark.parametrize("vendor", ["ollama_local", "ollama_cloud"])
@pytest.mark.parametrize(
    ("extra", "expected"),
    [({"request_timeout": 1800}, 1800), ({}, 600.0)],
    ids=["set", "unset"],
)
def test_a_client_found_by_batch_id_waits_the_action_request_timeout(vendor, extra, expected):
    with patch(_SDK) as sdk:
        BatchClientResolver().get_for_batch_id(
            "b1", _registry(vendor), agent_config=_agent(vendor, **extra)
        )

    assert sdk.call_args.kwargs["timeout"] == expected


@pytest.mark.parametrize("vendor", ["ollama_local", "ollama_cloud"])
def test_a_cached_client_for_another_timeout_is_not_reused_by_batch_id(vendor):
    resolver = BatchClientResolver()
    with patch(_SDK) as sdk:
        resolver.get_for_config(_agent(vendor))
        resolver.get_for_batch_id(
            "b1", _registry(vendor), agent_config=_agent(vendor, request_timeout=30)
        )

    assert [call.kwargs["timeout"] for call in sdk.call_args_list] == [600.0, 30]


@pytest.mark.parametrize("vendor", ["ollama_local", "ollama_cloud"])
def test_the_cached_client_for_the_same_timeout_is_reused_by_batch_id(vendor):
    resolver = BatchClientResolver()
    with patch(_SDK) as sdk:
        resolver.get_for_config(_agent(vendor, request_timeout=30))
        resolver.get_for_batch_id(
            "b1", _registry(vendor), agent_config=_agent(vendor, request_timeout=30)
        )

    assert [call.kwargs["timeout"] for call in sdk.call_args_list] == [30]
