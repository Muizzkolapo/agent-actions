"""What the run path and the retrieve step call: config, digests, builds and one search.

A step searches a knowledge base, or the records an earlier action processed (an action
corpus, indexed by ``index_action_corpus`` when the step starts).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_actions.errors import ConfigurationError
from agent_actions.knowledge.config import KnowledgeBase
from agent_actions.knowledge.methods import INDEX_FOR_METHOD as _INDEX_FOR_METHOD
from agent_actions.knowledge.methods import METHODS

if TYPE_CHECKING:
    from agent_actions.knowledge.action_corpus import CorpusChange, CorpusIndex

__all__ = [
    "INDEX_FOR_METHOD",
    "KNOWN_METHODS",
    "KnowledgeBase",
    "KnowledgeConfigError",
    "ensure_indexes",
    "knowledge_hash",
    "action_corpus_change",
    "index_action_corpus",
    "load_knowledge_config",
    "retrieve",
    "retrieve_from_corpus",
]

KNOWN_METHODS: frozenset[str] = frozenset(METHODS)
INDEX_FOR_METHOD: Mapping[str, str] = dict(_INDEX_FOR_METHOD)


class KnowledgeConfigError(ConfigurationError):
    """A knowledge base that cannot be loaded, read or built as configured."""


def _as_knowledge_error(error: ConfigurationError) -> KnowledgeConfigError:
    if isinstance(error, KnowledgeConfigError):
        return error
    return KnowledgeConfigError(str(error), context=dict(error.context))


def load_knowledge_config(project_root: Path) -> dict[str, KnowledgeBase]:
    """The validated ``knowledge:`` section of agent_actions.yml; {} when there is none.

    Reads the config only, no source file.
    """
    from agent_actions.knowledge.config import load_knowledge

    try:
        return load_knowledge(project_root)
    except ConfigurationError as e:
        raise _as_knowledge_error(e) from None


def _base(project_root: Path, base: str) -> KnowledgeBase:
    from agent_actions.knowledge.config import unknown_base_message

    bases = load_knowledge_config(project_root)
    if base not in bases:
        raise KnowledgeConfigError(
            unknown_base_message(base, bases), context={"knowledge_base": base}
        )
    return bases[base]


def knowledge_hash(
    project_root: Path, base: str, indexes: set[str], *, sandbox: bool
) -> str | None:
    """The digest the current sources would build for *indexes*, without building.

    None when it cannot be computed now, such as a database source with no snapshot.
    Never connects. *sandbox* is accepted for symmetry with ``ensure_indexes``.
    """
    from agent_actions.knowledge.chunks import scan
    from agent_actions.knowledge.index import combined_digest, kind_digests

    try:
        found = scan(project_root, base, _base(project_root, base), connect=False)
    except ConfigurationError:
        return None
    return combined_digest(kind_digests(found, indexes))


def ensure_indexes(project_root: Path, base: str, indexes: set[str], *, sandbox: bool) -> str:
    """Build *indexes* of *base* when they are stale, and return their digest.

    Builds under the project lock, through a temporary file and ``os.replace``, and logs
    one line when it builds. A sandbox run with no database snapshot is refused.
    """
    from agent_actions.knowledge.chunks import scan
    from agent_actions.knowledge.index import build_indexes

    try:
        found = scan(project_root, base, _base(project_root, base), connect=not sandbox)
        digest, _ = build_indexes(project_root, found, indexes)
    except ConfigurationError as e:
        raise _as_knowledge_error(e) from None
    return digest


def retrieve(
    project_root: Path,
    *,
    base: str,
    digest: str,
    methods: Mapping[str, float],
    query_text: str,
    where: Mapping[str, Any],
    top_k: int,
    candidates: int,
    max_context_tokens: int | None,
    max_per_origin: int | None,
    label: str = "",
) -> dict[str, Any]:
    """The step's output: ``matches``, ``count``, ``query`` and ``index`` (*digest*).

    Opens the index read-only and is safe from many threads. A ``where`` value of None
    matches nothing. *label* names the step in the one warning ``max_context_tokens``
    can give per run.
    """
    from agent_actions.knowledge.index import locate
    from agent_actions.knowledge.search import Limits, empty, search

    unknown = sorted(set(methods) - KNOWN_METHODS)
    if unknown:
        raise KnowledgeConfigError(
            f"Unknown search method {', '.join(unknown)}; the methods are {', '.join(METHODS)}",
            context={"knowledge_base": base},
        )
    try:
        paths = locate(project_root, base, digest, {INDEX_FOR_METHOD[m] for m in methods})
    except ConfigurationError as e:
        raise _as_knowledge_error(e) from None
    if any(value is None for value in where.values()):
        return empty(digest)
    limits = Limits(top_k, candidates, max_context_tokens, max_per_origin)
    return search(paths, methods, query_text, limits, list(where.items()), digest, label=label)


def index_action_corpus(
    folder: Path,
    corpus: Mapping[str, Any],
    methods: Iterable[str],
    rows: Iterable[Any],
    *,
    label: str,
) -> CorpusIndex:
    """Index the records the ``from:`` action of a step processed, before the step runs.

    *rows* are that action's stored rows, read before the downstream reset. Writes
    ``<folder>/<digest>.db`` unless it exists.
    """
    from agent_actions.knowledge.action_corpus import (
        CorpusSettings,
        build_corpus_index,
        corpus_records,
        processed_outputs,
    )

    settings = CorpusSettings.of(corpus)
    records = corpus_records(processed_outputs(rows, settings.action), settings, label)
    kinds = {INDEX_FOR_METHOD[method] for method in methods}
    return build_corpus_index(folder, settings, kinds, records, label)


def action_corpus_change(
    folder: Path, index: CorpusIndex, answers: Sequence[tuple[str, str]]
) -> CorpusChange:
    """How *index* differs from what the step's stored answers searched, once the step ran.

    *answers* are the ``(source_guid, index)`` of each answer the step holds. Index files
    of *folder* that neither *index* nor an answer names are removed.
    """
    from agent_actions.knowledge.action_corpus import corpus_change, prune

    change = corpus_change(folder, index.records, answers, index.digest)
    prune(folder, {index.digest} | {digest for _, digest in answers})
    return change


def retrieve_from_corpus(
    corpus: CorpusIndex,
    *,
    methods: Mapping[str, float],
    query_text: str,
    where: Mapping[str, Any],
    top_k: int,
    candidates: int,
    max_context_tokens: int | None,
    exclude: str | None,
    label: str = "",
) -> dict[str, Any]:
    """The step's output for one record of an action corpus; *exclude* is its own chunk."""
    from agent_actions.knowledge.search import Limits, empty, search

    if any(value is None for value in where.values()):
        return empty(corpus.digest)
    limits = Limits(top_k, candidates, max_context_tokens, None)
    return search(
        corpus.paths,
        methods,
        query_text,
        limits,
        list(where.items()),
        corpus.digest,
        label=label,
        exclude=exclude,
    )
