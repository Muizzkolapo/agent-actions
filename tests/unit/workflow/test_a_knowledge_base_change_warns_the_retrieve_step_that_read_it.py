"""A retrieve step stamps the knowledge base it read; a change warns; --rerun reopens it."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_actions.llm.providers.tools.builtin import knowledge_run
from agent_actions.storage.backends.sqlite_backend import SQLiteBackend
from agent_actions.workflow.executor import (
    KNOWLEDGE_EDIT,
    ActionExecutor,
    ExecutorDependencies,
    _compute_action_config_hash,
    _edits_since,
    config_in_force,
)
from agent_actions.workflow.managers.state import ActionStateManager, ActionStatus
from tests.helpers.knowledge import FakeBase, install_fake_knowledge

ROOT = Path("/project")
SPEC = {
    "tool": "retrieve",
    "base": "help_center",
    "methods": {"keyword": 1.0},
    "query": ["source.text"],
    "where": {},
    "top_k": 5,
    "candidates": 20,
    "max_context_tokens": None,
    "max_per_origin": None,
    "entry": "help",
    "action": "write_reply",
}
CONFIGS = {
    "write_reply__help": {"kind": "tool", "impl": "agac.retrieve", "_builtin": SPEC},
    "write_reply": {"prompt": "X", "model": "m", "dependencies": ["write_reply__help"]},
}


@pytest.fixture
def knowledge(monkeypatch):
    return install_fake_knowledge(monkeypatch, FakeBase("help_center"))


def _executor(tmp_path, knowledge):
    backend = SQLiteBackend(str(tmp_path / "store.db"), workflow_name="w")
    backend.initialize()
    state = ActionStateManager(tmp_path / "status.json", list(CONFIGS))
    with knowledge_run(ROOT, sandbox=False):
        for name, config in CONFIGS.items():
            state.update_status(name, ActionStatus.COMPLETED, **config_in_force(config))
    runner = MagicMock()
    runner.retried_records = frozenset()
    runner.storage_backend = backend
    runner.action_configs = CONFIGS
    executor = ActionExecutor(
        ExecutorDependencies(
            action_runner=runner,
            state_manager=state,
            skip_evaluator=MagicMock(),
            batch_manager=MagicMock(),
            output_manager=MagicMock(),
        )
    )
    return executor, state


def test_a_changed_knowledge_base_is_an_edit_of_the_step_in_a_run(tmp_path, knowledge):
    _, state = _executor(tmp_path, knowledge)
    knowledge.hash = "digest-2"

    with knowledge_run(ROOT, sandbox=False):
        edits = _edits_since(
            state.get_status_details("write_reply__help"), CONFIGS["write_reply__help"]
        )

    assert edits == [KNOWLEDGE_EDIT]


def test_a_read_only_load_does_not_compare_the_knowledge_base(tmp_path, knowledge):
    _, state = _executor(tmp_path, knowledge)
    knowledge.hash = "digest-2"
    hashed = len(knowledge.hashed)

    edits = _edits_since(
        state.get_status_details("write_reply__help"), CONFIGS["write_reply__help"]
    )

    assert edits == []
    assert len(knowledge.hashed) == hashed


def test_a_stamp_from_before_knowledge_bases_is_no_edit_of_another_action():
    stamp = config_in_force(CONFIGS["write_reply"])
    stamp.pop("knowledge_hash")

    assert _edits_since(stamp, CONFIGS["write_reply"]) == []


def test_the_change_warns_naming_the_step_the_base_and_the_rerun(tmp_path, knowledge, caplog):
    executor, _ = _executor(tmp_path, knowledge)
    knowledge.hash = "digest-2"

    with knowledge_run(ROOT, sandbox=False), caplog.at_level(logging.WARNING):
        status = executor._maybe_invalidate_completed_status(
            "write_reply__help", CONFIGS["write_reply__help"], ActionStatus.COMPLETED
        )

    assert status == ActionStatus.COMPLETED
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [
        "write_reply: retrieve 'help' (write_reply__help): knowledge base 'help_center' "
        "changed since it answered; run again with --rerun write_reply__help"
    ]


def test_method_where_and_limits_are_in_the_steps_config_hash():
    base = _compute_action_config_hash(CONFIGS["write_reply__help"])
    for change in (
        {"methods": {"fuzzy": 1.0}},
        {"where": {"product": {"value": "billing"}}},
        {"top_k": 3},
        {"max_per_origin": 1},
    ):
        edited = {**CONFIGS["write_reply__help"], "_builtin": {**SPEC, **change}}
        assert _compute_action_config_hash(edited) != base


def test_rerun_of_an_action_reopens_its_retrieve_steps(tmp_path, knowledge):
    executor, state = _executor(tmp_path, knowledge)

    reopened = executor.rerun(["write_reply"])

    assert "write_reply__help" in reopened
    assert state.get_status("write_reply__help") == ActionStatus.PENDING
    assert state.get_status("write_reply") == ActionStatus.PENDING
