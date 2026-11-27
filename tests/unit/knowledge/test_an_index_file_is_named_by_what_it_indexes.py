"""An index file is named by a digest of what it indexes, and written whole or not at all.

A build writes a temporary file and renames it under a project lock, so concurrent builds
write one file and a killed build leaves none in place. A digest covers only the index
kinds an entry reads, and a search reads the files of the digest it is given, so an edit
made after a run resolved its digest does not change what the run searches.
"""

from __future__ import annotations

import multiprocessing
import sqlite3
import threading
from pathlib import Path

import pytest

from agent_actions.knowledge import index as index_module
from agent_actions.knowledge.api import ensure_indexes, knowledge_hash, retrieve
from agent_actions.knowledge.chunks import scan
from agent_actions.knowledge.config import load_knowledge
from agent_actions.knowledge.index import build_indexes, prune
from tests.unit.knowledge.conftest import make_project

KB = {"help": {"sources": ["kb/*.md"], "index": ["keyword", "fuzzy"]}}
FILES = {
    "kb/billing.md": "# Billing\n\nDuplicate charges drop off.",
    "kb/app.md": "# App\n\nCrash.",
}


@pytest.fixture
def root(tmp_path) -> Path:
    return make_project(tmp_path / "p", FILES, KB)


def _folder(root: Path) -> Path:
    return root / ".agac" / "knowledge" / "help"


def _scan(root: Path):
    return scan(root, "help", load_knowledge(root)["help"])


def test_the_hash_changes_with_a_file_byte_and_not_with_the_index_list(root):
    before = knowledge_hash(root, "help", {"keyword"}, sandbox=False)
    make_project(root, {}, {"help": {**KB["help"], "index": ["keyword"]}})
    assert knowledge_hash(root, "help", {"keyword"}, sandbox=False) == before

    (root / "kb" / "app.md").write_text("# App\n\nCrash!", encoding="utf-8")
    assert knowledge_hash(root, "help", {"keyword"}, sandbox=False) != before


def test_the_hash_is_computed_without_building(root):
    digest = knowledge_hash(root, "help", {"keyword", "fuzzy"}, sandbox=False)

    assert digest is not None
    assert not _folder(root).exists()
    assert ensure_indexes(root, "help", {"keyword", "fuzzy"}, sandbox=False) == digest


def test_a_digest_covers_only_the_kinds_it_reads(root):
    keyword = ensure_indexes(root, "help", {"keyword"}, sandbox=False)
    both = ensure_indexes(root, "help", {"keyword", "fuzzy"}, sandbox=False)

    assert keyword != both
    assert (_folder(root) / f"keyword-{keyword}.db").exists()
    assert (_folder(root) / f"set-{both}.json").exists()


def test_a_file_is_built_once_and_found_again(root):
    found = _scan(root)
    digest, built = build_indexes(root, found, ["keyword"])
    again, built_again = build_indexes(root, found, ["keyword"])

    assert built == ["keyword"] and built_again == []
    assert digest == again
    assert [p.name for p in _folder(root).iterdir()] == [f"keyword-{digest}.db"]


def _build_in_thread(root: Path, digests: list[str]) -> None:
    digests.append(ensure_indexes(root, "help", {"keyword", "fuzzy"}, sandbox=False))


def test_concurrent_builds_in_threads_write_one_set_of_files(root):
    digests: list[str] = []
    threads = [threading.Thread(target=_build_in_thread, args=(root, digests)) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(digests)) == 1 and len(digests) == 8
    assert len(list(_folder(root).iterdir())) == 3


def _build_in_process(root: str) -> None:
    ensure_indexes(Path(root), "help", {"fuzzy"}, sandbox=False)


def test_concurrent_builds_in_processes_write_one_file(root):
    context = multiprocessing.get_context("spawn")
    processes = [context.Process(target=_build_in_process, args=(str(root),)) for _ in range(4)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(60)

    assert all(p.exitcode == 0 for p in processes)
    files = sorted(p.name for p in _folder(root).iterdir())
    assert len(files) == 1 and files[0].startswith("fuzzy-")
    with sqlite3.connect(_folder(root) / files[0]) as conn:
        assert conn.execute("SELECT count(*) FROM chunks").fetchone() == (2,)


def test_a_build_killed_partway_leaves_no_index_in_place(root, monkeypatch):
    def killed(conn, chunks):
        conn.execute("CREATE TABLE chunks (id TEXT)")
        raise KeyboardInterrupt

    monkeypatch.setattr(index_module, "build_chunks_table", killed)
    with pytest.raises(KeyboardInterrupt):
        ensure_indexes(root, "help", {"keyword"}, sandbox=False)
    monkeypatch.undo()

    assert list(_folder(root).iterdir()) == []
    # A partial file a hard kill leaves is never read; the next build writes the index.
    (_folder(root) / ".keyword-x.db.1-abc.tmp").write_bytes(b"partial")
    digest = ensure_indexes(root, "help", {"keyword"}, sandbox=False)
    assert (_folder(root) / f"keyword-{digest}.db").exists()


def test_a_search_reads_the_digest_it_is_given_after_a_file_changes(root):
    digest = ensure_indexes(root, "help", {"keyword"}, sandbox=False)
    (root / "kb" / "app.md").write_text("# App\n\nA duplicate crash.", encoding="utf-8")

    result = retrieve(
        root,
        base="help",
        digest=digest,
        methods={"keyword": 1.0},
        query_text="duplicate",
        where={},
        top_k=5,
        candidates=20,
        max_context_tokens=None,
        max_per_origin=None,
    )

    assert [m["origin"] for m in result["matches"]] == ["kb/billing.md"]
    assert result["index"] == digest
    assert knowledge_hash(root, "help", {"keyword"}, sandbox=False) != digest


def test_prune_removes_the_files_no_current_digest_names(root):
    old = ensure_indexes(root, "help", {"keyword"}, sandbox=False)
    (root / "kb" / "app.md").write_text("changed", encoding="utf-8")
    new = ensure_indexes(root, "help", {"keyword"}, sandbox=False)
    new_path = _folder(root) / f"keyword-{new}.db"

    removed = prune(root, {"help": {new_path}})

    assert [p.name for p in removed] == [f"keyword-{old}.db"]
    assert new_path.exists()
