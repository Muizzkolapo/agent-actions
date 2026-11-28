"""A retrieve step of an action corpus searches the index its run built, never its own record."""

from __future__ import annotations

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.knowledge.api import index_action_corpus
from agent_actions.llm.providers.tools.builtin import (
    knowledge_run,
    register_corpus,
    resolve_knowledge,
    run_builtin,
)
from agent_actions.workflow.executor import _compute_knowledge_hash

SPEC = {
    "tool": "retrieve",
    "corpus": {"action": "summarize", "text": ["summary"], "title": None, "id": "ticket_id"},
    "methods": {"keyword": 1.0},
    "query": ["summarize.summary"],
    "where": {},
    "top_k": 2,
    "candidates": 20,
    "max_context_tokens": None,
    "max_per_origin": None,
    "entry": "similar",
    "action": "link",
}
SUMMARIES = {"T-1": "charged twice", "T-2": "charged twice again", "T-3": "charged once"}


def _rows():
    return [
        {
            "source_guid": f"g-{ticket}",
            "_state": "processed",
            "content": {"summarize": {"ticket_id": ticket, "summary": summary}},
        }
        for ticket, summary in SUMMARIES.items()
    ]


def _record(ticket):
    return {"summarize": {"ticket_id": ticket, "summary": SUMMARIES[ticket]}}


def test_the_step_searches_the_registered_index_and_never_returns_its_own_record(tmp_path):
    with knowledge_run(tmp_path, sandbox=False):
        index = index_action_corpus(tmp_path, SPEC["corpus"], ["keyword"], _rows(), label="x")
        register_corpus("link__similar", index)

        result = run_builtin(SPEC, _record("T-1"), "g-T-1")

    assert [m["id"] for m in result["matches"]] == ["T-2", "T-3"]
    assert result["index"] == index.digest


def test_a_step_whose_run_built_no_index_is_refused_naming_the_action(tmp_path):
    with knowledge_run(tmp_path, sandbox=False), pytest.raises(ConfigurationError) as caught:
        run_builtin(SPEC, _record("T-1"), "g-T-1")

    assert "searches the records of action 'summarize'" in str(caught.value)
    assert "link: retrieve 'similar' (link__similar)" in str(caught.value)


def test_a_run_resolves_no_knowledge_base_and_stamps_no_hash_for_an_action_corpus(tmp_path):
    config = {"name": "link__similar", "kind": "tool", "_builtin": SPEC}

    with knowledge_run(tmp_path, sandbox=False) as run:
        resolve_knowledge({"link__similar": config}, tmp_path, sandbox=False)

        assert run.digests == {}
        assert _compute_knowledge_hash(config) == ""  # type: ignore[arg-type]
