"""The records an earlier action processed, as the corpus a retrieve step searches.

Each processed record is one chunk: its ``text`` fields joined with spaces. The index is
one file, ``<digest>.db``, in the step's folder; the digest covers the step's
``text``/``title``/``id`` settings, the index format, the tokenizers and each record's
``(source_guid, hash)``. The file also holds that pair of each record, so a later run can
tell which records were added, changed or removed since an answer searched it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigurationError
from agent_actions.knowledge.chunks import Chunk
from agent_actions.knowledge.index import FORMAT_VERSION, write_index_file
from agent_actions.knowledge.methods import INDEX_SETTINGS

logger = logging.getLogger(__name__)

# Changes when the same records would give a different index file.
CORPUS_FORMAT = 1
PROCESSED = "processed"
# Each record searches the whole corpus, so the step's time grows with its square.
MANY_RECORDS = 20_000
OVERSIZED_TOKENS = 2_000
# Under the run folder: agent_io/, or agent_io/sandbox/ in a sandbox run.
RETRIEVE_DIR = "retrieve"


def corpus_folder(run_dir: Path, step: str) -> Path:
    """Where the index files of *step* are: ``<run folder>/retrieve/<step>/``."""
    return run_dir / RETRIEVE_DIR / step


@dataclass(frozen=True)
class CorpusSettings:
    """What a retrieve step reads of each record of its ``from:`` action."""

    action: str
    text: tuple[str, ...]
    title: str | None = None
    id: str | None = None

    @classmethod
    def of(cls, spec: Mapping[str, Any]) -> CorpusSettings:
        return cls(spec["action"], tuple(spec["text"]), spec.get("title"), spec.get("id"))


@dataclass(frozen=True)
class CorpusRecord:
    source_guid: str
    chunk: Chunk
    # Covers what the index stores of the record: its id, title, text and metadata.
    hash: str


@dataclass(frozen=True)
class CorpusIndex:
    """The index a step searches in this run, and the chunk id of each record in it."""

    digest: str
    path: Path
    kinds: frozenset[str]
    chunk_ids: Mapping[str, str]
    # Each record's source_guid and hash, to compare with an older index.
    records: Mapping[str, str]
    # Whether this call wrote the file (False when an earlier run built it).
    built: bool = False

    @property
    def paths(self) -> dict[str, Path]:
        return dict.fromkeys(self.kinds, self.path)


def _many(count: int, one: str, many: str) -> str:
    return f"{count:,} {one if count == 1 else many}"


@dataclass
class CorpusChange:
    """How the corpus differs from what the step's stored answers searched."""

    records: int
    # Whether this run built the index the step searched: the corpus changed since the last run.
    new_index: bool = False
    added: int = 0
    changed: int = 0
    removed: int = 0
    # Stored answers that searched an older index.
    stale_answers: int = 0
    # Of those, the answers whose index file is gone, so what they saw is not known.
    unknown_answers: int = 0

    def message(self, step: str, label: str) -> tuple[int, str] | None:
        """The log level and line to report, or None when nothing is to be said.

        Records only added are reported once, by the run that adds them; changed or
        removed records, and answers whose index is gone, warn on each run until a rerun.
        """
        answers = _many(self.stale_answers, "earlier answer", "earlier answers")
        if self.changed or self.removed:
            was = "was" if self.added == 1 else "were"
            return logging.WARNING, (
                f"{label}: since {answers} searched the records, {self.changed:,} changed, "
                f"{self.removed:,} left and {self.added:,} {was} added, so those answers may "
                "show old text or cite a record that is gone. "
                f"Run again with --rerun {step} to search again"
            )
        if self.unknown_answers:
            unknown = _many(self.unknown_answers, "earlier answer", "earlier answers")
            return logging.WARNING, (
                f"{label}: {unknown} searched an index that is gone, so the changes since "
                f"are not known. Run again with --rerun {step} to search again"
            )
        if self.added and self.new_index:
            added = _many(self.added, "record was", "records were")
            return logging.INFO, (
                f"{label}: {added} added since {answers} searched; --rerun {step} to search again"
            )
        return None


def processed_outputs(rows: Iterable[Any], action: str) -> list[tuple[str, dict[str, Any]]]:
    """The ``(source_guid, output)`` of each row *action* processed, as stored.

    Read before the downstream reset, which marks a guard-skipped row active: a failed,
    exhausted, guard-skipped or tombstoned row is left out.
    """
    found: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("_state") != PROCESSED or row.get("_tombstone"):
            continue
        content = row.get("content")
        output = content.get(action) if isinstance(content, dict) else None
        guid = row.get("source_guid")
        if isinstance(output, dict) and isinstance(guid, str) and guid:
            found.append((guid, output))
    return found


def _field_text(value: Any, name: str, label: str) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(part for part in (_field_text(v, name, label) for v in value) if part)
    if isinstance(value, dict):
        raise ConfigurationError(
            f"{label}: text field '{name}' holds an object; a text field holds text, numbers "
            "or a list of them",
            context={"field": name},
        )
    return str(value)


def corpus_records(
    outputs: Sequence[tuple[str, dict[str, Any]]], settings: CorpusSettings, label: str
) -> list[CorpusRecord]:
    """One chunk per record; refuses a repeated ``source_guid`` or ``id`` value by name."""
    records: list[CorpusRecord] = []
    guids: set[str] = set()
    ids: dict[str, str] = {}
    for guid, output in outputs:
        if guid in guids:
            raise ConfigurationError(
                f"{label}: action '{settings.action}' holds more than one record with "
                f"source_guid '{guid}'. A retrieve step searches an action with one record "
                "per input record",
                context={"source_guid": guid, "from": settings.action},
            )
        guids.add(guid)
        body = " ".join(
            t for t in (_field_text(output.get(f), f, label) for f in settings.text) if t
        )
        title = (
            _field_text(output.get(settings.title), settings.title, label)
            if settings.title
            else ""
        )
        chunk_id = guid
        if settings.id is not None:
            chunk_id = _field_text(output.get(settings.id), settings.id, label)
            if not chunk_id:
                raise ConfigurationError(
                    f"{label}: the record with source_guid '{guid}' has no value in its id "
                    f"field '{settings.id}'",
                    context={"source_guid": guid, "field": settings.id},
                )
            if chunk_id in ids:
                raise ConfigurationError(
                    f"{label}: id '{chunk_id}' ({settings.id}) names the records with "
                    f"source_guid '{ids[chunk_id]}' and '{guid}'. Each id must name one "
                    "record, so a citation is not ambiguous",
                    context={"id": chunk_id, "field": settings.id},
                )
        ids[chunk_id] = guid
        metadata = {k: v for k, v in output.items() if k not in settings.text}
        metadata["source_guid"] = guid
        stored = json.dumps([chunk_id, title, body, metadata], sort_keys=True, default=str)
        records.append(
            CorpusRecord(
                source_guid=guid,
                chunk=Chunk(chunk_id, title, body, body, settings.action, metadata),
                hash=hashlib.sha256(stored.encode("utf-8")).hexdigest()[:16],
            )
        )
    _warn_of_missing_fields(outputs, settings, label)
    return records


def _warn_of_missing_fields(
    outputs: Sequence[tuple[str, dict[str, Any]]], settings: CorpusSettings, label: str
) -> None:
    """Warn of a `text` or `title` field no record holds; the load checks only a schema."""
    if not outputs:
        return
    named = [*settings.text, *([settings.title] if settings.title else [])]
    for name in named:
        if not any(name in output for _, output in outputs):
            logger.warning(
                "%s: no record of action '%s' holds the field '%s', so it adds no text. "
                "Check the field name",
                label,
                settings.action,
                name,
            )


def corpus_digest(
    settings: CorpusSettings, kinds: Iterable[str], records: Sequence[CorpusRecord]
) -> str:
    parts = {
        "format": [FORMAT_VERSION, CORPUS_FORMAT],
        # The action is each match's origin, so a renamed `from:` builds a new index.
        "settings": [settings.action, list(settings.text), settings.title, settings.id],
        "indexes": {kind: INDEX_SETTINGS[kind] for kind in sorted(set(kinds))},
        "records": sorted((r.source_guid, r.hash) for r in records),
    }
    text = json.dumps(parts, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _records_table(records: Sequence[CorpusRecord]):
    def write(conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE records (source_guid TEXT PRIMARY KEY, hash TEXT)")
        conn.executemany(
            "INSERT INTO records (source_guid, hash) VALUES (?, ?)",
            ((r.source_guid, r.hash) for r in records),
        )

    return write


def stored_records(path: Path) -> dict[str, str] | None:
    """Each record's ``source_guid`` and hash in the index file *path*; None when unreadable."""
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        rows = conn.execute("SELECT source_guid, hash FROM records").fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return {guid: digest for guid, digest in rows}


def corpus_change(
    folder: Path,
    current: Mapping[str, str],
    answers: Sequence[tuple[str, str]],
    digest: str,
    *,
    new_index: bool = False,
) -> CorpusChange:
    """Compare the corpus with the index each stored answer ``(source_guid, index)`` searched.

    Each older index is compared on its own, so a record counts once however many of the
    older indexes lack it.
    """
    # A record that reaches the step need not be in the corpus (a join, a guard skip).
    stale = [index for _, index in answers if index != digest]
    change = CorpusChange(records=len(current), new_index=new_index, stale_answers=len(stale))
    added: set[str] = set()
    changed: set[str] = set()
    removed: set[str] = set()
    unknown: set[str] = set()
    for index in sorted(set(stale)):
        stored = stored_records(folder / f"{index}.db")
        if stored is None:
            unknown.add(index)
            continue
        added.update(g for g in current if g not in stored)
        changed.update(g for g, h in stored.items() if g in current and current[g] != h)
        removed.update(g for g in stored if g not in current)
    change.added = len(added)
    change.changed = len(changed)
    change.removed = len(removed)
    change.unknown_answers = sum(1 for index in stale if index in unknown)
    return change


def prune(folder: Path, keep: set[str]) -> list[Path]:
    """Remove the index files of *folder* whose digest *keep* does not name, and partial builds."""
    removed: list[Path] = []
    if not folder.is_dir():
        return removed
    for path in sorted(folder.iterdir()):
        ours = (path.suffix == ".db" and path.stem not in keep) or path.name.endswith(".tmp")
        if path.is_file() and ours:
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed


def build_corpus_index(
    folder: Path,
    settings: CorpusSettings,
    kinds: Iterable[str],
    records: Sequence[CorpusRecord],
    label: str,
) -> CorpusIndex:
    """The index of *records*, written to ``<folder>/<digest>.db`` unless it exists."""
    kinds = frozenset(kinds)
    digest = corpus_digest(settings, kinds, records)
    path = folder / f"{digest}.db"
    built = not path.exists()
    if built:
        folder.mkdir(parents=True, exist_ok=True)
        write_index_file(path, [r.chunk for r in records], kinds, _records_table(records))
        logger.info("%s: built the index %s of %d records", label, digest, len(records))
    _warn_of_size(records, label)
    return CorpusIndex(
        digest=digest,
        path=path,
        kinds=kinds,
        chunk_ids={r.source_guid: r.chunk.id for r in records},
        records={r.source_guid: r.hash for r in records},
        built=built,
    )


def _warn_of_size(records: Sequence[CorpusRecord], label: str) -> None:
    from agent_actions.input.preprocessing.transformation.markdown_splitter import count_tokens

    if len(records) > MANY_RECORDS:
        logger.warning(
            "%s: the corpus holds %s records, more than %s. Each record searches all of them, "
            "so the time grows with the square of the corpus: about 14 ms a search at 10,000 "
            "records and 140 ms at 100,000",
            label,
            f"{len(records):,}",
            f"{MANY_RECORDS:,}",
        )
    # A token is at least one character, so a shorter text cannot pass the limit.
    sizes = [count_tokens(r.chunk.text) for r in records if len(r.chunk.text) > OVERSIZED_TOKENS]
    oversized = [size for size in sizes if size > OVERSIZED_TOKENS]
    if oversized:
        logger.warning(
            "%s: %d records hold more than %d tokens of text (the largest %d). A long record "
            "matches many queries; search a shorter field, such as a summary",
            label,
            len(oversized),
            OVERSIZED_TOKENS,
            max(oversized),
        )
