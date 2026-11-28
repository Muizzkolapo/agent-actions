"""In an action corpus the record itself is never a match, and it still gets `top_k` matches."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_actions.knowledge.action_corpus import (
    CorpusSettings,
    build_corpus_index,
    corpus_records,
)
from agent_actions.knowledge.api import retrieve_from_corpus

LABEL = "link: retrieve 'similar' (link__similar)"
SETTINGS = CorpusSettings("summarize", ("summary",), id="ticket_id")
SUMMARIES = {
    "T-1": "charged twice for the invoice",
    "T-2": "charged twice on the card",
    "T-3": "the invoice was charged twice",
    "T-4": "an invoice charged on the wrong card",
    "T-5": "the app closes on upload",
}


def _corpus(tmp_path, summaries=SUMMARIES, methods=("keyword",)):
    outputs = [(f"g-{t}", {"ticket_id": t, "summary": s}) for t, s in summaries.items()]
    records = corpus_records(outputs, SETTINGS, LABEL)
    kinds = {"fuzzy" if m == "fuzzy" else "keyword" for m in methods}
    return build_corpus_index(tmp_path / "link__similar", SETTINGS, kinds, records, LABEL)


def _search(corpus, ticket, top_k=2, methods=None, **extra):
    settings = {
        "methods": methods or {"keyword": 1.0},
        "query_text": SUMMARIES[ticket],
        "where": {},
        "top_k": top_k,
        "candidates": 20,
        "max_context_tokens": None,
        "exclude": corpus.chunk_ids.get(f"g-{ticket}"),
        **extra,
    }
    return retrieve_from_corpus(corpus, **settings)


@pytest.mark.parametrize("ticket", sorted(SUMMARIES))
def test_each_record_gets_top_k_matches_and_never_itself(tmp_path, ticket):
    corpus = _corpus(tmp_path)

    result = _search(corpus, ticket)

    ids = [m["id"] for m in result["matches"]]
    assert ticket not in ids
    if ticket != "T-5":
        assert len(ids) == 2
    assert [m["rank"] for m in result["matches"]] == list(range(1, len(ids) + 1))


def test_a_fused_search_never_matches_the_record_itself(tmp_path):
    corpus = _corpus(tmp_path, methods=("keyword", "fuzzy"))

    result = _search(corpus, "T-1", methods={"keyword": 1.0, "fuzzy": 1.0}, top_k=3)

    ids = [m["id"] for m in result["matches"]]
    assert "T-1" not in ids
    assert len(ids) == 3


def test_a_record_not_in_the_corpus_gets_top_k_matches(tmp_path):
    corpus = _corpus(tmp_path)

    result = _search(corpus, "T-1", exclude=None)

    assert len(result["matches"]) == 2
    assert result["matches"][0]["id"] == "T-1"


def test_a_corpus_smaller_than_top_k_gives_every_other_record(tmp_path):
    corpus = _corpus(tmp_path, summaries={"T-1": "charged twice", "T-2": "charged twice"})

    result = _search(corpus, "T-1", top_k=5, query_text="charged twice")

    assert [m["id"] for m in result["matches"]] == ["T-2"]


def test_a_match_names_the_record_its_action_and_its_source_guid(tmp_path):
    corpus = _corpus(tmp_path)

    match = _search(corpus, "T-1")["matches"][0]

    assert match["origin"] == "summarize"
    assert match["metadata"]["source_guid"] == f"g-{match['id']}"
    assert match["text"] == SUMMARIES[match["id"]]


def test_a_where_value_of_none_matches_nothing(tmp_path):
    corpus = _corpus(tmp_path)

    result = _search(corpus, "T-1", where={"ticket_id": None})

    assert result["matches"] == []
    assert result["index"] == corpus.digest


def test_sixteen_concurrent_records_all_report_one_index(tmp_path):
    summaries = {f"T-{n}": f"charged twice for invoice {n}" for n in range(16)}
    corpus = _corpus(tmp_path, summaries=summaries)

    def one(n):
        return retrieve_from_corpus(
            corpus,
            methods={"keyword": 1.0},
            query_text=summaries[f"T-{n}"],
            where={},
            top_k=3,
            candidates=20,
            max_context_tokens=None,
            exclude=corpus.chunk_ids[f"g-T-{n}"],
        )

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(one, range(16)))

    assert {r["index"] for r in results} == {corpus.digest}
    for n, result in enumerate(results):
        assert f"T-{n}" not in [m["id"] for m in result["matches"]]
        assert result["count"] == 3
