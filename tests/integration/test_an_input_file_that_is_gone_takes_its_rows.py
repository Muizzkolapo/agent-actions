"""An action re-run after one of its input files was removed holds nothing for it (1258).

A reset clears what called an action's rows done and relies on the re-run to
write each file again. A file whose input is gone is never written again, so its
rows stood beside the files that were, the action read completed, and its readers
ran on them. A walk that finds no file at all is #1240's; this one finds some.
Editing the action is what resets it; its readers are reset by that.
"""

import json

from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    SECOND,
    WORKFLOW,
    _backend,
    chained,  # noqa: F401
    project,  # noqa: F401
)
from tests.integration.test_skipped_reader_drops_stale_rows import (
    MODES,
    RESET_ONLY,
    _add_guard_to,
    _run,
    _status,
)

PAGES = 6
MORE = 3


def _staging(root):
    return root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"


def _stage(root, name, records):
    path = _staging(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"page_content": f"{name} {i}"} for i in range(records)]))


def _stored(root, action):
    """Rows held per stored file."""
    backend = _backend(root)
    try:
        return {
            path: len(backend._read_target_raw(action, path))
            for path in backend.list_target_files(action)
        }
    finally:
        backend.close()


def _two_files(root):
    _stage(root, "more.json", MORE)
    _run("--fresh")
    assert _stored(root, SECOND) == {"more.json": MORE, "pages.json": PAGES}


@MODES
def test_neither_the_action_nor_its_reader_keeps_the_rows_of_a_file_that_is_gone(
    chained,  # noqa: F811
    mode,
):
    _two_files(chained)
    (_staging(chained) / "more.json").unlink()
    _add_guard_to(chained, ACTION, RESET_ONLY)

    _run("-e", mode)

    assert _stored(chained, ACTION) == {"pages.json": PAGES}
    assert _stored(chained, SECOND) == {"pages.json": PAGES}
    assert _status(chained, ACTION) == "completed"
    assert _status(chained, SECOND) == "completed"


def test_a_file_in_a_subdirectory_is_matched_by_its_path(chained):  # noqa: F811
    """The one beside it stays: a basename would match neither, or both."""
    _stage(chained, "sub/kept.json", 2)
    _stage(chained, "sub/more.json", MORE)
    _run("--fresh")
    (_staging(chained) / "sub" / "more.json").unlink()
    _add_guard_to(chained, ACTION, RESET_ONLY)

    _run()

    assert _stored(chained, ACTION) == {"pages.json": PAGES, "sub/kept.json": 2}
    assert _stored(chained, SECOND) == {"pages.json": PAGES, "sub/kept.json": 2}


def test_a_file_limit_the_walk_never_reaches_deletes_them_too(chained):  # noqa: F811
    """Every file left was opened, so none is kept for being unopened."""
    _two_files(chained)
    (_staging(chained) / "more.json").unlink()

    # A new limit is itself what resets the action.
    _run("--file-limit", "5")

    assert _stored(chained, ACTION) == {"pages.json": PAGES}
    assert _stored(chained, SECOND) == {"pages.json": PAGES}


def test_the_input_coming_back_is_answered_on_the_next_reset(chained):  # noqa: F811
    """A completed action does not look for new input; once reset, nothing left by the
    deletion keeps it from answering the file again."""
    _two_files(chained)
    (_staging(chained) / "more.json").unlink()
    _add_guard_to(chained, ACTION, RESET_ONLY)
    _run()

    _stage(chained, "more.json", MORE)
    _run("--file-limit", "5")

    assert _stored(chained, ACTION) == {"more.json": MORE, "pages.json": PAGES}
    assert _stored(chained, SECOND) == {"more.json": MORE, "pages.json": PAGES}
