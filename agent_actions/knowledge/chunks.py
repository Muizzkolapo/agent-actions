"""Read a knowledge base's sources and cut them into chunks.

A scan reads each source's bytes once and hashes them; the chunks are cut from those same
bytes, so the index digest names exactly what was indexed.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigurationError
from agent_actions.knowledge.config import (
    MAX_FILE_BYTES,
    RECORD_TYPES,
    DatabaseSource,
    KnowledgeBase,
    StructuredSource,
)

logger = logging.getLogger(__name__)

# Changes when a chunk of the same bytes would come out different.
CHUNKER_VERSION = 1
KNOWLEDGE_DIR = Path(".agac") / "knowledge"


@dataclass(frozen=True)
class Chunk:
    id: str
    title: str
    text: str
    body: str
    origin: str
    metadata: dict[str, Any]

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ScannedFile:
    relpath: str
    data: bytes
    source: str | StructuredSource
    digest: str


@dataclass(frozen=True)
class ScannedRows:
    source: DatabaseSource
    rows: list[dict[str, Any]]
    digest: str


@dataclass
class Scan:
    name: str
    base: KnowledgeBase
    files: list[ScannedFile] = field(default_factory=list)
    tables: list[ScannedRows] = field(default_factory=list)

    @property
    def content_digest(self) -> str:
        """The base's settings (not its index kinds) and the bytes of every source."""
        settings = self.base.model_dump(mode="json", exclude={"index", "name"})
        parts = {
            "chunker": CHUNKER_VERSION,
            "settings": settings,
            "files": [[f.relpath, f.digest] for f in self.files],
            "tables": [t.digest for t in self.tables],
        }
        text = json.dumps(parts, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def knowledge_dir(project_root: Path) -> Path:
    return project_root / KNOWLEDGE_DIR


def snapshot_root(project_root: Path, name: str, number: int) -> Path:
    return knowledge_dir(project_root) / name / "snapshots" / f"source-{number}"


def matched_files(project_root: Path, name: str, pattern: str) -> list[Path]:
    """The files *pattern* matches under the project; refuses a pattern that leaves it."""
    where = f"knowledge base '{name}': source '{pattern}'"
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise ConfigurationError(
            f"{where} must be a path inside the project, relative to agent_actions.yml",
            context={"knowledge_base": name, "source": pattern},
        )
    root = project_root.resolve()
    files = sorted(p for p in root.glob(pattern) if p.is_file())
    for path in files:
        if not path.resolve().is_relative_to(root):
            raise ConfigurationError(
                f"{where} matches {path}, which is outside the project",
                context={"knowledge_base": name, "source": pattern},
            )
    if not files:
        raise ConfigurationError(
            f"{where} matches no file",
            context={"knowledge_base": name, "source": pattern},
        )
    return files


def check_sources(project_root: Path, name: str, base: KnowledgeBase) -> None:
    """Refuse a file source that matches no file or leaves the project; reads no file."""
    for source in base.sources:
        pattern = source if isinstance(source, str) else getattr(source, "path", None)
        if pattern is not None:
            matched_files(project_root, name, pattern)


def scan(
    project_root: Path, name: str, base: KnowledgeBase, *, connect: bool = True
) -> Scan:
    """Read every source of *base*.

    A database source reads its snapshot; with no snapshot it reads the query when
    *connect* allows it, and refuses otherwise.
    """
    found = Scan(name=name, base=base)
    root = project_root.resolve()
    for number, source in enumerate(base.sources, 1):
        if isinstance(source, DatabaseSource):
            found.tables.append(_scan_rows(project_root, name, number, source, connect))
            continue
        pattern = source if isinstance(source, str) else source.path
        for path in matched_files(project_root, name, pattern):
            relpath = path.resolve().relative_to(root).as_posix()
            data = _read(path, name, relpath)
            digest = hashlib.sha256(data).hexdigest()
            found.files.append(ScannedFile(relpath, data, source, digest))
    return found


def _read(path: Path, name: str, relpath: str) -> bytes:
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ConfigurationError(
                f"knowledge base '{name}': {relpath} is {size // (1024 * 1024)} MB; a source "
                f"file may hold at most {MAX_FILE_BYTES // (1024 * 1024)} MB. Split it",
                context={"knowledge_base": name, "file": relpath},
            )
        return path.read_bytes()
    except OSError as e:
        raise ConfigurationError(
            f"knowledge base '{name}': cannot read {relpath}: {e.strerror or e}",
            context={"knowledge_base": name, "file": relpath},
        ) from None


def _scan_rows(
    project_root: Path, name: str, number: int, source: DatabaseSource, connect: bool
) -> ScannedRows:
    from agent_actions.connections import connection_settings, open_connection
    from agent_actions.connections.settings import settings_as_resolved
    from agent_actions.input.loaders.database_source import (
        snapshot_fingerprint,
        snapshot_needs_reading,
        snapshot_query,
    )

    settings = settings_as_resolved(connection_settings(source.connection, project_root))
    fingerprint = snapshot_fingerprint(source.connection, source.sql, settings)
    snapshot_dir = snapshot_root(project_root, name, number) / fingerprint / "data"
    if snapshot_needs_reading(snapshot_dir):
        if not connect:
            raise ConfigurationError(
                f"knowledge base '{name}': source {number} reads connection "
                f"'{source.connection}', and no snapshot of it exists. A sandbox run does not "
                f"connect to a database: run 'agac knowledge build {name}' first",
                context={"knowledge_base": name, "connection": source.connection},
            )
        with open_connection(source.connection, project_root, read_only=True) as connector:
            snapshot_query(connector, source.sql, snapshot_dir)
    rows: list[dict[str, Any]] = []
    hasher = hashlib.sha256()
    for part in sorted(snapshot_dir.glob("part-*.json")):
        data = part.read_bytes()
        hasher.update(data)
        rows.extend(json.loads(data.decode("utf-8")))
    return ScannedRows(source=source, rows=rows, digest=hasher.hexdigest())


def chunk(found: Scan) -> list[Chunk]:
    """The chunks of a scan, in source order; refuses a repeated id or a record with no text."""
    split_method, size, overlap, tokenizer = found.base.chunk_settings()
    chunks: list[Chunk] = []
    for file in found.files:
        suffix = Path(file.relpath).suffix.lower()
        if suffix in RECORD_TYPES:
            spec = file.source if isinstance(file.source, StructuredSource) else None
            records = _records(file.data, suffix, found.name, file.relpath)
            chunks.extend(
                _record_chunk(r, spec, file.relpath, n, found.name)
                for n, r in enumerate(records, 1)
            )
            continue
        text = _text(file.data, suffix, found.name, file.relpath)
        for n, (title, body, whole) in enumerate(
            _split(text, split_method, size, overlap, tokenizer), 1
        ):
            chunks.append(Chunk(f"{file.relpath}#{n}", title, whole, body, file.relpath, {}))
    for table in found.tables:
        chunks.extend(
            _record_chunk(row, table.source, table.source.connection, n, found.name)
            for n, row in enumerate(table.rows, 1)
        )
    seen: dict[str, str] = {}
    for item in chunks:
        if item.id in seen:
            raise ConfigurationError(
                f"knowledge base '{found.name}': id '{item.id}' names a record of "
                f"{seen[item.id]} and of {item.origin}. Each id must name one record, so a "
                "citation is not ambiguous",
                context={"knowledge_base": found.name, "id": item.id},
            )
        seen[item.id] = item.origin
    return chunks


def _split(
    text: str, split_method: str, size: int, overlap: int, tokenizer: str | None
) -> list[tuple[str, str, str]]:
    from agent_actions.input.preprocessing.transformation.markdown_splitter import split_markdown
    from agent_actions.input.preprocessing.transformation.string_transformer import Tokenizer

    if split_method == "markdown":
        return [(c.title, c.body, c.text) for c in split_markdown(text, size, overlap)]
    parts = Tokenizer.split_text_content(
        text, size, overlap, tokenizer or "cl100k_base", split_method
    )
    return [("", part, part) for part in parts if part.strip()]


def _text(data: bytes, suffix: str, name: str, relpath: str) -> str:
    try:
        if suffix == ".pdf":
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(data))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        if suffix == ".docx":
            from docx import Document

            document = Document(io.BytesIO(data))
            return "\n\n".join(_docx_paragraph(p) for p in document.paragraphs)
        text = data.decode("utf-8-sig")
        if suffix in (".html", ".htm"):
            return _html_as_markdown(text)
        return text
    except Exception as e:  # noqa: BLE001 - a parser raises its own error types
        raise ConfigurationError(
            f"knowledge base '{name}': cannot read {relpath}: {e}",
            context={"knowledge_base": name, "file": relpath},
        ) from None


def _docx_paragraph(paragraph: Any) -> str:
    style = str(getattr(getattr(paragraph, "style", None), "name", "") or "")
    if style.startswith("Heading ") and style[8:].isdigit():
        return f"{'#' * min(int(style[8:]), 6)} {paragraph.text}"
    return str(paragraph.text)


def _html_as_markdown(text: str) -> str:
    """The text of an HTML page, its headings written as markdown headings."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(text, "html.parser")
    for unwanted in soup(["script", "style"]):
        unwanted.decompose()
    for level in range(1, 7):
        for heading in soup.find_all(f"h{level}"):
            heading.replace_with(f"\n\n{'#' * level} {heading.get_text(' ', strip=True)}\n\n")
    for block in soup.find_all(["p", "li", "div", "br", "tr"]):
        block.insert_after("\n\n")
    return soup.get_text()


def _records(data: bytes, suffix: str, name: str, relpath: str) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8-sig")
        if suffix == ".csv":
            records: list[Any] = list(csv.DictReader(io.StringIO(text, newline="")))
        elif suffix == ".jsonl":
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            loaded = json.loads(text)
            records = loaded if isinstance(loaded, list) else [loaded]
    except (UnicodeDecodeError, ValueError, csv.Error) as e:
        raise ConfigurationError(
            f"knowledge base '{name}': cannot read {relpath}: {e}",
            context={"knowledge_base": name, "file": relpath},
        ) from None
    for number, record in enumerate(records, 1):
        if not isinstance(record, dict):
            raise ConfigurationError(
                f"knowledge base '{name}': record {number} of {relpath} is not an object",
                context={"knowledge_base": name, "file": relpath},
            )
    return records


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(part for part in (_as_text(v) for v in value) if part)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _record_chunk(
    record: dict[str, Any],
    spec: StructuredSource | DatabaseSource | None,
    origin: str,
    number: int,
    name: str,
) -> Chunk:
    where = f"knowledge base '{name}': record {number} of {origin}"
    if spec is None:
        lines = [f"{key}: {_as_text(value)}" for key, value in record.items() if _as_text(value)]
        text = "\n".join(lines)
        if not text:
            raise ConfigurationError(f"{where} has no text", context={"knowledge_base": name})
        return Chunk(f"{origin}#{number}", "", text, text, origin, {})
    body = "\n".join(t for t in (_as_text(record.get(f)) for f in spec.text) if t)
    if not body:
        raise ConfigurationError(
            f"{where} has no text in {', '.join(spec.text)}",
            context={"knowledge_base": name, "origin": origin},
        )
    if spec.id is not None:
        if record.get(spec.id) in (None, ""):
            raise ConfigurationError(
                f"{where} has no value in its id field '{spec.id}'",
                context={"knowledge_base": name, "origin": origin},
            )
        chunk_id = _as_text(record[spec.id])
    else:
        chunk_id = f"{origin}#{number}"
    title = _as_text(record.get(spec.title)) if spec.title else ""
    metadata = {key: record.get(key) for key in spec.metadata or []}
    text = f"{title}\n{body}" if title and spec.title not in spec.text else body
    return Chunk(chunk_id, title, text, body, origin, metadata)
