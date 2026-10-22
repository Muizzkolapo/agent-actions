import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend

ACTION = "summarize"


def _prompt(n: int) -> str:
    return (
        "You are a careful editor. Summarise the page below in one sentence.\n"
        "Keep names exact and never invent facts.\n"
        * 20
        + f"Page {n}: the quick brown fox jumps over the lazy dog {n} times."
    )


def _context(n: int) -> str:
    body = "lorem ipsum " * 200
    return f'{{"page": {{"title": "Page {n}", "body": "{body}"}}}}'


@pytest.fixture
def backend(tmp_path):
    b = SQLiteBackend(str(tmp_path / "wf.db"), workflow_name="wf")
    b.initialize()
    yield b
    b.close()


def _stored(backend, column: str) -> list[tuple[str, int]]:
    rows = backend.connection.execute(
        f"SELECT typeof({column}), length({column}) FROM prompt_trace ORDER BY id"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


class TestTraceTextIsStoredCompressed:
    def test_the_prompt_and_context_are_stored_smaller_than_written(self, backend):
        for n in range(5):
            backend.write_prompt_trace(ACTION, f"tid-{n}", _prompt(n), llm_context=_context(n))

        for column, text in (("compiled_prompt", _prompt(4)), ("llm_context", _context(4))):
            kinds, sizes = zip(*_stored(backend, column), strict=True)
            assert set(kinds) == {"blob"}
            assert sizes[-1] * 4 < len(text.encode())

    def test_every_reader_returns_the_text_that_was_written(self, backend):
        for n in range(3):
            backend.write_prompt_trace(ACTION, f"tid-{n}", _prompt(n), llm_context=_context(n))
            backend.update_prompt_trace_response(ACTION, f"tid-{n}", f"Summary {n}.")
        backend.write_target(
            ACTION, "out.json", [{"source_guid": "g2", "target_id": "tid-2"}], force_full=True
        )

        traces = backend.get_prompt_traces(ACTION)
        assert [t["compiled_prompt"] for t in traces] == [_prompt(n) for n in range(3)]
        assert [t["llm_context"] for t in traces] == [_context(n) for n in range(3)]
        assert [t["response_text"] for t in traces] == [f"Summary {n}." for n in range(3)]

        page = backend.preview_prompt_traces(ACTION, limit=1, offset=1)["records"]
        assert page[0]["compiled_prompt"] == _prompt(1)
        assert page[0]["response_text"] == "Summary 1."

        assert backend.get_prompt_trace_summary(ACTION)["compiled_prompt"] in {
            _prompt(n) for n in range(3)
        }

        trace = backend.scan_data()["nodes"][ACTION]["preview"][0]["_trace"]
        assert trace["compiled_prompt"] == _prompt(2)
        assert trace["llm_context"] == _context(2)
        assert trace["response_text"] == "Summary 2."

    def test_a_missing_context_and_response_stay_null(self, backend):
        backend.write_prompt_trace(ACTION, "tid-0", _prompt(0))

        trace = backend.get_prompt_traces(ACTION)[0]
        assert trace["llm_context"] is None
        assert trace["response_text"] is None
        assert _stored(backend, "llm_context") == [("null", None)]


class TestStoresWrittenBeforeCompression:
    def test_a_plain_text_row_still_reads_back(self, backend):
        backend.connection.execute(
            "INSERT INTO prompt_trace (action_name, record_id, attempt, compiled_prompt,"
            " llm_context, response_text) VALUES (?, 'tid-old', 0, 'old prompt', 'old ctx', 'old')",
            (ACTION,),
        )
        backend.connection.commit()
        backend.write_prompt_trace(ACTION, "tid-new", _prompt(1), llm_context=_context(1))

        traces = {t["record_id"]: t for t in backend.get_prompt_traces(ACTION)}
        assert traces["tid-old"]["compiled_prompt"] == "old prompt"
        assert traces["tid-old"]["response_text"] == "old"
        assert traces["tid-new"]["compiled_prompt"] == _prompt(1)


class TestCompressedTracesAcrossInstancesAndClears:
    def test_a_read_only_instance_reads_compressed_traces(self, backend, tmp_path):
        backend.write_prompt_trace(ACTION, "tid-0", _prompt(0), llm_context=_context(0))
        backend.update_prompt_trace_response(ACTION, "tid-0", "Summary 0.")
        backend.close()

        reader = SQLiteBackend.create_readonly(tmp_path / "wf.db")
        try:
            trace = reader.get_prompt_traces(ACTION)[0]
        finally:
            reader.close()
        assert trace["compiled_prompt"] == _prompt(0)
        assert trace["llm_context"] == _context(0)
        assert trace["response_text"] == "Summary 0."

    def test_traces_written_after_a_clear_read_back(self, backend):
        backend.write_prompt_trace(ACTION, "tid-0", _prompt(0), llm_context=_context(0))
        backend.clear_prompt_traces(ACTION)

        backend.write_prompt_trace(ACTION, "tid-1", "a different prompt entirely")
        backend.write_prompt_trace(ACTION, "tid-2", _prompt(2), llm_context=_context(2))

        traces = backend.get_prompt_traces(ACTION)
        assert [t["compiled_prompt"] for t in traces] == ["a different prompt entirely", _prompt(2)]
        assert traces[1]["llm_context"] == _context(2)

    def test_a_second_writer_on_the_same_store_reads_the_firsts_traces(self, backend, tmp_path):
        backend.write_prompt_trace(ACTION, "tid-0", _prompt(0), llm_context=_context(0))
        other = SQLiteBackend(str(tmp_path / "wf.db"), workflow_name="wf")
        other.initialize()
        try:
            other.write_prompt_trace(ACTION, "tid-1", _prompt(1), llm_context=_context(1))
            from_other = [t["compiled_prompt"] for t in other.get_prompt_traces(ACTION)]
        finally:
            other.close()

        assert from_other == [_prompt(0), _prompt(1)]
        assert [t["llm_context"] for t in backend.get_prompt_traces(ACTION)] == [
            _context(0),
            _context(1),
        ]

    def test_clearing_every_action_leaves_no_dictionary_behind(self, backend):
        backend.write_prompt_trace(ACTION, "tid-0", _prompt(0), llm_context=_context(0))
        backend.write_prompt_trace("classify", "tid-0", _prompt(1))
        count = "SELECT COUNT(*) FROM prompt_trace_dictionary"
        assert backend.connection.execute(count).fetchone()[0] == 3

        backend.clear_prompt_traces()

        assert backend.connection.execute(count).fetchone()[0] == 0


def test_a_corrupt_compressed_value_is_an_error_not_garbage(backend):
    backend.write_prompt_trace(ACTION, "tid-0", _prompt(0))
    backend.connection.execute(
        "UPDATE prompt_trace SET compiled_prompt = ? WHERE record_id = 'tid-0'",
        (b"\x00\x00\x00\x01not zlib",),
    )
    backend.connection.commit()

    with pytest.raises(ValueError, match="compressed trace"):
        backend.get_prompt_traces(ACTION)
