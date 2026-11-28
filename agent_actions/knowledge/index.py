"""Content-addressed index files of the knowledge bases, under ``.agac/knowledge/``.

``<base>/<kind>-<digest>.db`` holds the chunks and the index of one kind. The digest
covers the index format, the kind's settings, the base's settings and the bytes of each
source, so a file never changes once written: a build writes a temporary file and renames
it into place under a project lock, and a reader takes no lock. An entry that reads more
than one kind is named by one digest of their digests, which ``<base>/set-<digest>.json``
maps back to the files.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import portalocker

from agent_actions.errors import ConfigurationError
from agent_actions.knowledge.chunks import Scan, chunk, knowledge_dir
from agent_actions.knowledge.methods import INDEX_BUILDERS, INDEX_SETTINGS, build_chunks_table

logger = logging.getLogger(__name__)

FORMAT_VERSION = 1
LOCK_FILE = ".lock"


def index_digest(content_digest: str, kind: str) -> str:
    key = f"{FORMAT_VERSION}\n{kind}\n{INDEX_SETTINGS[kind]}\n{content_digest}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def index_path(project_root: Path, name: str, kind: str, digest: str) -> Path:
    return knowledge_dir(project_root) / name / f"{kind}-{digest}.db"


def set_path(project_root: Path, name: str, digest: str) -> Path:
    return knowledge_dir(project_root) / name / f"set-{digest}.json"


def kind_digests(found: Scan, kinds: Iterable[str]) -> dict[str, str]:
    content = found.content_digest
    return {kind: index_digest(content, kind) for kind in sorted(set(kinds))}


def combined_digest(digests: dict[str, str]) -> str:
    """One kind's own digest, or a digest of several kinds' digests."""
    if len(digests) == 1:
        return next(iter(digests.values()))
    key = "\n".join(f"{kind}:{digests[kind]}" for kind in sorted(digests))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


@contextmanager
def project_lock(project_root: Path) -> Iterator[None]:
    """Hold the project's knowledge lock; waits for another build to finish."""
    folder = knowledge_dir(project_root)
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / LOCK_FILE, "a+", encoding="utf-8") as handle:
        portalocker.lock(handle, portalocker.LOCK_EX)
        try:
            yield
        finally:
            portalocker.unlock(handle)


def _partial(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp")


def _write_index(path: Path, chunks: list, kind: str) -> None:
    partial = _partial(path)
    conn = sqlite3.connect(partial)
    try:
        build_chunks_table(conn, chunks)
        INDEX_BUILDERS[kind](conn)
        conn.commit()
    except BaseException:
        conn.close()
        partial.unlink(missing_ok=True)
        raise
    conn.close()
    os.replace(partial, path)


def build_indexes(project_root: Path, found: Scan, kinds: Iterable[str]) -> tuple[str, list[str]]:
    """The digest of *kinds* for *found*, building what is missing; and the kinds built."""
    digests = kind_digests(found, kinds)
    digest = combined_digest(digests)
    paths = {kind: index_path(project_root, found.name, kind, d) for kind, d in digests.items()}
    listed = set_path(project_root, found.name, digest)
    complete = len(digests) == 1 or listed.exists()
    if complete and all(path.exists() for path in paths.values()):
        return digest, []
    built: list[str] = []
    with project_lock(project_root):
        missing = [kind for kind, path in paths.items() if not path.exists()]
        chunks = chunk(found) if missing else []
        for kind in missing:
            paths[kind].parent.mkdir(parents=True, exist_ok=True)
            _write_index(paths[kind], chunks, kind)
            built.append(kind)
        if len(digests) > 1 and not listed.exists():
            partial = _partial(listed)
            partial.write_text(json.dumps(digests, sort_keys=True), encoding="utf-8")
            os.replace(partial, listed)
    if built:
        logger.info(
            "knowledge base '%s': built the %s index %s (%d chunks)",
            found.name,
            ", ".join(built),
            digest,
            len(chunks),
        )
    return digest, built


_located: dict[tuple[str, str, str], dict[str, Path]] = {}
_located_lock = threading.Lock()


def locate(project_root: Path, name: str, digest: str, kinds: Iterable[str]) -> dict[str, Path]:
    """The index file of each of *kinds* that *digest* names; refuses one not built."""
    wanted = sorted(set(kinds))
    key = (str(project_root.resolve()), name, digest)
    with _located_lock:
        known = _located.get(key)
    if known is None:
        if len(wanted) == 1:
            known = {wanted[0]: index_path(project_root, name, wanted[0], digest)}
        else:
            listed = set_path(project_root, name, digest)
            try:
                digests = json.loads(listed.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                digests = {}
            known = {k: index_path(project_root, name, k, d) for k, d in digests.items()}
        # A set file not written yet is read again next time: a build may write it.
        if known:
            with _located_lock:
                _located[key] = known
    paths = {kind: known.get(kind) for kind in wanted}
    if not all(path is not None and path.exists() for path in paths.values()):
        raise ConfigurationError(
            f"knowledge base '{name}': no index {digest} of {', '.join(wanted)} is built. "
            f"Run 'agac knowledge build {name}'",
            context={"knowledge_base": name, "index": digest},
        )
    return {kind: path for kind, path in paths.items() if path is not None}


_local = threading.local()


def connection(path: Path) -> sqlite3.Connection:
    """A read-only connection to *path* for the calling thread."""
    opened: dict[Path, sqlite3.Connection] = getattr(_local, "connections", None) or {}
    _local.connections = opened
    path = path if path.is_absolute() else path.resolve()
    conn = opened.get(path)
    if conn is None:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        opened[path] = conn
    return conn


def prune(project_root: Path, keep: dict[str, set[Path]]) -> list[Path]:
    """Remove the files of each base that *keep* does not name, and partial builds."""
    removed: list[Path] = []
    with project_lock(project_root):
        for name, kept in keep.items():
            folder = knowledge_dir(project_root) / name
            if not folder.is_dir():
                continue
            for path in sorted(folder.iterdir()):
                ours = path.suffix in (".db", ".json") or path.name.endswith(".tmp")
                if path.is_file() and ours and path not in kept:
                    path.unlink(missing_ok=True)
                    removed.append(path)
    with _located_lock:
        _located.clear()
    return removed
