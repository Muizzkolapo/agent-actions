"""Run preflight scans tool and guard UDFs for reads of a bus key no action is named (1609)."""

from typing import Any

import pytest

from agent_actions.services.preflight_service import PreflightService
from agent_actions.utils.udf_management.registry import UDF_REGISTRY, _registered_modules, udf_tool


def bus_read_tool(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": data.get("m_upstream", {})}


def bus_read_guard(data: dict[str, Any]) -> bool:
    return bool(data.get("m_upstream"))


def bus_read_versions(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": data.get("vote", {})}


def bus_read_short(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": data.get("write", {})}


def bus_read_final(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": data.get("c2__write", {})}


@pytest.fixture(autouse=True)
def _registered():
    for function in (
        bus_read_tool,
        bus_read_guard,
        bus_read_versions,
        bus_read_short,
        bus_read_final,
    ):
        udf_tool()(function)
    yield
    for function in (
        bus_read_tool,
        bus_read_guard,
        bus_read_versions,
        bus_read_short,
        bus_read_final,
    ):
        UDF_REGISTRY.pop(function.__name__, None)
    _registered_modules.discard(__name__)


def _warnings(configs, monkeypatch):
    found: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        PreflightService,
        "_warn_findings",
        staticmethod(lambda label, f, **_: found.append((label, f))),
    )
    PreflightService("wf", configs, None, "wf.yml")._warn_unknown_bus_namespace_reads()
    return [
        finding for label, findings in found if label == "bus namespaces" for finding in findings
    ]


def test_a_tool_and_a_guard_reading_an_impl_name_are_named(monkeypatch):
    configs = {
        "upstream": {"kind": "tool", "model_vendor": "tool", "model_name": "m_upstream"},
        "reader": {"kind": "tool", "model_vendor": "tool", "model_name": "bus_read_tool"},
        "judged": {"model_vendor": "openai", "conditional_clause": "bus_read_guard"},
    }

    warnings = _warnings(configs, monkeypatch)

    assert [w.split(":")[0] for w in sorted(warnings)] == ["bus_read_guard", "bus_read_tool"]
    assert all("'m_upstream'" in w for w in warnings)


def test_a_versioned_actions_base_name_is_a_bus_key(monkeypatch):
    configs = {
        "vote_1": {
            "kind": "tool",
            "model_vendor": "tool",
            "model_name": "m",
            "version_base_name": "vote",
        },
        "merge": {"kind": "tool", "model_vendor": "tool", "model_name": "bus_read_versions"},
    }

    assert _warnings(configs, monkeypatch) == []


def _instance(impl: str) -> dict[str, Any]:
    names = {"write": "c2__write", "review": "c2__review"}
    return {
        "kind": "tool",
        "model_vendor": "tool",
        "model_name": impl,
        "_include": {"branch": "round", "instance": "c2", "local_name": "review", "names": names},
    }


def _instance_configs(reader: dict[str, Any]) -> dict[str, Any]:
    write = {"kind": "tool", "model_vendor": "tool", "model_name": "m_write"}
    return {"c2__write": write, "c2__review": reader}


def test_a_tool_of_an_instance_that_reads_a_short_name_is_not_warned_about(monkeypatch):
    assert _warnings(_instance_configs(_instance("bus_read_short")), monkeypatch) == []


def test_a_tool_of_an_instance_that_reads_a_final_name_is_warned_about(monkeypatch):
    warnings = _warnings(_instance_configs(_instance("bus_read_final")), monkeypatch)

    assert [w.split(":")[0] for w in warnings] == ["bus_read_final"]
    assert "'c2__write'" in warnings[0]


def test_a_host_tool_that_reads_a_short_name_is_warned_about(monkeypatch):
    host = {"kind": "tool", "model_vendor": "tool", "model_name": "bus_read_short"}
    configs = {**_instance_configs(_instance("m_review")), "host": host}

    warnings = _warnings(configs, monkeypatch)

    assert [w.split(":")[0] for w in warnings] == ["bus_read_short"]
    assert "'write'" in warnings[0]
