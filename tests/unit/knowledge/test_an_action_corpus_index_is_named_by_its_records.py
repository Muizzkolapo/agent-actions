"""An action corpus index is named by its records, and tells what changed since an answer."""

from __future__ import annotations

import logging

from agent_actions.knowledge.action_corpus import (
    CorpusSettings,
    build_corpus_index,
    corpus_change,
    corpus_digest,
    corpus_records,
    stored_records,
)
from agent_actions.knowledge.api import action_corpus_change, index_action_corpus

LABEL = "link: retrieve 'similar' (link__similar)"
SETTINGS = CorpusSettings("summarize", ("summary",), title="product", id="ticket_id")
CORPUS = {"action": "summarize", "text": ["summary"], "title": "product", "id": "ticket_id"}


def _outputs(**summaries):
    return [
        (f"g-{t}", {"ticket_id": t, "summary": s, "product": "app"}) for t, s in summaries.items()
    ]


def _digest(outputs, settings=SETTINGS, kinds=("keyword",)):
    return corpus_digest(settings, kinds, corpus_records(outputs, settings, LABEL))


def _rows(**summaries):
    return [
        {"source_guid": guid, "_state": "processed", "content": {"summarize": output}}
        for guid, output in _outputs(**summaries)
    ]


class TestTheDigest:
    def test_the_same_records_in_another_order_give_the_same_digest(self):
        outputs = _outputs(a="one", b="two")

        assert _digest(outputs) == _digest(list(reversed(outputs)))

    def test_a_changed_record_changes_the_digest(self):
        assert _digest(_outputs(a="one", b="two")) != _digest(_outputs(a="one", b="three"))

    def test_a_changed_field_outside_the_text_changes_the_digest(self):
        changed = _outputs(a="one")
        changed[0][1]["product"] = "billing"

        assert _digest(_outputs(a="one")) != _digest(changed)

    def test_an_added_record_changes_the_digest(self):
        assert _digest(_outputs(a="one")) != _digest(_outputs(a="one", b="two"))

    def test_the_text_title_and_id_settings_and_the_index_kinds_change_the_digest(self):
        outputs = _outputs(a="one")
        digests = {
            _digest(outputs),
            _digest(outputs, CorpusSettings("summarize", ("summary",), id="ticket_id")),
            _digest(outputs, CorpusSettings("summarize", ("summary",), title="product")),
            _digest(outputs, CorpusSettings("summarize", ("summary", "product"))),
            _digest(outputs, kinds=("keyword", "fuzzy")),
        }

        assert len(digests) == 5

    def test_another_from_action_with_the_same_output_changes_the_digest(self):
        outputs = _outputs(a="one")
        renamed = CorpusSettings("condense", ("summary",), title="product", id="ticket_id")

        assert _digest(outputs) != _digest(outputs, renamed)


class TestTheIndexFile:
    def test_the_file_is_named_by_the_digest_and_holds_each_record_and_its_hash(self, tmp_path):
        records = corpus_records(_outputs(a="one", b="two"), SETTINGS, LABEL)

        index = build_corpus_index(tmp_path, SETTINGS, {"keyword"}, records, LABEL)

        assert index.path == tmp_path / f"{index.digest}.db"
        assert stored_records(index.path) == {r.source_guid: r.hash for r in records}

    def test_an_index_already_built_is_not_written_again(self, tmp_path, caplog):
        records = corpus_records(_outputs(a="one"), SETTINGS, LABEL)
        first = build_corpus_index(tmp_path, SETTINGS, {"keyword"}, records, LABEL)
        written = first.path.stat().st_mtime_ns

        with caplog.at_level(logging.INFO):
            again = build_corpus_index(tmp_path, SETTINGS, {"keyword"}, records, LABEL)

        assert again.path.stat().st_mtime_ns == written
        assert "built the index" not in caplog.text


class TestWhatChangedSinceAnAnswer:
    def _first(self, tmp_path, **summaries):
        index, change = prepare(tmp_path, CORPUS, ["keyword"], _rows(**summaries), [], label=LABEL)
        assert change.message("link__similar", LABEL) is None
        return index

    def test_records_only_added_give_one_info_line(self, tmp_path):
        first = self._first(tmp_path, a="one", b="two")
        answers = [("g-a", first.digest), ("g-b", first.digest)]

        index, change = prepare(
            tmp_path, CORPUS, ["keyword"], _rows(a="one", b="two", c="three"), answers, label=LABEL
        )

        level, line = change.message("link__similar", LABEL)
        assert level == logging.INFO
        assert line == (
            f"{LABEL}: 1 record was added since 2 earlier answers searched; "
            "--rerun link__similar to search again"
        )
        assert index.digest != first.digest

    def test_a_changed_record_gives_a_warning(self, tmp_path):
        first = self._first(tmp_path, a="one", b="two")
        answers = [("g-a", first.digest), ("g-b", first.digest)]

        _, change = prepare(
            tmp_path, CORPUS, ["keyword"], _rows(a="one", b="other"), answers, label=LABEL
        )

        level, line = change.message("link__similar", LABEL)
        assert level == logging.WARNING
        assert (
            "since 2 earlier answers searched the records, 1 changed, 0 left and 0 were " in line
        )
        assert "--rerun link__similar" in line

    def test_a_removed_record_gives_a_warning(self, tmp_path):
        first = self._first(tmp_path, a="one", b="two")
        answers = [("g-a", first.digest), ("g-b", first.digest)]

        _, change = prepare(tmp_path, CORPUS, ["keyword"], _rows(a="one"), answers, label=LABEL)

        level, line = change.message("link__similar", LABEL)
        assert level == logging.WARNING
        assert "since 1 earlier answer searched the records, 0 changed, 1 left and 0 were " in line

    def test_a_later_run_with_no_new_record_gives_no_info_line(self, tmp_path):
        first = self._first(tmp_path, a="one", b="two")
        answers = [("g-a", first.digest), ("g-b", first.digest)]
        rows = _rows(a="one", b="two", c="three")
        prepare(tmp_path, CORPUS, ["keyword"], rows, answers, label=LABEL)

        _, change = prepare(tmp_path, CORPUS, ["keyword"], rows, answers, label=LABEL)

        assert change.added == 1
        assert change.message("link__similar", LABEL) is None

    def test_a_record_counts_once_against_each_older_index_that_lacks_it(self, tmp_path):
        first = self._first(tmp_path, a="one", b="two")
        older = [("g-a", first.digest), ("g-b", first.digest)]
        rows = _rows(a="one", b="two", c="three")
        second, _ = prepare(tmp_path, CORPUS, ["keyword"], rows, older, label=LABEL)
        answers = [*older, ("g-c", second.digest)]

        _, change = prepare(
            tmp_path,
            CORPUS,
            ["keyword"],
            _rows(a="one", b="two", c="three", d="four"),
            answers,
            label=LABEL,
        )

        assert (change.added, change.stale_answers) == (2, 3)
        level, line = change.message("link__similar", LABEL)
        assert level == logging.INFO
        assert line.startswith(f"{LABEL}: 2 records were added since 3 earlier answers searched")

    def test_answers_whose_index_is_gone_give_a_warning(self, tmp_path):
        first = self._first(tmp_path, a="one", b="two")
        answers = [("g-a", first.digest), ("g-b", first.digest)]
        first.path.unlink()

        _, change = prepare(
            tmp_path, CORPUS, ["keyword"], _rows(a="one", b="two", c="three"), answers, label=LABEL
        )

        level, line = change.message("link__similar", LABEL)
        assert level == logging.WARNING
        assert line == (
            f"{LABEL}: 2 earlier answers searched an index that is gone, so the changes since "
            "are not known. Run again with --rerun link__similar to search again"
        )

    def test_answers_that_searched_the_current_index_give_nothing(self, tmp_path):
        first = self._first(tmp_path, a="one", b="two")
        answers = [("g-a", first.digest), ("g-b", first.digest)]

        _, change = prepare(
            tmp_path, CORPUS, ["keyword"], _rows(a="one", b="two"), answers, label=LABEL
        )

        assert change.message("link__similar", LABEL) is None

    def test_the_comparison_reads_the_index_each_answer_names(self, tmp_path):
        current = {"g-a": "h1", "g-c": "h3"}
        records = corpus_records(_outputs(a="one", b="two"), SETTINGS, LABEL)
        old = build_corpus_index(tmp_path, SETTINGS, {"keyword"}, records, LABEL)

        change = corpus_change(tmp_path, current, [("g-a", old.digest)], "new")

        assert (change.added, change.changed, change.removed) == (1, 1, 1)
        assert change.stale_answers == 1


class TestTheOldFiles:
    def test_index_files_no_answer_names_are_removed_at_build_time(self, tmp_path):
        first = self._index(tmp_path, a="one")
        second = self._index(tmp_path, a="one", b="two")
        (tmp_path / ".abc.db.1-2.tmp").write_text("")

        third, _ = prepare(
            tmp_path,
            CORPUS,
            ["keyword"],
            _rows(a="one", b="two", c="three"),
            [("g-a", second.digest)],
            label=LABEL,
        )

        assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
            [f"{second.digest}.db", f"{third.digest}.db"]
        )
        assert not first.path.exists()

    @staticmethod
    def _index(tmp_path, **summaries):
        index, _ = prepare(tmp_path, CORPUS, ["keyword"], _rows(**summaries), [], label=LABEL)
        return index


def prepare(folder, corpus, methods, rows, answers, *, label):
    """Index the records, then compare with *answers*, as a run of the step does."""
    index = index_action_corpus(folder, corpus, methods, rows, label=label)
    return index, action_corpus_change(folder, index, answers)
