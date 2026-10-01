"""A guard UDF's body is scanned for bad bus namespaces, against its own valid set (#1192).

`validate-udfs` warns when a UDF reads a bus namespace that is not an action name, and
scanned only `impl:` UDFs, so the same mistake in a guard UDF was silent.

The valid set differs: a tool UDF receives the action-keyed bus, a guard receives the
evaluation context, which also carries the record's envelope fields. So `data["source_guid"]`
is correct in a guard and would be flagged against the tool set. Merging the two ref lists
into one scan would fix that by widening the tool set too, silencing real findings there.
"""

from __future__ import annotations

import pytest

from agent_actions.record.envelope import RECORD_FRAMEWORK_FIELDS
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

    def test_the_wider_set_is_exactly_the_envelope_minus_content(self):
        """Pins the derivation rather than re-listing it, so a field added to the envelope
        is covered without this test being edited."""
        guard_valid = ValidateUDFsCommand._guard_valid_namespaces({"tag"})

        assert guard_valid == {"tag"} | RUNTIME_BUS_NAMESPACES | (
            RECORD_FRAMEWORK_FIELDS - {"content"}
        )


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
    def test_a_tool_reading_an_envelope_field_is_still_warned_about(self):
        """If the two scans were merged into one widened set this finding would vanish —
        a tool UDF receives the action-keyed bus, which carries no `source_guid`."""
        from agent_actions.validation.bus_namespace_validator import (
            find_unknown_bus_namespaces,
        )

        body = 'def t(data):\n    return data["source_guid"]\n'

        warnings = find_unknown_bus_namespaces({"t": body}, {"tag"} | RUNTIME_BUS_NAMESPACES)

        assert any("source_guid" in w for w in warnings), warnings

    @pytest.mark.parametrize("name", ["source_guid", "_state"])
    def test_the_tool_valid_set_excludes_the_envelope(self, name):
        assert name not in ({"tag"} | RUNTIME_BUS_NAMESPACES)
