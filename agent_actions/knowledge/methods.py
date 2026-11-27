"""The search methods of a knowledge base: each builds its index and searches it.

A method compiles its own query from the raw query text, so no FTS5 syntax a record holds
reaches SQLite. ``where`` is applied inside each search, before the ``candidates`` limit.
Adding a method changes only this module, its tests and one docs row.
"""

from __future__ import annotations

import functools
import json
import re
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from agent_actions.knowledge.chunks import Chunk

MAX_TERMS = 32
MAX_TRIGRAMS = 64
TITLE_WEIGHT = 2.0
_WORD = re.compile(r"\w+")

# English stopwords, and the pieces a contraction leaves (can't -> can, t).
STOPWORDS = frozenset(
    """a about above after again against all am an and any are as at be because been before
    being below between both but by can could d did do does doing down during each few for
    from further had has have having he her here hers herself him himself his how i if in
    into is it its itself just ll m me more most my myself no nor not now o of off on once
    only or other our ours ourselves out over own please re s same she should so some such t
    than that the their theirs them themselves then there these they this those through to
    too under until up ve very was we were what when where which while who whom why will
    with would y you your yours yourself yourselves""".split()
)

WORDS_TABLE = "words"
TRIGRAMS_TABLE = "trigrams"
TOKENIZERS = {
    "keyword": "porter unicode61 remove_diacritics 2",
    "fuzzy": "trigram remove_diacritics 1",
}
# What each index kind's digest covers besides the content.
INDEX_SETTINGS = {**TOKENIZERS, "key": "exact id"}
_TABLES = {"keyword": WORDS_TABLE, "fuzzy": TRIGRAMS_TABLE}

Where = Sequence[tuple[str, Any]]
Hit = tuple[str, float]


def terms(text: str, *, keep_stopwords: bool = False) -> list[str]:
    """The lowercase word tokens of *text*, each once, in order."""
    words = [w for w in _WORD.findall(text.lower()) if keep_stopwords or w not in STOPWORDS]
    return list(dict.fromkeys(words))


def _quoted(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def keyword_query(text: str) -> str:
    return " OR ".join(_quoted(t) for t in terms(text)[:MAX_TERMS])


def all_words_query(text: str) -> str:
    return " AND ".join(_quoted(t) for t in terms(text)[:MAX_TERMS])


def phrase_query(text: str) -> str:
    words = _WORD.findall(text.lower())[:MAX_TERMS]
    return _quoted(" ".join(words)) if words else ""


def fuzzy_query(text: str) -> str:
    grams: list[str] = []
    for term in terms(text):
        grams.extend(term[i : i + 3] for i in range(len(term) - 2))
    unique = list(dict.fromkeys(grams))[:MAX_TRIGRAMS]
    return " OR ".join(_quoted(g) for g in unique)


def key_query(text: str) -> str:
    return text.strip()


def build_chunks_table(conn: sqlite3.Connection, chunks: Iterable[Chunk]) -> None:
    conn.execute(
        "CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, title TEXT, "
        "text TEXT, body TEXT, origin TEXT, hash TEXT, metadata TEXT)"
    )
    conn.executemany(
        "INSERT INTO chunks (id, title, text, body, origin, hash, metadata) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            (c.id, c.title, c.text, c.body, c.origin, c.hash, json.dumps(c.metadata, default=str))
            for c in chunks
        ),
    )


def _build_fts(kind: str) -> Callable[[sqlite3.Connection], None]:
    def build(conn: sqlite3.Connection) -> None:
        table = _TABLES[kind]
        conn.execute(
            f"CREATE VIRTUAL TABLE {table} USING fts5(title, body, "
            f"content='chunks', content_rowid='rowid', tokenize='{TOKENIZERS[kind]}')"
        )
        conn.execute(
            f"INSERT INTO {table}(rowid, title, body) SELECT rowid, title, body FROM chunks"
        )

    return build


def _where_sql(where: Where) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    for key, value in where:
        clauses.append("json_extract(c.metadata, ?) = ?")
        params.extend(['$."' + key.replace('"', '\\"') + '"', value])
    return "".join(f" AND {clause}" for clause in clauses), params


def _fts_search(kind: str, compile_query: Callable[[str], str]) -> Callable[..., list[Hit]]:
    def search(conn: sqlite3.Connection, text: str, candidates: int, where: Where) -> list[Hit]:
        query = compile_query(text)
        if not query:
            return []
        table = _TABLES[kind]
        extra, params = _where_sql(where)
        rows = conn.execute(
            f"SELECT c.id, bm25({table}, {TITLE_WEIGHT}, 1.0) AS rank FROM {table} "
            f"JOIN chunks c ON c.rowid = {table}.rowid WHERE {table} MATCH ?{extra} "
            "ORDER BY rank, c.id LIMIT ?",
            [query, *params, candidates],
        ).fetchall()
        return [(row[0], -float(row[1])) for row in rows]

    return search


def _key_search(conn: sqlite3.Connection, text: str, candidates: int, where: Where) -> list[Hit]:
    key = key_query(text)
    if not key:
        return []
    extra, params = _where_sql(where)
    rows = conn.execute(
        f"SELECT c.id FROM chunks c WHERE c.id = ?{extra} LIMIT ?", [key, *params, candidates]
    ).fetchall()
    return [(row[0], 1.0) for row in rows]


@dataclass(frozen=True)
class Method:
    """A search method: the index it reads, how that index is built, and its search."""

    name: str
    index: str
    compile: Callable[[str], str]
    search: Callable[[sqlite3.Connection, str, int, Where], list[Hit]]

    def build(self, conn: sqlite3.Connection) -> None:
        INDEX_BUILDERS[self.index](conn)


def _chunks_only(conn: sqlite3.Connection) -> None:
    """The ``key`` index is the chunks table every index file holds."""


INDEX_BUILDERS: dict[str, Callable[[sqlite3.Connection], None]] = {
    **{kind: _build_fts(kind) for kind in TOKENIZERS},
    "key": _chunks_only,
}

# In the order a fused search adds them.
METHODS: dict[str, Method] = {
    "keyword": Method("keyword", "keyword", keyword_query, _fts_search("keyword", keyword_query)),
    "all_words": Method(
        "all_words", "keyword", all_words_query, _fts_search("keyword", all_words_query)
    ),
    "phrase": Method("phrase", "keyword", phrase_query, _fts_search("keyword", phrase_query)),
    "fuzzy": Method("fuzzy", "fuzzy", fuzzy_query, _fts_search("fuzzy", fuzzy_query)),
    "key": Method("key", "key", key_query, _key_search),
}
INDEX_FOR_METHOD = {name: method.index for name, method in METHODS.items()}
COMBINABLE = tuple(name for name in METHODS if name != "key")


@functools.cache
def trigram_supported() -> bool:
    try:
        sqlite3.connect(":memory:").execute(
            f"CREATE VIRTUAL TABLE t USING fts5(x, tokenize='{TOKENIZERS['fuzzy']}')"
        )
    except sqlite3.OperationalError:
        return False
    return True
