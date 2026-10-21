import pytest

from agent_actions.storage.backends.sqlite_backend import SQLiteBackend


def _text(word: str) -> str:
    return f"{word} prompt with its own wording, repeated. " * 50


@pytest.fixture
def db(tmp_path):
    return tmp_path / "wf.db"


@pytest.fixture
def backend(db):
    b = SQLiteBackend(str(db), workflow_name="wf")
    b.initialize()
    yield b
    b.close()


def _read_fresh(db, action):
    reader = SQLiteBackend.create_readonly(db)
    try:
        return [t["compiled_prompt"] for t in reader.get_prompt_traces(action)]
    finally:
        reader.close()


def test_a_failed_trace_write_leaves_later_traces_readable_elsewhere(backend, db):
    backend.connection.execute(
        "CREATE TRIGGER refuse_a BEFORE INSERT ON prompt_trace WHEN NEW.action_name = 'a'"
        " BEGIN SELECT RAISE(ABORT, 'refused'); END"
    )
    backend.connection.commit()

    backend.write_prompt_trace("a", "r1", _text("alpha"))
    backend.write_prompt_trace("b", "r1", _text("beta"))

    assert _read_fresh(db, "a") == []
    assert _read_fresh(db, "b") == [_text("beta")]


def test_clearing_one_action_leaves_anothers_traces_readable(backend, db):
    backend.write_prompt_trace("summarize", "r1", _text("summary"))
    backend.write_prompt_trace("classify", "r1", _text("label"))

    backend.clear_prompt_traces("summarize")

    assert _read_fresh(db, "summarize") == []
    assert _read_fresh(db, "classify") == [_text("label")]
