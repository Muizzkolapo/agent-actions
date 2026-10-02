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
    def test_version_keys_are_not_allowed_without_a_versioned_action(self, key):
        """These were a hardcoded addition to every guard's set. They are derived from the
        config now, so on a workflow with no versioned action they are correctly absent —
        nothing promotes them there, and a guard reading `idx` is making a real mistake.
        `TestADeclaredLoopParamIsAllowed` covers the versioned case."""
        assert key not in ValidateUDFsCommand._guard_valid_namespaces({"tag"})


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


class TestADeclaredLoopParamIsAllowed:
    """`VersionNamespaceBuilder.build` promotes every non-reserved key of the version
    context to the top level, so `versions: {param: classifier_id}` gives its guard a
    top-level `classifier_id`. No fixed list can know that name — it is a config decision,
    and the sample project declares three of them already (`iteration`, `voter_id`,
    `verifier_id`).

    The config here carries `_version_context`, not `versions:`, because that is the shape
    this command receives: expansion replaces `versions:` with one `_version_context` per
    variant before `validate-udfs` ever loads it. A fixture using `versions:` would test a
    shape production never sees — which is how the first attempt at this passed its unit
    tests while the real command still warned.
    """

    @staticmethod
    def _config(param: str) -> dict:
        return {
            "name": "wf",
            "actions": [
                {"name": "tag", "prompt": "p", "schema": {"name": "string"}},
                {
                    "name": "decide_1",
                    "impl": "ug_echo",
                    "guard": "udf:ug_keep",
                    "_version_context": {
                        "i": 1,
                        "idx": 0,
                        "length": 2,
                        "first": True,
                        "last": False,
                        "base_name": "decide",
                        "param_name": param,
                        param: 1,
                    },
                },
            ],
        }

    def test_the_declared_param_is_in_the_valid_set(self):
        params = ValidateUDFsCommand._promoted_version_names(self._config("classifier_id"))
        valid = ValidateUDFsCommand._guard_valid_namespaces({"tag", "decide_1"}, params)

        assert "classifier_id" in valid

    def test_the_framework_keys_come_from_the_same_derivation(self):
        """They used to be a hardcoded list beside this; deriving covers both."""
        params = ValidateUDFsCommand._promoted_version_names(self._config("classifier_id"))

        assert {"i", "idx", "base_name", "param_name"} <= params

    def test_the_reserved_keys_that_are_not_promoted_stay_out(self):
        """`length`, `first` and `last` are in the version context and are NOT promoted,
        so a guard reading them is making a real mistake."""
        params = ValidateUDFsCommand._promoted_version_names(self._config("classifier_id"))

        assert params.isdisjoint({"length", "first", "last"})

    def test_a_guard_reading_the_param_is_not_warned_about(self):
        cmd = ValidateUDFsCommand.__new__(ValidateUDFsCommand)
        body = 'def ug_keep(data):\n    return data["classifier_id"] > 0\n'
        params = ValidateUDFsCommand._promoted_version_names(self._config("classifier_id"))

        warnings = cmd._find_guard_bus_namespace_warnings(
            {"ug_keep": body}, {"tag", "decide_1"}, loop_params=params
        )

        assert warnings == [], warnings

    def test_an_undeclared_param_is_still_warned_about(self):
        """The set widens by what this config declares, not by anything version-shaped."""
        cmd = ValidateUDFsCommand.__new__(ValidateUDFsCommand)
        body = 'def ug_keep(data):\n    return data["voter_id"] > 0\n'
        params = ValidateUDFsCommand._promoted_version_names(self._config("classifier_id"))

        warnings = cmd._find_guard_bus_namespace_warnings(
            {"ug_keep": body}, {"tag", "decide_1"}, loop_params=params
        )

        assert any("voter_id" in w for w in warnings), warnings
