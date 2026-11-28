"""The knowledge API raises KnowledgeConfigError, a ConfigurationError, for each refusal.

A sandbox run never connects: a database source with no snapshot is refused there, and
its hash is None until a build reads the rows.
"""

from __future__ import annotations

import sqlite3

import pytest
import yaml

from agent_actions.errors import ConfigurationError
from agent_actions.knowledge.api import (
    KnowledgeConfigError,
    ensure_indexes,
    knowledge_hash,
    load_knowledge_config,
    retrieve,
)
from tests.unit.knowledge.conftest import find, make_project


def test_a_bad_section_is_a_knowledge_config_error(tmp_path):
    root = make_project(tmp_path / "p", {}, {"help": {"sources": []}})

    with pytest.raises(KnowledgeConfigError) as caught:
        load_knowledge_config(root)
    assert isinstance(caught.value, ConfigurationError)


def test_a_project_with_no_section_has_no_base(tmp_path):
    (tmp_path / "agent_actions.yml").write_text("project_name: x\n", encoding="utf-8")
    assert load_knowledge_config(tmp_path) == {}


def test_an_unknown_base_is_refused_with_a_suggestion(tmp_path):
    root = make_project(
        tmp_path / "p", {"kb/a.md": "x"}, {"help_center": {"sources": ["kb/*.md"]}}
    )

    with pytest.raises(KnowledgeConfigError, match="Did you mean 'help_center'"):
        ensure_indexes(root, "help_centre", {"keyword"}, sandbox=False)


def test_a_digest_that_was_never_built_is_refused(tmp_path):
    root = make_project(tmp_path / "p", {"kb/a.md": "x"}, {"help": {"sources": ["kb/*.md"]}})

    with pytest.raises(KnowledgeConfigError, match="agac knowledge build help"):
        retrieve(
            root,
            base="help",
            digest="0" * 16,
            methods={"keyword": 1.0},
            query_text="x",
            where={},
            top_k=5,
            candidates=20,
            max_context_tokens=None,
            max_per_origin=None,
        )


def _database_project(tmp_path, connection: dict, create) -> object:
    root = make_project(tmp_path / "p", {}, {})
    create(root)
    config = {
        "project_name": "kb",
        "connections": {"warehouse": connection},
        "knowledge": {
            "kb": {
                "sources": [
                    {
                        "connection": "warehouse",
                        "sql": "SELECT article_id, title, body, product FROM kb",
                        "text": ["body"],
                        "title": "title",
                        "id": "article_id",
                        "metadata": ["product"],
                    }
                ]
            }
        },
    }
    (root / "agent_actions.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return root


ROWS = [("A1", "Refunds", "Money back in 5 days.", "web"), ("A2", "Access", "Reset it.", "app")]


def _sqlite(root):
    with sqlite3.connect(root / "warehouse.db") as conn:
        conn.execute("CREATE TABLE kb (article_id TEXT, title TEXT, body TEXT, product TEXT)")
        conn.executemany("INSERT INTO kb VALUES (?, ?, ?, ?)", ROWS)


def _duckdb(root):
    duckdb = pytest.importorskip("duckdb")
    conn = duckdb.connect(str(root / "warehouse.duckdb"))
    conn.execute("CREATE TABLE kb (article_id TEXT, title TEXT, body TEXT, product TEXT)")
    conn.executemany("INSERT INTO kb VALUES (?, ?, ?, ?)", ROWS)
    conn.close()


@pytest.mark.parametrize(
    ("connection", "create"),
    [
        ({"type": "sqlite", "path": "warehouse.db"}, _sqlite),
        ({"type": "duckdb", "path": "warehouse.duckdb"}, _duckdb),
    ],
    ids=["sqlite", "duckdb"],
)
def test_a_database_source_is_searched_from_its_snapshot(tmp_path, connection, create):
    root = _database_project(tmp_path, connection, create)

    assert knowledge_hash(root, "kb", {"keyword"}, sandbox=True) is None
    with pytest.raises(KnowledgeConfigError, match="does not connect to a database"):
        ensure_indexes(root, "kb", {"keyword"}, sandbox=True)

    digest = ensure_indexes(root, "kb", {"keyword"}, sandbox=False)
    assert knowledge_hash(root, "kb", {"keyword"}, sandbox=True) == digest
    # The snapshot serves a sandbox run, which never connects.
    assert ensure_indexes(root, "kb", {"keyword"}, sandbox=True) == digest

    result = find(root, "kb", {"keyword": 1.0}, "money back", where={"product": "web"})
    assert [(m["id"], m["origin"], m["metadata"]) for m in result["matches"]] == [
        ("A1", "warehouse", {"product": "web"})
    ]
