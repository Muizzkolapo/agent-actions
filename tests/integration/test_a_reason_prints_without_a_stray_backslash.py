"""A failure reason holding a closing tag prints as written, with nothing added.

Printing it at all was the first fix. Escaping it for the table instead of printing it
as text satisfies "the tag appears" while putting a backslash in front of it.
"""

from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_dispositions_prints_a_reason_that_holds_brackets import (
    WORKFLOW,
    project,  # noqa: F401
)

REASON = "Error executing UDF 'flat_brackets': [/note] gamma breaks"


def test_the_quarantined_table_prints_the_reason_exactly(project):  # noqa: F811
    result = CliRunner().invoke(cli, ["dispositions", "-a", WORKFLOW, "--quarantined"])

    assert REASON in result.output


def test_the_retry_plan_prints_the_reason_exactly(project):  # noqa: F811
    result = CliRunner().invoke(cli, ["retry", "-a", WORKFLOW, "--dry-run"])

    assert REASON in result.output
