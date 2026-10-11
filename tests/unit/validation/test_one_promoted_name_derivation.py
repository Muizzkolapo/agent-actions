"""What `validate-udfs` believes the version namespace promotes must match what it promotes.

`VersionNamespaceBuilder.build` decides which names a versioned action's context puts at the
top level, and two checkers need that list to judge whether a bare reference resolves.
`validate_udfs` kept its own copy of the derivation, and the copy claimed `i` and `idx`
unconditionally wherever a `_version_context` existed. `build` promotes them only when the
context carries them, so a guard UDF reading a name that resolves to nothing was reported as
fine — the silence this command exists to remove.

These assert against `build` itself rather than against the shared helper, so they stay
meaningful after the derivation is unified instead of comparing a function with itself.
"""

from agent_actions.prompt.context.scope_builder import VersionNamespaceBuilder
from agent_actions.validation.validate_udfs import ValidateUDFsCommand


def _build_promotes(version_context: dict) -> set[str]:
    """The names `build` actually puts at the top level, which is the runtime behaviour."""
    built = VersionNamespaceBuilder.build(dict(version_context), "a_1") or {}
    return set(built) - {"version"}


def _walk_claims(version_context: dict) -> set[str]:
    config = {"actions": [{"name": "a_1", "_version_context": dict(version_context)}]}
    return ValidateUDFsCommand._promoted_version_names(config)


class TestTheCheckerAgreesWithTheRuntime:
    def test_a_context_without_i_does_not_promote_i(self):
        """The expander always writes `i`, but a partial context must not be over-claimed:
        claiming a name the runtime does not promote silences a real warning."""
        vc = {"length": 2, "voter_id": 1}

        assert _build_promotes(vc) == {"voter_id"}
        assert _walk_claims(vc) == _build_promotes(vc)

    def test_a_full_expander_context_agrees(self):
        """The shape expansion really produces — the control, so the fix is not just
        'return less'."""
        vc = {"i": 1, "idx": 0, "length": 2, "first": True, "last": False, "voter_id": 1}

        assert _build_promotes(vc) == {"i", "idx", "voter_id"}
        assert _walk_claims(vc) == _build_promotes(vc)

    def test_reserved_keys_are_never_promoted_by_either(self):
        """`length`, `first` and `last` are reachable only as `version.length` etc."""
        vc = {"i": 1, "idx": 0, "length": 2, "first": True, "last": False}

        assert _build_promotes(vc) == {"i", "idx"}
        assert _walk_claims(vc) == _build_promotes(vc)

    def test_several_contexts_in_one_config_are_all_collected(self):
        """The walk's own job -- finding every context in the tree -- must survive."""
        config = {
            "actions": [
                {"name": "a_1", "_version_context": {"i": 1, "idx": 0, "voter_id": 1}},
                {"name": "b_1", "_version_context": {"i": 1, "idx": 0, "classifier_id": 7}},
            ]
        }

        assert ValidateUDFsCommand._promoted_version_names(config) == {
            "i",
            "idx",
            "voter_id",
            "classifier_id",
        }
