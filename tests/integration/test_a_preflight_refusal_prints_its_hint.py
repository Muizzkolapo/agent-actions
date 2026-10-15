"""`agac run` prints the remedy a pre-flight refusal carries, not a generic one (1295).

The refusal keeps its remedy in `context['hint']`; the error formatter that ended up
rendering it never read it, so the line labelled Fix was the same constant for every
refusal, printed under a specific remedy that said something else. The same frame
printed "Error:" twice before the title.

`late` observes `final`, which is downstream of its only dependency. Every command is a
real `agac run`.
"""

from tests.integration.test_an_action_reads_only_what_is_upstream_of_it import (
    _late,
    _run,
    project,  # noqa: F401
)

HINT = "add each one it names to its dependencies"
GENERIC_FIX = "Check your configuration and try again"


def test_the_fix_line_is_the_refusals_own_hint(project):  # noqa: F811
    _late(project, ["flatten"], ["flatten.summary", "final.summary"])

    result = _run("--fresh")

    assert result.exit_code == 1, result.output
    assert "'final' is not upstream of it" in result.output
    fix = [line.strip() for line in result.output.splitlines() if line.strip().startswith("Fix:")]
    assert len(fix) == 1, result.output
    assert HINT in fix[0], fix
    assert GENERIC_FIX not in result.output


def test_the_title_is_not_prefixed_with_error_twice(project):  # noqa: F811
    _late(project, ["flatten"], ["flatten.summary", "final.summary"])

    result = _run("--fresh")

    assert result.exit_code == 1, result.output
    assert "Error: Error:" not in result.output
