"""One search of a knowledge base, as the retrieve step and ``agac knowledge search`` run it.

Each method searches with ``candidates`` results and ``where`` inside its query; a list of
methods is merged by weighted reciprocal rank fusion. Then ``max_per_origin``,
``max_context_tokens`` and ``top_k`` apply, in that order.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_actions.input.preprocessing.transformation.markdown_splitter import count_tokens
from agent_actions.knowledge.index import connection
from agent_actions.knowledge.methods import METHODS, Hit

logger = logging.getLogger(__name__)

RRF_K = 60
MATCH_KEYS = ("id", "rank", "score", "text", "title", "origin", "hash", "metadata")

# One warning per step and process: a run is one process.
_warned: set[str] = set()
_warned_lock = threading.Lock()


def forget_warnings() -> None:
    with _warned_lock:
        _warned.clear()


@dataclass(frozen=True)
class Limits:
    top_k: int
    candidates: int
    max_context_tokens: int | None = None
    max_per_origin: int | None = None


def fused(ranked: Mapping[str, list[Hit]], weights: Mapping[str, float]) -> list[Hit]:
    """The hits of each method merged by weighted RRF; one method keeps its own scores.

    Order: fused score, then the best rank any method gave, then the chunk id.
    """
    if len(ranked) == 1:
        return list(next(iter(ranked.values())))
    scores: dict[str, float] = {}
    best: dict[str, int] = {}
    for method, hits in ranked.items():
        for rank, (chunk_id, _) in enumerate(hits, 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weights[method] / (RRF_K + rank)
            best[chunk_id] = min(best.get(chunk_id, rank), rank)
    order = sorted(scores, key=lambda cid: (-scores[cid], best[cid], cid))
    return [(cid, scores[cid]) for cid in order]


def search(
    paths: Mapping[str, Path],
    methods: Mapping[str, float],
    text: str,
    limits: Limits,
    where: Sequence[tuple[str, Any]],
    digest: str,
    *,
    label: str = "",
) -> dict[str, Any]:
    """The step's output for one query: ``matches``, ``count``, ``query`` and ``index``.

    *paths* holds the index file of each kind *methods* read.
    """
    ranked: dict[str, list[Hit]] = {}
    compiled: dict[str, str] = {}
    for name, method in METHODS.items():
        if name not in methods:
            continue
        compiled[name] = method.compile(text)
        conn = connection(paths[method.index])
        ranked[name] = method.search(conn, text, limits.candidates, where)
    hits = fused(ranked, methods)
    rows = _chunks(next(iter(paths.values())), [cid for cid, _ in hits])
    matches: list[dict[str, Any]] = []
    per_origin: dict[str, int] = {}
    tokens = 0
    for chunk_id, score in hits:
        if len(matches) == limits.top_k:
            break
        row = rows[chunk_id]
        if limits.max_per_origin is not None:
            if per_origin.get(row["origin"], 0) >= limits.max_per_origin:
                continue
        if limits.max_context_tokens is not None:
            size = count_tokens(row["text"])
            if tokens + size > limits.max_context_tokens:
                if not matches:
                    _warn_once(label, limits.max_context_tokens, size)
                break
            tokens += size
        per_origin[row["origin"]] = per_origin.get(row["origin"], 0) + 1
        match = {**row, "rank": len(matches) + 1, "score": round(score, 6)}
        matches.append({key: match[key] for key in MATCH_KEYS})
    return {
        "matches": matches,
        "count": len(matches),
        "query": _query(compiled),
        "index": digest,
    }


def empty(digest: str) -> dict[str, Any]:
    return {"matches": [], "count": 0, "query": "", "index": digest}


def _query(compiled: Mapping[str, str]) -> str:
    """The compiled query of one method, or each method's, named."""
    if len(compiled) == 1:
        return next(iter(compiled.values()))
    return " | ".join(f"{name}: {query}" for name, query in compiled.items())


def _chunks(path: Path, ids: list[str]) -> dict[str, dict[str, Any]]:
    conn = connection(path)
    rows: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), 500):
        part = ids[start : start + 500]
        placeholders = ",".join("?" for _ in part)
        for chunk_id, title, text, origin, digest, metadata in conn.execute(
            "SELECT id, title, text, origin, hash, metadata FROM chunks "
            f"WHERE id IN ({placeholders})",
            part,
        ):
            rows[chunk_id] = {
                "id": chunk_id,
                "title": title,
                "text": text,
                "origin": origin,
                "hash": digest,
                "metadata": json.loads(metadata),
            }
    return rows


def _warn_once(label: str, limit: int, size: int) -> None:
    with _warned_lock:
        if label in _warned:
            return
        _warned.add(label)
    logger.warning(
        "%s: the best match alone holds %d tokens, more than max_context_tokens (%d), so a "
        "record gets no match. Raise max_context_tokens, or lower the base's chunk_size",
        label or "retrieve",
        size,
        limit,
    )
