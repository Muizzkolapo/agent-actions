"""A guard UDF's body is scanned for bad bus namespaces, against its own valid set (#1192).

`validate-udfs` warns when a UDF reads a bus namespace that is not an action name, and
scanned only `impl:` UDFs, so the same mistake in a guard UDF was silent.

The valid set differs: a tool UDF receives the action-keyed bus, a guard receives the
evaluation context, which also carries the record's envelope fields. So `data["source_guid"]`
is correct in a guard and would be flagged against the tool set. Merging the two ref lists
into one scan would fix that by widening the tool set too, silencing real findings there.
"""

from __future__ import annotations

from unittest import mock

import pytest

from agent_actions.utils.constants import RUNTIME_BUS_NAMESPACES
from agent_actions.validation.validate_udfs import ValidateUDFsCommand


def _sources(**bodies: str) -> dict[str, str]:
    return dict(bodies)


class TestTheValidSetForAGuardIsWiderThanForATool:
    def test_the_envelope_fields_a_guard_context_carries_are_allowed(self):
        """Measured from `_build_evaluation_context`: a guard reading `source_guid` is
        correct, and the tool set holds no such name."""
        guard_valid = ValidateUDFsCommand._guard_valid_namespaces({"tag"})

        for field in ("source_guid", "parent_source_guid", "producer_source_guids", "_state"):
            assert field in guard_valid, f"{field} would be a false warning on a guard UDF"

    def test_it_still_holds_the_action_names_and_runtime_namespaces(self):
        guard_valid = ValidateUDFsCommand._guard_valid_namespaces({"tag"})

        assert "tag" in guard_valid
        assert RUNTIME_BUS_NAMESPACES <= guard_valid

    def test_content_is_not_allowed(self):
        """The guard context flattens `content` rather than exposing it — its keys are
        spread up — so a guard reading `data["content"]` genuinely is a mistake."""
        assert "content" not in ValidateUDFsCommand._guard_valid_namespaces({"tag"})

    @pytest.mark.parametrize("key", ["base_name", "i", "idx", "param_name"])
    def test_the_promoted_version_loop_keys_are_allowed(self, key):
        """Measured from `build_guard_context`: a versioned action's guard context
        promotes these alongside the action namespaces, so a guard reading `idx` is
        correct and warning about it would be a false positive."""
        assert key in ValidateUDFsCommand._guard_valid_namespaces({"tag"})


class TestAGuardUdfIsScanned:
    def test_a_bad_namespace_in_a_guard_body_is_warned_about(self):
        cmd = ValidateUDFsCommand.__new__(ValidateUDFsCommand)
        body = 'def ug_keep(data):\n    return data["tpg"]["name"] != "x"\n'

        warnings = cmd._find_guard_bus_namespace_warnings(_sources(ug_keep=body), {"tag"})

        assert any("tpg" in w for w in warnings), warnings

    def test_an_envelope_read_is_not_warned_about(self):
        """The false-warning case the two-set split exists to prevent."""
        cmd = ValidateUDFsCommand.__new__(ValidateUDFsCommand)
        body = 'def ug_keep(data):\n    return data["source_guid"] and data["tag"]["name"]\n'

        warnings = cmd._find_guard_bus_namespace_warnings(_sources(ug_keep=body), {"tag"})

        assert warnings == [], warnings


class TestTheToolSetIsNotWidened:
    """The central claim of the two-scan split. The previous version of this class built
    the tool set as an inline literal and never called the production method, so replacing
    the tool scan's set with the guard's — exactly the merge this design argues against —
    left the whole suite green.
    """

    @staticmethod
    def _tool_warnings(body: str) -> list[str]:
        """Through the real method, so a change to the set it uses is visible here."""

        def t(data):
            return data

        t.__wrapped_source__ = body
        registry = {"t": {"function": t}}
        cmd = ValidateUDFsCommand.__new__(ValidateUDFsCommand)
        with mock.patch.object(ValidateUDFsCommand, "_udf_sources", return_value={"t": body}):
            return cmd._find_bus_namespace_warnings(registry, {"t"}, {"tag"})

    def test_a_tool_reading_an_envelope_field_is_warned_about(self):
        """If the two scans were merged into one widened set this finding would vanish —
        a tool UDF receives the action-keyed bus, which carries no `source_guid`."""
        warnings = self._tool_warnings('def t(data):\n    return data["source_guid"]\n')

        assert any("source_guid" in w for w in warnings), warnings

    def test_a_tool_reading_a_version_key_is_warned_about(self):
        warnings = self._tool_warnings('def t(data):\n    return data["idx"]\n')

        assert any("idx" in w for w in warnings), warnings

    def test_a_tool_reading_an_action_name_is_not(self):
        warnings = self._tool_warnings('def t(data):\n    return data["tag"]\n')

        assert warnings == [], warnings
