"""FILE-mode UDF return-contract warnings: only dict-constructing UDFs are flagged."""

from typing import Optional

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


# --- FileUDFResult annotation is the declared-safe signal (never flagged) -----


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


def test_union_fileudfresult_or_none_is_ok():
    @udf_tool(granularity=Granularity.FILE)
    def maybe_merge(data) -> FileUDFResult | None:
        return FileUDFResult(outputs=[])

    assert find_file_udf_contract_warnings(UDF_REGISTRY) == []


def test_typing_optional_fileudfresult_is_ok():
    # typing.Optional (distinct from `X | None`: it has __name__ == "Optional")
    # must also be recognised, so pin this exact spelling.
    @udf_tool(granularity=Granularity.FILE)
    def maybe_merge_opt(data) -> Optional[FileUDFResult]:  # noqa: UP045
        return FileUDFResult(outputs=[])

    assert find_file_udf_contract_warnings(UDF_REGISTRY) == []


def test_record_udf_is_ignored():
    @udf_tool(granularity=Granularity.RECORD)
    def rec_tool(data) -> dict:
        return data

    assert find_file_udf_contract_warnings(UDF_REGISTRY) == []


# --- Filter mode: returns the received items unchanged (never flagged) --------


def test_filter_mode_udf_not_flagged():
    @udf_tool(granularity=Granularity.FILE)
    def filter_only(data) -> list[dict]:
        out = []
        for item in data:
            out.append(item)  # returns input items → filter mode
        return out

    assert find_file_udf_contract_warnings(UDF_REGISTRY) == []


def test_return_data_directly_not_flagged():
    @udf_tool(granularity=Granularity.FILE)
    def passthrough(data) -> list[dict]:
        return data

    assert find_file_udf_contract_warnings(UDF_REGISTRY) == []


def test_filter_comprehension_over_items_not_flagged():
    @udf_tool(granularity=Granularity.FILE)
    def keep_scored(data) -> list[dict]:
        return [item for item in data if item.get("score")]

    assert find_file_udf_contract_warnings(UDF_REGISTRY) == []


def test_local_lookup_dict_not_flagged():
    # A dict literal used as a local lookup table is never returned/appended,
    # so it must not be mistaken for output construction.
    @udf_tool(granularity=Granularity.FILE)
    def with_lookup(data) -> list[dict]:
        lookup = {"a": 1, "b": 2}
        out = []
        for item in data:
            item["rank"] = lookup.get(item.get("grade"))
            out.append(item)
        return out

    assert find_file_udf_contract_warnings(UDF_REGISTRY) == []


def test_returns_fileudfresult_in_body_not_flagged():
    # No return annotation, but the body appends dict literals to a list that is
    # wrapped in FileUDFResult and returned — the correct N→M idiom. The runtime
    # never crashes here, so it must not be flagged.
    @udf_tool(granularity=Granularity.FILE)
    def build_result(data):
        outputs = []
        for idx, record in enumerate(data):
            outputs.append({"source_index": idx, "data": record})
        return FileUDFResult(outputs=outputs)

    assert find_file_udf_contract_warnings(UDF_REGISTRY) == []


# --- Construct mode: returns freshly-built dicts (must be flagged) -------------


def test_construct_mode_udf_flagged():
    @udf_tool(granularity=Granularity.FILE)
    def construct(data) -> list[dict]:
        out = []
        for item in data:
            out.append({"key": item.get("key")})  # new dict → needs FileUDFResult
        return out

    assert any("construct" in w for w in find_file_udf_contract_warnings(UDF_REGISTRY))


def test_return_list_of_dict_literals_flagged():
    @udf_tool(granularity=Granularity.FILE)
    def make(data) -> list[dict]:
        return [{"key": "v"}]

    assert any("make" in w for w in find_file_udf_contract_warnings(UDF_REGISTRY))


def test_return_dict_comprehension_flagged():
    @udf_tool(granularity=Granularity.FILE)
    def expand(data) -> list[dict]:
        return [{"key": d.get("key")} for d in data]

    assert any("expand" in w for w in find_file_udf_contract_warnings(UDF_REGISTRY))


def test_dict_constructor_call_flagged():
    @udf_tool(granularity=Granularity.FILE)
    def via_dict_call(data) -> list[dict]:
        out = []
        for d in data:
            out.append(dict(key=d.get("key")))  # dict(...) builds a new dict
        return out

    assert any("via_dict_call" in w for w in find_file_udf_contract_warnings(UDF_REGISTRY))


def test_build_dict_in_var_then_append_flagged():
    @udf_tool(granularity=Granularity.FILE)
    def build_var(data) -> list[dict]:
        out = []
        for d in data:
            row = {"key": d.get("key")}
            out.append(row)
        return out

    assert any("build_var" in w for w in find_file_udf_contract_warnings(UDF_REGISTRY))


def test_return_bare_dict_flagged():
    @udf_tool(granularity=Granularity.FILE)
    def bare(data) -> list[dict]:
        return {"only": "one"}

    assert any("bare" in w for w in find_file_udf_contract_warnings(UDF_REGISTRY))


def test_missing_annotation_construct_is_warned():
    @udf_tool(granularity=Granularity.FILE)
    def no_annotation(data):
        out = []
        for d in data:
            out.append({"id": d.get("id")})
        return out

    assert any("no_annotation" in w for w in find_file_udf_contract_warnings(UDF_REGISTRY))


def test_warning_names_the_fix_path():
    @udf_tool(granularity=Granularity.FILE)
    def constructs_dicts(data) -> list[dict]:
        return [{"id": d.get("id")} for d in data]

    (warning,) = find_file_udf_contract_warnings(UDF_REGISTRY)
    assert "source_index" in warning
    assert "FileUDFResult" in warning


# --- referenced-scoping (unchanged contract; UDFs must construct to be warned) -


def test_referenced_filter_scopes_to_named_udfs():
    @udf_tool(granularity=Granularity.FILE)
    def used_udf(data) -> list[dict]:
        return [{"id": d.get("id")} for d in data]

    @udf_tool(granularity=Granularity.FILE)
    def unused_udf(data) -> list[dict]:
        return [{"id": d.get("id")} for d in data]

    warnings = find_file_udf_contract_warnings(UDF_REGISTRY, referenced={"used_udf"})
    assert any("used_udf" in w for w in warnings)
    assert not any("unused_udf" in w for w in warnings)


def test_referenced_none_warns_all():
    @udf_tool(granularity=Granularity.FILE)
    def a_udf(data) -> list[dict]:
        return [{"id": d.get("id")} for d in data]

    @udf_tool(granularity=Granularity.FILE)
    def b_udf(data) -> list[dict]:
        return [{"id": d.get("id")} for d in data]

    assert len(find_file_udf_contract_warnings(UDF_REGISTRY)) == 2


def test_unresolvable_forward_ref_does_not_crash():
    # A string annotation naming a type that does not exist must be handled
    # without importing/resolving it; the body constructs dicts, so it warns.
    @udf_tool(granularity=Granularity.FILE)
    def bad_ref(data) -> "TypeThatDoesNotExist":  # noqa: F821
        return [{"id": d.get("id")} for d in data]

    assert any("bad_ref" in w for w in find_file_udf_contract_warnings(UDF_REGISTRY))
