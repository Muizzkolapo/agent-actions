"""The retrieve step reads its query and filters from the record and searches the run's index."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.llm.providers.tools import builtin
from agent_actions.llm.providers.tools.builtin import (
    knowledge_hash,
    knowledge_run,
    resolve_knowledge,
    run_builtin,
)
from tests.helpers.knowledge import FakeBase, install_fake_knowledge

ROOT = Path("/project")


@pytest.fixture
def knowledge(monkeypatch):
    return install_fake_knowledge(monkeypatch, FakeBase("help_center"))


def _spec(**over):
    return {
        "tool": "retrieve",
        "base": "help_center",
        "methods": {"keyword": 1.0},
        "query": ["source.subject", "classify.keywords"],
        "where": {"product": "classify.product", "lang": {"value": "en"}},
        "top_k": 3,
        "candidates": 20,
        "max_context_tokens": None,
        "max_per_origin": 2,
        "entry": "help",
        "action": "write_reply",
        **over,
    }


def _config(spec):
    return {"name": f"{spec['action']}__{spec['entry']}", "kind": "tool", "_builtin": spec}


def _record(**classify):
    return {
        "source": {"subject": "Refund"},
        "classify": {"keywords": ["double", "charge"], "product": "billing", **classify},
    }


def _search(knowledge, spec, record):
    with knowledge_run(ROOT, sandbox=False):
        resolve_knowledge({"s": _config(spec)}, ROOT, sandbox=False)
        result = run_builtin(spec, record)
    assert result == knowledge.result
    return knowledge.searched[-1]


def test_the_query_joins_each_reference_and_flattens_a_list_of_strings(knowledge):
    call = _search(knowledge, _spec(), _record())

    assert call["query_text"] == "Refund double charge"
    assert call["where"] == {"product": "billing", "lang": "en"}
    assert call["digest"] == knowledge.digest
    assert call["methods"] == {"keyword": 1.0}
    assert (call["top_k"], call["candidates"], call["max_per_origin"]) == (3, 20, 2)
    assert call["label"] == "write_reply: retrieve 'help' (write_reply__help)"


def test_a_null_adds_nothing_and_a_number_is_written_as_text(knowledge):
    call = _search(knowledge, _spec(), _record(keywords=[None, 42, ["nested"]]))

    assert call["query_text"] == "Refund 42 nested"


def test_a_null_where_value_stays_null(knowledge):
    call = _search(knowledge, _spec(), _record(product=None))

    assert call["where"]["product"] is None


def test_a_field_the_record_lacks_fails_the_record_as_for_a_router(knowledge):
    record = {"source": {"subject": "Refund"}, "classify": {"product": "billing"}}

    with knowledge_run(ROOT, sandbox=False):
        resolve_knowledge({"s": _config(_spec())}, ROOT, sandbox=False)
        with pytest.raises(KeyError, match="the record holds no 'classify.keywords'"):
            run_builtin(_spec(), record)


def test_an_object_in_the_query_is_refused(knowledge):
    with knowledge_run(ROOT, sandbox=False):
        resolve_knowledge({"s": _config(_spec())}, ROOT, sandbox=False)
        with pytest.raises(TypeError, match="holds an object"):
            run_builtin(_spec(), _record(keywords={"a": 1}))


def test_a_search_outside_a_run_names_the_step_and_the_base(knowledge):
    with pytest.raises(ConfigurationError, match="write_reply: retrieve 'help'.*help_center"):
        run_builtin(_spec(), _record())


class TestTheRunResolvesEachIndexOnce:
    def test_ensure_indexes_runs_once_per_base_and_index_kinds_over_every_pass(self, knowledge):
        configs = {
            "a": _config(_spec()),
            "b": _config(_spec(entry="other", action="other")),
            "c": _config(_spec(entry="fuzzy", methods={"keyword": 0.5, "fuzzy": 0.5})),
        }
        with knowledge_run(ROOT, sandbox=True):
            resolve_knowledge(configs, ROOT, sandbox=True)
            resolve_knowledge(configs, ROOT, sandbox=True)

        assert knowledge.ensured == [
            (ROOT, "help_center", {"fuzzy", "keyword"}, True),
            (ROOT, "help_center", {"keyword"}, True),
        ]

    def test_a_new_run_resolves_again(self, knowledge):
        for _ in range(2):
            with knowledge_run(ROOT, sandbox=False):
                resolve_knowledge({"a": _config(_spec())}, ROOT, sandbox=False)

        assert len(knowledge.ensured) == 2

    def test_a_workflow_with_no_retrieve_step_never_imports_the_api(self, monkeypatch):
        monkeypatch.setattr(builtin, "knowledge_api", lambda: pytest.fail("imported"))

        resolve_knowledge({"a": {"name": "a", "kind": "tool"}}, ROOT, sandbox=False)


class TestTheKnowledgeHash:
    def test_it_is_none_outside_a_run(self, knowledge):
        assert knowledge_hash(_spec()) is None
        assert knowledge.hashed == []

    def test_a_run_hashes_the_kinds_the_methods_read_once(self, knowledge):
        with knowledge_run(ROOT, sandbox=False):
            assert knowledge_hash(_spec()) == knowledge.hash
            assert knowledge_hash(_spec(entry="again")) == knowledge.hash

        assert knowledge.hashed == [(ROOT, "help_center", {"keyword"}, False)]
