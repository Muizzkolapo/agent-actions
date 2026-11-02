"""A function not found names the tool files discovery skipped, which may define it (1608)."""

import pytest

from agent_actions.errors import FunctionNotFoundError
from agent_actions.utils.udf_management import registry


@pytest.fixture(autouse=True)
def _no_skipped_files():
    registry._skipped_tool_files.clear()
    yield
    registry._skipped_tool_files.clear()


def test_the_error_names_each_skipped_file():
    registry.record_skipped_tool_files({"tools/wf/broken.py": "boom at import"})

    with pytest.raises(FunctionNotFoundError) as caught:
        registry.get_udf("never_registered")

    assert "tools/wf/broken.py (boom at import)" in str(caught.value)
    assert caught.value.context["skipped_tool_files"] == {"tools/wf/broken.py": "boom at import"}


def test_without_a_skipped_file_the_error_is_as_before():
    with pytest.raises(FunctionNotFoundError) as caught:
        registry.get_udf_metadata("never_registered")

    assert str(caught.value).startswith("Function 'never_registered' not found")
    assert "skipped_tool_files" not in caught.value.context


def test_clearing_the_registry_forgets_the_skipped_files():
    registry.record_skipped_tool_files({"x.py": "e"})
    registry.clear_registry()
    assert registry._skipped_tool_files == {}
