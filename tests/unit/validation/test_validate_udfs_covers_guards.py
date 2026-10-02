"""`validate-udfs` checks a guard's UDF, not only `impl:` (#1191).

The command is documented as validating all UDF references in config without running the
workflow, and walked the config for one key. #1188 made `udf:` guards loadable for the
first time, so a guard UDF name became a reference a user can get wrong — and its runtime
check only fires when the action runs, which is what this command exists to avoid.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.errors import FunctionNotFoundError
from agent_actions.input.loaders.udf import validate_udf_references
from agent_actions.utils.udf_management import registry as registry_module
from agent_actions.utils.udf_management.registry import UDF_REGISTRY


@pytest.fixture
def registered():
    """Register the names these configs reference, and leave the registry as found."""

    def ug_echo(data):
        return data

    def ug_keep(data):
        return True

    modules_before = set(registry_module._registered_modules)
    registry_module.udf_tool(ug_echo)
    registry_module.udf_tool(ug_keep)
    try:
        yield
    finally:
        for name in ("ug_echo", "ug_keep"):
            UDF_REGISTRY.pop(name, None)
        registry_module._registered_modules.intersection_update(modules_before)


def _config(guard: Any) -> dict[str, Any]:
    return {"wf": {"actions": [{"name": "decide", "impl": "ug_echo", "guard": guard}]}}


class TestAGuardsUdfIsChecked:
    def test_a_string_guard_naming_an_unregistered_udf_is_refused(self, registered):
        with pytest.raises(FunctionNotFoundError, match="ug_kep"):
            validate_udf_references(_config("udf:ug_kep"))

    def test_a_dict_guard_naming_an_unregistered_udf_is_refused(self, registered):
        with pytest.raises(FunctionNotFoundError, match="ug_kep"):
            validate_udf_references(_config({"condition": "udf:ug_kep", "on_false": "skip"}))

    def test_a_registered_one_passes_in_both_spellings(self, registered):
        validate_udf_references(_config("udf:ug_keep"))
        validate_udf_references(_config({"condition": "udf:ug_keep", "on_false": "skip"}))


class TestWhatIsNotAUdfReferenceIsLeftAlone:
    """The walk must not start treating expressions or field names as UDF names."""

    def test_a_sql_guard_is_not_read_as_a_udf(self, registered):
        validate_udf_references(_config("status == 'active'"))

    def test_a_dict_sql_guard_is_not_read_as_a_udf(self, registered):
        validate_udf_references(_config({"condition": "score > 50", "on_false": "skip"}))

    def test_a_guard_naming_no_condition_is_not_read_as_a_udf(self, registered):
        validate_udf_references(_config({"on_false": "skip"}))

    def test_a_non_string_guard_does_not_crash_the_walk(self, registered):
        validate_udf_references(_config(None))
        validate_udf_references(_config(42))
        validate_udf_references(_config(["udf:ug_kep"]))

    def test_the_udf_prefix_is_case_sensitive_as_the_parser_is(self, registered):
        """`GuardParser` only treats a lowercase `udf:` as a UDF, so this is SQL to the
        runtime; reading it as a UDF here would refuse a config that loads."""
        validate_udf_references(_config("UDF:ug_kep"))


class TestImplIsStillChecked:
    def test_an_unregistered_impl_is_still_refused(self, registered):
        with pytest.raises(FunctionNotFoundError, match="no_such_tool"):
            validate_udf_references({"wf": {"actions": [{"name": "a", "impl": "no_such_tool"}]}})

    def test_a_guard_does_not_mask_an_impl_error(self, registered):
        """Both are collected, so a valid guard beside a bad impl still fails."""
        with pytest.raises(FunctionNotFoundError, match="no_such_tool"):
            validate_udf_references(
                {"wf": {"actions": [{"name": "a", "impl": "no_such_tool", "guard": "udf:ug_keep"}]}}
            )


class TestTheCommandReportsWhatItChecked:
    def test_guard_udfs_are_counted_separately_from_impl(self, registered):
        """The summary says "N Tools referenced in config"; a guard UDF is not a tool, and
        folding it into that count would overstate what the number means."""
        from agent_actions.validation.validate_udfs import ValidateUDFsCommand

        config = {
            "wf": {
                "actions": [
                    {"name": "a", "impl": "ug_echo", "guard": "udf:ug_keep"},
                    {"name": "b", "impl": "ug_echo"},
                ]
            }
        }

        assert ValidateUDFsCommand._count_impl_references(config) == {"ug_echo"}
        assert ValidateUDFsCommand._count_guard_udf_references(config) == {"ug_keep"}


class TestAMalformedNameIsLeftToTheCheckThatOwnsTheMessage:
    """This walk runs before the structural preflight, so reporting a malformed guard UDF
    as a missing function would answer the wrong question: a dotted name would be met with
    "did you forget the decorator?" rather than "drop the module prefix", which is the
    message the guard parser exists to give.
    """

    def test_a_dotted_name_is_not_reported_as_a_missing_function(self, registered):
        validate_udf_references(_config("udf:mymod.check_it"))

    def test_a_blocklisted_name_is_not_reported_as_a_missing_function(self, registered):
        validate_udf_references(_config("udf:exec"))

    def test_an_empty_name_is_not_looked_up(self, registered):
        """`get_udf("")` would be a lookup of nothing; the parser refuses it first."""
        validate_udf_references(_config("udf:"))
        validate_udf_references(_config({"condition": "udf:   "}))

    def test_a_condition_that_is_not_a_string_is_not_looked_up(self, registered):
        validate_udf_references(_config({"condition": {"nested": 1}}))
        validate_udf_references(_config({"condition": ["udf:ug_kep"]}))
        validate_udf_references(_config({"condition": 42}))
