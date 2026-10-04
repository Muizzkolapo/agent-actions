"""A test that runs `agac` runs the tree it lives in, not the installed checkout.

The console script imports `agent_actions` from wherever the venv's editable
install points, and from a second worktree that is another checkout: a CLI test
would pass or fail on that checkout's code, whatever the change under test.
pytest.ini's `pythonpath` reaches the pytest process only.
"""

from pathlib import Path

from tests.integration.test_retry_selection_under_batch import _agac

REPO = Path(__file__).resolve().parents[2]

# Tool discovery imports this inside the CLI process, so it sees the
# `agent_actions` that process imported.
PROBE = """\
from pathlib import Path

import agent_actions
from agent_actions import udf_tool

Path(__file__).with_name("imported_from.txt").write_text(agent_actions.__file__)


@udf_tool
def probe(data):
    return data
"""


def test_the_agac_a_test_runs_imports_agent_actions_from_this_tree(tmp_path):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "probe.py").write_text(PROBE)

    code, output = _agac(tmp_path, "list-udfs", "-u", "tools")

    assert code == 0, output
    imported = Path((tools / "imported_from.txt").read_text()).resolve()
    assert imported == REPO / "agent_actions" / "__init__.py"
