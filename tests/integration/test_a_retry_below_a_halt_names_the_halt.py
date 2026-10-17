"""A retry starting below a halted action says so, and names the retry that resumes it.

Its starting action was skipped, since a halted action is not re-run and the reader has
nothing to read. The notice read the skip as the record being "not in its input" and
pointed at `agac run --fresh`, which throws away every answer in the workflow (1317).
"""

from tests.integration.test_a_retry_resumes_a_halt_in_full import (
    _halted,
    _retry,
    _status,
    _the_readers_tool,
    _unwrapped,
)
from tests.integration.test_retry_ignores_record_cap import (
    ACTION,
    SECOND,
    _disposition,
    _fail,
    _stored_guids,
    chained,  # noqa: F401
    project,  # noqa: F811, F401
)


def test_the_notice_names_the_halted_action_and_the_retry_from_it(chained):  # noqa: F811
    guids = _stored_guids(chained, ACTION)
    at_first, at_second = guids[0], guids[-1]
    _fail(chained, at_first, ACTION)
    _fail(chained, at_second, SECOND)
    with _the_readers_tool(halts_at=1, udf="flatten_pages"):
        halted = _retry("--from", ACTION, "--record", at_first)
    assert halted.exit_code != 0, halted.output
    assert _halted(chained, ACTION) and _status(chained, SECOND) == "skipped"

    result = _retry("--from", SECOND, "--record", at_second)

    said = _unwrapped(result.output)
    assert result.exit_code != 0
    assert _disposition(chained, at_second, SECOND) == "failed"
    assert f"'{ACTION}' is halted" in said and f"--from {ACTION}" in said, said
    assert "cleared only by starting over" not in said, said
