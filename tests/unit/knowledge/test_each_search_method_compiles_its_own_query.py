"""Each method compiles its own query from raw text, and no FTS5 syntax reaches SQLite.

keyword: any word, stemmed, stopwords dropped. all_words: every word. phrase: the exact
phrase. fuzzy: trigrams of each word. key: the chunk whose id is the text. ``where`` is
applied inside each search, and a value of None matches nothing.
"""

from __future__ import annotations

import json

import pytest

from agent_actions.knowledge.methods import (
    MAX_TERMS,
    MAX_TRIGRAMS,
    all_words_query,
    fuzzy_query,
    keyword_query,
    phrase_query,
)
from tests.unit.knowledge.conftest import find, make_project

FAQ = json.dumps(
    [
        {"faq": f, "q": q, "a": a, "product": p}
        for f, q, a, p in [
            ("pw", "Resetting your password", "Use Forgot password on the sign-in page.", "web"),
            ("dup", "Duplicate charges", "A second charge is a pending authorization.", "billing"),
            ("refund", "Refund policy", "Annual plans are refunded within 30 days.", "billing"),
            ("login", "Cannot sign in", "If you can not log in, check caps lock.", "web"),
        ]
    ]
)


@pytest.fixture
def root(tmp_path):
    return make_project(
        tmp_path / "p",
        {"seed/faq.json": FAQ},
        {
            "faq": {
                "sources": [
                    {
                        "path": "seed/faq.json",
                        "text": ["q", "a"],
                        "title": "q",
                        "id": "faq",
                        "metadata": ["product"],
                    }
                ],
                "index": ["keyword", "fuzzy"],
            }
        },
    )


def _ids(root, method, text, **limits):
    return [m["id"] for m in find(root, "faq", {method: 1.0}, text, **limits)["matches"]]


HOSTILE = ["NEAR(", '"x', "can't", "col:", "title:refund", "a* OR ^b", "AND OR NOT", ")(", '"""']


@pytest.mark.parametrize("hostile", HOSTILE)
@pytest.mark.parametrize("method", ["keyword", "all_words", "phrase", "fuzzy", "key"])
def test_a_hostile_query_is_searched_as_words(root, method, hostile):
    find(root, "faq", {method: 1.0}, hostile)


@pytest.mark.parametrize(
    "compile_query", [keyword_query, all_words_query, phrase_query, fuzzy_query]
)
@pytest.mark.parametrize("hostile", HOSTILE)
def test_a_compiled_query_holds_only_quoted_word_terms(compile_query, hostile):
    query = compile_query(hostile)
    for term in query.replace(" OR ", "\n").replace(" AND ", "\n").splitlines():
        assert term.startswith('"') and term.endswith('"')
        assert all(ch.isalnum() or ch in ' "_' for ch in term), query


def test_keyword_matches_any_word_with_stems_and_no_stopwords(root):
    assert _ids(root, "keyword", "I was charged twice")[0] == "dup"
    assert _ids(root, "keyword", "refunds")[0] == "refund"
    assert keyword_query("The refund of my order") == '"refund" OR "order"'
    assert keyword_query("can't col:x") == '"col" OR "x"'
    assert _ids(root, "keyword", "the of and") == []


def test_all_words_needs_every_word(root):
    assert _ids(root, "all_words", "pending charge") == ["dup"]
    assert _ids(root, "all_words", "pending refund") == []


def test_phrase_needs_the_exact_phrase_with_its_stopwords(root):
    assert phrase_query("Can not log in!") == '"can not log in"'
    assert _ids(root, "phrase", "can not log in") == ["login"]
    assert _ids(root, "phrase", "log can not") == []


def test_fuzzy_finds_a_misspelled_word(root):
    assert _ids(root, "fuzzy", "pasword")[0] == "pw"
    assert _ids(root, "fuzzy", "refnd polcy")[0] == "refund"
    # A word under three characters adds nothing.
    assert fuzzy_query("go to it") == ""


def test_key_finds_the_chunk_whose_id_is_the_text(root):
    assert _ids(root, "key", " refund ") == ["refund"]
    assert _ids(root, "key", "refund policy") == []


def test_a_query_keeps_at_most_its_term_limits():
    many = " ".join(f"word{i}" for i in range(100))
    assert keyword_query(many).count(" OR ") == MAX_TERMS - 1
    assert fuzzy_query(many).count(" OR ") == MAX_TRIGRAMS - 1


def test_top_k_limits_the_matches(root):
    assert len(_ids(root, "fuzzy", "password sign charge refund", top_k=2)) == 2
    assert len(_ids(root, "fuzzy", "password sign charge refund", top_k=3)) == 3


def test_a_where_value_matches_exactly_and_none_matches_nothing(root):
    assert _ids(root, "keyword", "sign", where={"product": "web"}) == ["login", "pw"]
    assert _ids(root, "keyword", "sign", where={"product": "billing"}) == []
    assert _ids(root, "keyword", "sign", where={"product": None}) == []
    assert _ids(root, "fuzzy", "sign", where={"product": None}) == []


def test_where_is_applied_inside_the_search_before_candidates(tmp_path):
    rows = [{"id": f"a{i}", "text": "refund refund refund", "p": "a"} for i in range(30)]
    rows.append({"id": "b1", "text": "refund policy", "p": "b"})
    root = make_project(
        tmp_path / "w",
        {"rows.json": json.dumps(rows)},
        {
            "rows": {
                "sources": [{"path": "rows.json", "text": "text", "id": "id", "metadata": "p"}]
            }
        },
    )

    result = find(
        root, "rows", {"keyword": 1.0}, "refund", top_k=3, candidates=5, where={"p": "b"}
    )

    assert [m["id"] for m in result["matches"]] == ["b1"]


def test_max_per_origin_limits_the_chunks_of_one_document(tmp_path):
    files = {f"kb/{n}.md": f"# A\n\nrefund one {n}\n\n# B\n\nrefund two {n}" for n in "abc"}
    root = make_project(tmp_path / "t", files, {"kb": {"sources": ["kb/*.md"]}})

    result = find(root, "kb", {"keyword": 1.0}, "refund", max_per_origin=1)

    assert sorted(m["origin"] for m in result["matches"]) == ["kb/a.md", "kb/b.md", "kb/c.md"]


def test_a_best_chunk_over_max_context_tokens_gives_no_match_and_one_warning(root, caplog):
    for _ in range(3):
        result = find(
            root,
            "faq",
            {"keyword": 1.0},
            "password",
            max_context_tokens=3,
            label="w: retrieve 'h'",
        )
        assert result["count"] == 0

    warnings = [r for r in caplog.records if "max_context_tokens (3)" in r.getMessage()]
    assert len(warnings) == 1
    assert warnings[0].getMessage().startswith("w: retrieve 'h': the best match alone")


def test_max_context_tokens_keeps_the_best_chunks_that_fit(root):
    result = find(root, "faq", {"fuzzy": 1.0}, "password sign charge", max_context_tokens=30)
    assert 1 <= result["count"] < 4


def test_the_output_has_the_frozen_shape(root):
    result = find(root, "faq", {"keyword": 1.0}, "charged twice", top_k=1)

    assert set(result) == {"matches", "count", "query", "index"}
    match = result["matches"][0]
    assert list(match) == ["id", "rank", "score", "text", "title", "origin", "hash", "metadata"]
    assert match["rank"] == 1 and match["score"] > 0
    assert match["title"] == "Duplicate charges"
    assert match["origin"] == "seed/faq.json"
    assert match["metadata"] == {"product": "billing"}
    assert result["query"] == '"charged" OR "twice"'
    assert len(result["index"]) == 16


def test_two_methods_merge_and_report_each_query(root):
    result = find(root, "faq", {"keyword": 0.7, "fuzzy": 0.3}, "pasword reset")

    assert result["matches"][0]["id"] == "pw"
    assert result["query"].startswith('keyword: "pasword" OR "reset" | fuzzy: ')
