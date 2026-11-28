"""A 10,000-record action corpus is indexed and searched within a time budget (D24).

Each record searches the whole corpus, so a step's time grows with the square of its corpus.
The budgets are generous for a slow CI machine; they catch a search that reads every record
or a build that indexes one record at a time.
"""

from __future__ import annotations

import logging
import random
import time

from agent_actions.knowledge.action_corpus import MANY_RECORDS
from agent_actions.knowledge.api import (
    action_corpus_change,
    index_action_corpus,
    retrieve_from_corpus,
)

LABEL = "link: retrieve 'similar' (link__similar)"
CORPUS = {"action": "summarize", "text": ["summary"], "id": "ticket_id"}
WORDS = (
    "charged twice invoice refund card payment app crash upload photo email address account "
    "password reset login order cancelled delivery late parcel missing broken screen battery "
    "update install error message slow sync contact support billing plan upgrade downgrade"
).split()


def _rows(count: int) -> list[dict]:
    pick = random.Random(7)
    return [
        {
            "source_guid": f"g{n}",
            "_state": "processed",
            "content": {
                "summarize": {
                    "ticket_id": f"T-{n}",
                    "summary": " ".join(pick.choice(WORDS) for _ in range(12)),
                }
            },
        }
        for n in range(count)
    ]


def test_a_10000_record_corpus_is_indexed_and_searched_within_the_budget(tmp_path):
    rows = _rows(10_000)

    started = time.perf_counter()
    index, _ = prepare(tmp_path, CORPUS, ["keyword"], rows, [], label=LABEL)
    built = time.perf_counter() - started

    queries = [row["content"]["summarize"]["summary"] for row in rows[:200]]
    started = time.perf_counter()
    for n, query in enumerate(queries):
        result = retrieve_from_corpus(
            index,
            methods={"keyword": 1.0},
            query_text=query,
            where={},
            top_k=3,
            candidates=20,
            max_context_tokens=None,
            exclude=index.chunk_ids[f"g{n}"],
        )
        assert result["count"] == 3
    per_search = (time.perf_counter() - started) / len(queries)

    assert built < 10.0
    assert per_search < 0.1


def test_a_corpus_of_more_than_20000_records_warns_of_the_cost(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        prepare(tmp_path, CORPUS, ["keyword"], _rows(MANY_RECORDS + 1), [], label=LABEL)

    assert f"{LABEL}: the corpus holds 20,001 records, more than 20,000" in caplog.text
    assert "grows with the square of the corpus" in caplog.text


def prepare(folder, corpus, methods, rows, answers, *, label):
    """Index the records, then compare with *answers*, as a run of the step does."""
    index = index_action_corpus(folder, corpus, methods, rows, label=label)
    return index, action_corpus_change(folder, index, answers)
