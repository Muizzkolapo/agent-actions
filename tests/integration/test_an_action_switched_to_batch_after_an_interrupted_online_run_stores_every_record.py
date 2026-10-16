"""An action switched to batch after an online run stopped partway keeps its finished records.

The records the online run finished exist only as checkpoint rows. Submission treats such
a record as carried and does not send it, so finalize has to write it; before, finalize
read only the stored file and the record was left with a `success` disposition and no row.
"""

import pytest

from tests.integration.test_a_stopped_action_keeps_only_what_its_config_still_answers import (
    ACTION,
    EVERY_PAGE,
    _config,
    _run,
    _stored_rows,
    online,  # noqa: F401
    project,  # noqa: F401
    provider,  # noqa: F401
)


@pytest.fixture
def switched(online, provider):  # noqa: F811
    """Four pages, the online run stopped at its second call, the action now in batch."""
    provider.stops(at_call=2, raising=KeyboardInterrupt())
    _run("--fresh")
    config = _config(online)
    config.write_text(config.read_text().replace("run_mode: online", "run_mode: batch"))
    provider.answers()
    return online


def _submit_and_collect():
    first, second = _run(), _run()
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    return second


def test_every_record_is_stored_once(switched):
    _submit_and_collect()

    guids = [row["source_guid"] for row in _stored_rows(switched, ACTION)]

    assert len(guids) == len(EVERY_PAGE)
    assert len(set(guids)) == len(EVERY_PAGE)


def test_the_next_run_has_nothing_to_ask(switched, provider):  # noqa: F811
    _submit_and_collect()
    stored = len(_stored_rows(switched, ACTION))

    result = _run()

    assert result.exit_code == 0, result.output
    assert provider.asked == []
    assert len(_stored_rows(switched, ACTION)) == stored
