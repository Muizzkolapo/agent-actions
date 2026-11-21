"""An Ollama batch action's records are sent from this process, `batch_max_workers` at a time.

`record_concurrency` is the online setting and is refused on any batch action. On an Ollama
one the refusal said its records run at the provider and named no setting to use instead.
"""

from __future__ import annotations

import logging

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.llm.batch.infrastructure.batch_client_resolver import BatchClientResolver
from agent_actions.llm.providers.ollama.batch_client import OllamaBatchClient

from .test_record_concurrency_config import _agents, _llm

OLLAMA = ["ollama_local", "ollama_cloud"]


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("KEY", "k")
    monkeypatch.delenv("OLLAMA_BATCH_MAX_WORKERS", raising=False)


@pytest.mark.parametrize("vendor", OLLAMA)
def test_record_concurrency_on_an_ollama_batch_action_names_batch_max_workers(vendor):
    action = _llm(record_concurrency=4, run_mode="batch", model_vendor=vendor)

    with pytest.raises(ConfigValidationError) as refused:
        _agents([action])

    assert (
        "Action 'act' sets record_concurrency, but an Ollama batch action sends its records "
        "from this process, batch_max_workers at a time.\n"
        "Remove record_concurrency from 'act', and set batch_max_workers on it to send "
        "more than one record at a time."
    ) in str(refused.value)


def test_another_vendors_batch_action_is_told_its_records_run_at_the_provider():
    with pytest.raises(ConfigValidationError) as refused:
        _agents([_llm(record_concurrency=4, run_mode="batch")])

    message = str(refused.value)
    assert "a batch action's records run at the provider.\nRemove record_concurrency" in message
    assert "batch_max_workers" not in message


@pytest.mark.parametrize("vendor", OLLAMA)
@pytest.mark.parametrize("where", ["action", "defaults"])
def test_batch_max_workers_reaches_the_ollama_batch_client(vendor, where):
    setting = {"batch_max_workers": 6}
    agents = _agents(
        [_llm(run_mode="batch", model_vendor=vendor, **(setting if where == "action" else {}))],
        defaults=setting if where == "defaults" else None,
    )

    client = BatchClientResolver().get_for_config(agents["act"])

    assert isinstance(client, OllamaBatchClient)
    assert client._get_max_workers() == 6


@pytest.mark.parametrize("vendor", OLLAMA)
def test_an_inherited_record_concurrency_does_not_set_the_batch_workers(vendor):
    agents = _agents(
        [_llm(run_mode="batch", model_vendor=vendor)], defaults={"record_concurrency": 8}
    )

    assert BatchClientResolver().get_for_config(agents["act"])._get_max_workers() == 1


@pytest.mark.parametrize(
    ("value", "said"),
    [("0", "OLLAMA_BATCH_MAX_WORKERS=0 invalid"), ("99", "OLLAMA_BATCH_MAX_WORKERS=99 exceeds")],
)
def test_a_bad_environment_value_is_named_as_the_environment_variable(
    monkeypatch, caplog, value, said
):
    monkeypatch.setenv("OLLAMA_BATCH_MAX_WORKERS", value)
    client = OllamaBatchClient(base_url="http://localhost:11434")

    with caplog.at_level(logging.WARNING):
        client._get_max_workers()

    assert said in caplog.text
    assert "batch_max_workers=" not in caplog.text
