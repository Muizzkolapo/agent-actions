import subprocess
import sys
from pathlib import Path

import pytest

import agent_actions
from agent_actions.expectations import registry as expectation_registry
from agent_actions.utils.udf_management import registry as udf_registry


def test_public_names_are_the_defining_modules_objects():
    from agent_actions import FileUDFResult, expectation_check, udf_tool

    assert expectation_check is expectation_registry.expectation_check
    assert agent_actions.expectation_check is expectation_registry.expectation_check
    assert udf_tool is udf_registry.udf_tool
    assert FileUDFResult is udf_registry.FileUDFResult


def test_every_name_in_all_resolves():
    for name in agent_actions.__all__:
        assert getattr(agent_actions, name) is not None


def test_an_unknown_name_raises_attribute_error():
    with pytest.raises(AttributeError, match="no_such_name"):
        agent_actions.no_such_name  # noqa: B018


def test_star_import_binds_every_public_name():
    code = (
        "from agent_actions import *\n"
        "from agent_actions.expectations.registry import expectation_check as e\n"
        "assert expectation_check is e\n"
        "assert udf_tool and FileUDFResult and __version__\n"
    )
    repo_root = Path(agent_actions.__file__).resolve().parents[1]
    subprocess.run([sys.executable, "-c", code], check=True, cwd=repo_root)


def test_the_pydantic_build_default_is_set_on_import():
    code = (
        "import os\n"
        "os.environ.pop('DEFER_PYDANTIC_BUILD', None)\n"
        "import agent_actions\n"
        "assert os.environ['DEFER_PYDANTIC_BUILD'] == 'false'\n"
    )
    repo_root = Path(agent_actions.__file__).resolve().parents[1]
    subprocess.run([sys.executable, "-c", code], check=True, cwd=repo_root)


def _run_fresh(code: str) -> None:
    repo_root = Path(agent_actions.__file__).resolve().parents[1]
    subprocess.run([sys.executable, "-c", code], check=True, cwd=repo_root)


def test_importing_the_package_does_not_load_the_expectation_checks():
    _run_fresh(
        "import sys\n"
        "import agent_actions\n"
        "assert 'agent_actions.expectations.registry' not in sys.modules\n"
        "assert 'agent_actions.expectations.judge' not in sys.modules\n"
    )


def test_subpackages_stay_reachable_after_a_bare_package_import():
    _run_fresh(
        "import agent_actions\n"
        "for name in ('config', 'errors', 'utils', 'llm', 'prompt', 'storage'):\n"
        "    assert getattr(agent_actions, name).__name__ == 'agent_actions.' + name\n"
        "assert not hasattr(agent_actions, 'no_such_subpackage')\n"
    )
