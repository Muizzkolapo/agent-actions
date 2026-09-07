"""`agac batch` picks the action to address, or says why it cannot."""

from __future__ import annotations

import json

import click
import pytest

from agent_actions.llm.batch.batch_cli import _resolve_action
from agent_actions.llm.batch.core.batch_constants import RetiredRecoveryState
from agent_actions.llm.batch.core.batch_models import BatchJobEntry
from agent_actions.llm.batch.infrastructure.registry import BatchRegistryManager

WORKFLOW = "pipeline"
PREFIX = BatchRegistryManager.METADATA_KEY_PREFIX


class _Backend:
    def __init__(self, registries: dict[str, dict]) -> None:
        self.store = {f"{PREFIX}{action}": json.dumps(jobs) for action, jobs in registries.items()}

    def load_metadata(self, key: str) -> str | None:
        return self.store.get(key)

    def save_metadata(self, key: str, value: str) -> None:
        self.store[key] = value

    def list_metadata_prefix(self, prefix: str) -> list[str]:
        return [k for k in self.store if k.startswith(prefix)]


def _job(batch_id: str, file_name: str = "pages.json") -> dict:
    return BatchJobEntry(
        batch_id=batch_id,
        status="completed",
        timestamp="2026-09-01T09:00:00Z",
        provider="openai",
        file_name=file_name,
    ).to_dict()


def _registry(*batch_ids: str) -> dict:
    return {f"pages_{i}.json": _job(bid) for i, bid in enumerate(batch_ids)}


def test_an_explicit_action_is_used_verbatim():
    """Not registry-checked: a batch can be live at the provider after --fresh."""
    backend = _Backend({})
    assert _resolve_action(backend, WORKFLOW, "extract") == "extract"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_action_is_rejected(blank):
    with pytest.raises(click.UsageError, match="must not be empty"):
        _resolve_action(_Backend({}), WORKFLOW, blank)


def test_no_registered_action_names_the_workflow_and_the_way_out():
    with pytest.raises(click.UsageError) as exc:
        _resolve_action(_Backend({}), WORKFLOW, None)
    assert WORKFLOW in str(exc.value)
    assert "--action" in str(exc.value)


def test_a_single_registered_action_is_auto_selected():
    backend = _Backend({"extract": _registry("b-1")})
    assert _resolve_action(backend, WORKFLOW, None) == "extract"


def test_several_actions_with_no_batch_id_lists_the_candidates():
    backend = _Backend({"extract": _registry("b-1"), "score": _registry("b-2")})
    with pytest.raises(click.UsageError) as exc:
        _resolve_action(backend, WORKFLOW, None)
    message = str(exc.value)
    assert "extract" in message and "score" in message


def test_a_batch_id_owned_by_one_action_selects_it():
    backend = _Backend({"extract": _registry("b-1"), "score": _registry("b-2")})
    assert _resolve_action(backend, WORKFLOW, None, batch_id="b-2") == "score"


def test_a_batch_id_owned_by_several_actions_lists_only_the_owners():
    backend = _Backend(
        {"extract": _registry("shared"), "score": _registry("shared"), "other": _registry("b-9")}
    )
    with pytest.raises(click.UsageError) as exc:
        _resolve_action(backend, WORKFLOW, None, batch_id="shared")
    message = str(exc.value)
    assert "extract" in message and "score" in message
    assert "other" not in message, f"a non-owner must not be offered as a candidate: {message}"


def test_an_unowned_batch_id_falls_through_to_auto_select():
    """The service layer, not this resolver, reports 'batch not found'."""
    backend = _Backend({"extract": _registry("b-1")})
    assert _resolve_action(backend, WORKFLOW, None, batch_id="never-registered") == "extract"


def test_one_actions_unreadable_registry_names_that_action():
    """The sweep reads every action, so a refusal has to say which one is stuck."""
    legacy = {
        "pages_reprompt_1.json": {
            "batch_id": "b-legacy",
            "status": "completed",
            "timestamp": "2026-09-01T09:00:00Z",
            "provider": "openai",
            "recovery_type": "reprompt",
        }
    }
    backend = _Backend({"extract": _registry("b-1"), "score": legacy})
    with pytest.raises(RetiredRecoveryState) as exc:
        _resolve_action(backend, WORKFLOW, None, batch_id="b-1")
    assert "score" in str(exc.value)
