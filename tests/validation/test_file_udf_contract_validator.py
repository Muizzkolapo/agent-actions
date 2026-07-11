"""FILE-mode UDF return-contract warnings: FILE + non-FileUDFResult annotation flagged."""

import pytest

from agent_actions.config.types import Granularity
from agent_actions.utils.udf_management.registry import (
    UDF_REGISTRY,
    FileUDFResult,
    clear_registry,
    udf_tool,
)
from agent_actions.validation.file_udf_contract_validator import find_file_udf_contract_warnings


@pytest.fixture(autouse=True)
def _clean():
    clear_registry()
    yield
    clear_registry()


def test_file_udf_returning_list_is_warned():
    @udf_tool(granularity=Granularity.FILE)
    def dedup_list(data) -> list[dict]:
        return data

    warnings = find_file_udf_contract_warnings(UDF_REGISTRY)
    assert any("dedup_list" in w for w in warnings)
    assert any("FileUDFResult" in w for w in warnings)


def test_file_udf_returning_fileudfresult_is_ok():
    @udf_tool(granularity=Granularity.FILE)
    def merge_ok(data) -> FileUDFResult:
        return FileUDFResult(outputs=[])

    assert find_file_udf_contract_warnings(UDF_REGISTRY) == []


def test_file_udf_string_annotation_fileudfresult_is_ok():
    @udf_tool(granularity=Granularity.FILE)
    def merge_str(data) -> "FileUDFResult":
        return FileUDFResult(outputs=[])

    assert find_file_udf_contract_warnings(UDF_REGISTRY) == []


def test_record_udf_is_ignored():
    @udf_tool(granularity=Granularity.RECORD)
    def rec_tool(data) -> dict:
        return data

    assert find_file_udf_contract_warnings(UDF_REGISTRY) == []


def test_file_udf_missing_return_annotation_is_warned():
    @udf_tool(granularity=Granularity.FILE)
    def no_annotation(data):
        return data

    assert any("no_annotation" in w for w in find_file_udf_contract_warnings(UDF_REGISTRY))


def test_warning_names_the_fix_path():
    @udf_tool(granularity=Granularity.FILE)
    def constructs_dicts(data) -> list[dict]:
        return data

    (warning,) = find_file_udf_contract_warnings(UDF_REGISTRY)
    assert "source_index" in warning
    assert "filter mode" in warning


def test_referenced_filter_scopes_to_named_udfs():
    @udf_tool(granularity=Granularity.FILE)
    def used_udf(data) -> list[dict]:
        return data

    @udf_tool(granularity=Granularity.FILE)
    def unused_udf(data) -> list[dict]:
        return data

    warnings = find_file_udf_contract_warnings(UDF_REGISTRY, referenced={"used_udf"})
    assert any("used_udf" in w for w in warnings)
    assert not any("unused_udf" in w for w in warnings)


def test_referenced_none_warns_all():
    @udf_tool(granularity=Granularity.FILE)
    def a_udf(data) -> list[dict]:
        return data

    @udf_tool(granularity=Granularity.FILE)
    def b_udf(data) -> list[dict]:
        return data

    assert len(find_file_udf_contract_warnings(UDF_REGISTRY)) == 2


def test_unresolvable_forward_ref_does_not_crash():
    # A string annotation naming a type that does not exist must be handled
    # without importing/resolving it — it is simply not FileUDFResult, so warn.
    @udf_tool(granularity=Granularity.FILE)
    def bad_ref(data) -> "TypeThatDoesNotExist":  # noqa: F821
        return data

    assert any("bad_ref" in w for w in find_file_udf_contract_warnings(UDF_REGISTRY))
