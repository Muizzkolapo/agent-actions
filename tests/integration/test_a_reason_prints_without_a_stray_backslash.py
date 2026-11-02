"""A failure reason holding a closing tag prints as written, with nothing added.

Printing it at all was the first fix. Escaping it for the table instead of printing it
as text satisfies "the tag appears" while putting a backslash in front of it.
"""

import pytest
from click.testing import CliRunner

from agent_actions.cli.main import cli
from tests.integration.test_dispositions_prints_a_reason_that_holds_brackets import (
    WORKFLOW,
    project,  # noqa: F401
)

# Up to the tag: the table shortens a long reason, and the tag is what this is about.
REASON = "Error executing UDF 'flat_brackets': RuntimeError: [/note]"


@pytest.mark.parametrize(
    "args",
    [
        ["dispositions", "-a", WORKFLOW, "--quarantined"],
        ["retry", "-a", WORKFLOW, "--dry-run"],
    ],
    ids=["dispositions-quarantined", "retry-dry-run"],
)
def test_the_reason_prints_exactly(project, args):  # noqa: F811
    # Wide enough that the table does not wrap the reason.
    result = CliRunner().invoke(cli, args, env={"COLUMNS": "200"})

    assert REASON in result.output
