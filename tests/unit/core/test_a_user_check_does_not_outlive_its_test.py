"""A user `@expectation_check` one test registers is gone when the next test starts.

Each test below discovers its own copy of the same tools file, the way a CLI test
runs a tmp copy of a fixture project. The registry refuses a second file claiming a
registered name, so whichever test runs second failed on the first one's leftover:
nothing reset the expectation registry between tests (1570).
"""

from __future__ import annotations

import sys

import pytest

from agent_actions.expectations import registry as expectation_registry
from agent_actions.input.loaders.udf import discover_udfs
from agent_actions.utils.udf_management.registry import clear_registry

CHECKS = (
    "from agent_actions import expectation_check\n"
    "\n"
    '@expectation_check("leftover_check_1570")\n'
    "def leftover_check_1570(value, params):\n"
    "    return True, ''\n"
)


@pytest.fixture
def fresh_copy(tmp_path):
    # As tests/unit/cli/test_json_stdout_clean.py does: forget the UDF modules, not the checks.
    clear_registry()
    for name in [k for k in sys.modules if k.startswith("agent_actions._udfs.")]:
        sys.modules.pop(name, None)
    (tmp_path / "checks.py").write_text(CHECKS, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("copy", ["first", "second"])
def test_each_copy_of_the_tools_file_registers_its_check(fresh_copy, copy):
    discover_udfs(fresh_copy)

    assert expectation_registry.get("leftover_check_1570") is not None
    assert expectation_registry._USER_CHECK_SOURCES["leftover_check_1570"][1] == str(
        fresh_copy / "checks.py"
    )
