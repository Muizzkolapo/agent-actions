"""`agac retry` prints the plan when a failure reason holds a closing tag.

The retry plan lists the failed records with the reason stored for each, which is the
error text and can quote record content or a provider reply. A Rich table cell parses
markup, so a reason holding a closing tag that matched no open one raised `MarkupError`
before any repair started, on the command a failed run's output points the user at.
"""

from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_dispositions_prints_a_reason_that_holds_brackets import (
    WORKFLOW,
    project,  # noqa: F401
)


def test_a_dry_run_prints_the_plan_with_the_reason(project):  # noqa: F811
    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "[/note]" in result.output


def test_the_plan_still_counts_the_records_it_will_retry(project):  # noqa: F811
    """Control: the table is the only part that held the reason."""
    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--dry-run"])

    assert "Records to retry: 1" in result.output
