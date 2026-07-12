"""RECORD-mode UDF input is a Bus, so data.require() fails loud at the wire point."""

import pytest

from agent_actions.config.schema import Granularity
from agent_actions.errors import AgentActionsError
from agent_actions.utils.udf_management.registry import clear_registry, udf_tool
from agent_actions.utils.udf_management.tooling import execute_user_defined_function


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def test_record_udf_require_raises_naming_namespace():
    @udf_tool(granularity=Granularity.RECORD)
    def strict_reader(data):
        return data.require("nope")

    with pytest.raises(AgentActionsError) as exc:
        execute_user_defined_function("strict_reader", {"author": {}})
    # The unknown namespace must surface through the execute wrapper — a plain
    # dict input raises "no attribute 'require'" instead, which omits "nope".
    assert "nope" in str(exc.value)


def test_record_udf_tolerant_reads_survive_wrap():
    @udf_tool(granularity=Granularity.RECORD)
    def mixed_reader(data):
        return {"missing": data.get("nope"), "present": data["author"], "has": "author" in data}

    result = execute_user_defined_function("mixed_reader", {"author": {"x": 1}})
    assert result == {"missing": None, "present": {"x": 1}, "has": True}
