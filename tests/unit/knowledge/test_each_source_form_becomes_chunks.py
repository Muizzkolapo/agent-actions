"""Each source form becomes chunks: a text file is split, a record is one chunk.

A file glob that matches nothing, a path outside the project, a file too large, a record
with no text and an id that names two records are refused by name.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
import yaml

from agent_actions.errors import ConfigurationError
from agent_actions.knowledge.chunks import chunk, scan
from agent_actions.knowledge.config import load_knowledge
from tests.unit.knowledge.conftest import make_project


def _chunks(root, name="kb"):
    return chunk(scan(root, name, load_knowledge(root)[name]))


def test_markdown_is_split_by_headings_with_ids_by_file_and_ordinal(tmp_path):
    root = make_project(
        tmp_path / "p",
        {"kb/a.md": "# A\n\none\n\n## B\n\ntwo\n"},
        {"kb": {"sources": ["kb/*.md"]}},
    )
    chunks = _chunks(root)

    assert [(c.id, c.title, c.text) for c in chunks] == [
        ("kb/a.md#1", "A", "A\none"),
        ("kb/a.md#2", "A > B", "A > B\ntwo"),
    ]
    assert chunks[0].origin == "kb/a.md"


def test_html_headings_become_heading_paths(tmp_path):
    root = make_project(
        tmp_path / "p",
        {"kb/a.html": "<h1>Refunds</h1><p>Money back in 5 days.</p><script>x()</script>"},
        {"kb": {"sources": ["kb/*.html"]}},
    )
    (only,) = _chunks(root)

    assert only.title == "Refunds"
    assert only.body == "Money back in 5 days."


def test_a_docx_file_is_read(tmp_path):
    docx = pytest.importorskip("docx")
    root = make_project(tmp_path / "p", {}, {"kb": {"sources": ["kb/*.docx"]}})
    (root / "kb").mkdir()
    document = docx.Document()
    document.add_heading("Access", level=1)
    document.add_paragraph("Reset your password from the sign-in page.")
    document.save(root / "kb" / "a.docx")

    (only,) = _chunks(root)

    assert only.title == "Access"
    assert "Reset your password" in only.text


def test_records_of_json_jsonl_and_csv_are_one_chunk_each(tmp_path):
    root = make_project(
        tmp_path / "p",
        {
            "seed/faq.jsonl": '{"n": "1", "q": "How?", "a": "So.", "tag": "x"}\n',
            "seed/faq.csv": "n,q,a,tag\n2,Why?,Because.,y\n",
            "seed/plain.json": json.dumps([{"name": "Ann", "role": "admin"}]),
        },
        {
            "kb": {
                "sources": [
                    {
                        "path": "seed/faq.jsonl",
                        "text": ["q", "a"],
                        "title": "q",
                        "id": "n",
                        "metadata": ["tag"],
                    },
                    {"path": "seed/faq.csv", "text": ["q", "a"], "id": "n", "metadata": ["tag"]},
                    "seed/plain.json",
                ]
            }
        },
    )
    chunks = _chunks(root)

    assert [(c.id, c.title, c.text, c.metadata) for c in chunks] == [
        ("1", "How?", "How?\nSo.", {"tag": "x"}),
        ("2", "", "Why?\nBecause.", {"tag": "y"}),
        ("seed/plain.json#1", "", "name: Ann\nrole: admin", {}),
    ]


def test_a_file_two_globs_match_is_read_once(tmp_path):
    root = make_project(
        tmp_path / "p",
        {"kb/a.md": "# A\n\nText.", "kb/b.md": "# B\n\nMore."},
        {"kb": {"sources": ["kb/*.md", "kb/a.md"]}},
    )

    assert [c.id for c in _chunks(root)] == ["kb/a.md#1", "kb/b.md#1"]


def test_a_file_two_sources_read_differently_is_refused_naming_both(tmp_path):
    root = make_project(
        tmp_path / "p",
        {"seed/faq.json": json.dumps([{"n": "1", "q": "How?"}])},
        {"kb": {"sources": ["seed/*.json", {"path": "seed/faq.json", "text": "q", "id": "n"}]}},
    )

    with pytest.raises(ConfigurationError) as caught:
        _chunks(root)

    assert "seed/faq.json is matched by source 1 and source 2" in str(caught.value)


def test_a_csv_row_with_more_values_than_columns_adds_no_unnamed_line(tmp_path):
    root = make_project(
        tmp_path / "p",
        {"seed/r.csv": "name,role\nAnn,admin,extra\n"},
        {"kb": {"sources": ["seed/r.csv"]}},
    )

    assert [c.text for c in _chunks(root)] == ["name: Ann\nrole: admin"]


def test_a_jsonl_record_is_one_line_whatever_line_separators_its_strings_hold(tmp_path):
    line = json.dumps({"n": "1", "q": "How now\x85then?"}, ensure_ascii=False)
    root = make_project(
        tmp_path / "p",
        {"seed/faq.jsonl": line + "\n\n"},
        {"kb": {"sources": [{"path": "seed/faq.jsonl", "text": "q", "id": "n"}]}},
    )

    assert [c.text for c in _chunks(root)] == ["How now\x85then?"]


@pytest.mark.parametrize(
    ("files", "source", "message"),
    [
        ({}, "kb/*.md", "matches no file"),
        ({}, "../outside/*.md", "must be a path inside the project"),
        (
            {"seed/r.json": '[{"n": "1", "q": ""}]'},
            {"path": "seed/r.json", "text": "q", "id": "n"},
            "has no text in q",
        ),
        (
            {"seed/r.json": '[{"n": "1", "q": "a"}, {"n": "1", "q": "b"}]'},
            {"path": "seed/r.json", "text": "q", "id": "n"},
            "id '1' names a record",
        ),
        (
            {"seed/r.json": '[{"q": "a"}]'},
            {"path": "seed/r.json", "text": "q", "id": "n"},
            "no value in its id field 'n'",
        ),
        ({"seed/r.json": "[1, 2]"}, {"path": "seed/r.json", "text": "q"}, "is not an object"),
        (
            {"seed/r.json": "{not json"},
            {"path": "seed/r.json", "text": "q"},
            "cannot read seed/r.json",
        ),
    ],
)
def test_a_bad_source_is_refused_by_name(tmp_path, files, source, message):
    root = make_project(tmp_path / "p", files, {"kb": {"sources": [source]}})

    with pytest.raises(ConfigurationError) as caught:
        _chunks(root)

    assert "knowledge base 'kb'" in str(caught.value)
    assert message in str(caught.value)


def test_a_file_over_the_size_limit_is_refused(tmp_path, monkeypatch):
    from agent_actions.knowledge import chunks as chunks_module

    monkeypatch.setattr(chunks_module, "MAX_FILE_BYTES", 10)
    root = make_project(tmp_path / "p", {"kb/a.md": "x" * 11}, {"kb": {"sources": ["kb/*.md"]}})

    with pytest.raises(ConfigurationError, match="a source file may hold at most"):
        _chunks(root)
    (root / "kb" / "a.md").write_text("x" * 10, encoding="utf-8")
    assert [c.text for c in _chunks(root)] == ["x" * 10]


def test_a_symlink_that_leaves_the_project_is_refused(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# Secret\n\nText.", encoding="utf-8")
    root = make_project(
        tmp_path / "p", {"kb/a.md": "# A\n\nText."}, {"kb": {"sources": ["kb/*.md"]}}
    )
    (root / "kb" / "link.md").symlink_to(outside)

    with pytest.raises(ConfigurationError, match="which is outside the project"):
        _chunks(root)


def _sqlite_project(tmp_path):
    root = make_project(tmp_path / "p", {}, {})
    with sqlite3.connect(root / "warehouse.db") as conn:
        conn.execute("CREATE TABLE kb (article_id TEXT, title TEXT, body TEXT, product TEXT)")
        conn.execute("INSERT INTO kb VALUES ('A1', 'Refunds', 'Money back in 5 days.', 'web')")
    config = {
        "project_name": "kb",
        "connections": {"warehouse": {"type": "sqlite", "path": "warehouse.db"}},
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


def test_a_database_source_reads_rows_once_into_a_snapshot(tmp_path):
    root = _sqlite_project(tmp_path)

    (only,) = _chunks(root)
    assert (only.id, only.title, only.origin, only.metadata) == (
        "A1",
        "Refunds",
        "warehouse",
        {"product": "web"},
    )
    snapshots = list((root / ".agac/knowledge/kb/snapshots").rglob("part-*.json"))
    assert len(snapshots) == 1

    # A later scan reads the snapshot and never connects.
    (root / "warehouse.db").unlink()
    (again,) = _chunks(root)
    assert again == only


def test_a_refresh_of_the_run_input_does_not_read_a_knowledge_snapshot_again(tmp_path):
    """Only ``agac knowledge build --refresh`` reads the query again, not ``--refresh-input``."""
    from agent_actions.input.loaders.database_source import (
        forget_refresh_request,
        request_refresh,
    )

    root = _sqlite_project(tmp_path)
    (only,) = _chunks(root)
    with sqlite3.connect(root / "warehouse.db") as conn:
        conn.execute("UPDATE kb SET body = 'Money back in 9 days.'")

    request_refresh()
    try:
        (kept,) = _chunks(root)
        (refreshed,) = chunk(scan(root, "kb", load_knowledge(root)["kb"], refresh=True))
    finally:
        forget_refresh_request()

    assert kept == only
    assert refreshed.body == "Money back in 9 days."


def test_a_database_source_with_no_snapshot_refuses_when_it_may_not_connect(tmp_path):
    root = _sqlite_project(tmp_path)

    with pytest.raises(ConfigurationError) as caught:
        scan(root, "kb", load_knowledge(root)["kb"], connect=False)

    assert "this command does not connect to a database" in str(caught.value)
    assert "agac knowledge build kb" in str(caught.value)
