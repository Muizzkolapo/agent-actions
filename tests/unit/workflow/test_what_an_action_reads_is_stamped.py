"""What an action reads — its context_scope and dependencies — is stamped beside config_hash (1332).

Each has a digest of its own so that recording it changed no digest already stored: a
store stamped before holds neither, and an absent digest never reads as an edit.
"""

from agent_actions.workflow.executor import (
    CONFIG_EDIT,
    MODEL_EDIT,
    _compute_action_config_hash,
    _compute_context_scope_hash,
    _compute_dependencies_hash,
    _edits_since,
    edited_since_its_work_began,
)

CONFIG = {
    "prompt": "p",
    "schema": "s",
    "model_name": "m",
    "model_vendor": "v",
    "dependencies": ["a", "b"],
    "context_scope": {"observe": ["a.x", "b.*"], "drop": ["a.y"]},
}


def _stamp(config):
    return {
        "config_hash": _compute_action_config_hash(config),
        "model_name": config["model_name"],
        "model_vendor": config["model_vendor"],
        "context_scope_hash": _compute_context_scope_hash(config),
        "dependencies_hash": _compute_dependencies_hash(config),
    }


def _with_scope(**scope):
    return {**CONFIG, "context_scope": scope}


class TestTheStoredDigestDoesNotRotate:
    def test_config_hash_is_what_it_was_before_and_ignores_what_the_action_reads(self):
        assert _compute_action_config_hash({"prompt": "p", "schema": "s"}) == "c09fe225de7185fe"
        assert _compute_action_config_hash(CONFIG) == "c09fe225de7185fe"


class TestTheContextScopeDigest:
    def test_each_directive_counts(self):
        base = _compute_context_scope_hash(CONFIG)
        for scope in (
            {"observe": ["a.x", "b.*", "a.z"], "drop": ["a.y"]},
            {"observe": ["a.x", "b.*"]},
            {"observe": ["a.x", "b.*"], "drop": ["a.y"], "passthrough": ["a.z"]},
            {"observe": ["a.x", "b.*"], "drop": ["a.y"], "seed": {"ref": "$file:r.json"}},
        ):
            assert _compute_context_scope_hash(_with_scope(**scope)) != base, scope

    def test_order_and_repeats_within_a_list_do_not(self):
        reordered = _with_scope(drop=["a.y"], observe=["b.*", "a.x", "b.*"])
        assert _compute_context_scope_hash(reordered) == _compute_context_scope_hash(CONFIG)

    def test_an_empty_observe_is_not_an_absent_one(self):
        """`observe: []` gates the action to the framework's namespaces; absent, it is not."""
        assert _compute_context_scope_hash(_with_scope(observe=[])) != _compute_context_scope_hash(
            {**CONFIG, "context_scope": None}
        )


class TestTheDependenciesDigest:
    def test_an_added_or_removed_dependency_counts(self):
        base = _compute_dependencies_hash(CONFIG)
        assert _compute_dependencies_hash({**CONFIG, "dependencies": ["a"]}) != base
        assert _compute_dependencies_hash({**CONFIG, "dependencies": ["a", "b", "c"]}) != base

    def test_a_single_name_reads_as_a_list_of_one(self):
        assert _compute_dependencies_hash({"dependencies": "a"}) == _compute_dependencies_hash(
            {"dependencies": ["a"]}
        )


class TestEditsSince:
    def test_nothing_edited(self):
        assert _edits_since(_stamp(CONFIG), CONFIG) == []

    def test_each_edit_is_named(self):
        edited = {
            **CONFIG,
            "prompt": "q",
            "model_name": "n",
            "dependencies": ["a"],
            "context_scope": {"observe": ["a.x"]},
        }
        assert _edits_since(_stamp(CONFIG), edited) == [
            MODEL_EDIT,
            CONFIG_EDIT,
            "context scope",
            "dependencies",
        ]

    def test_a_stamp_written_before_these_digests_never_reads_as_an_edit(self):
        old = _stamp(CONFIG)
        del old["context_scope_hash"], old["dependencies_hash"]
        edited = {**CONFIG, "dependencies": ["a"], "context_scope": {"observe": ["a.x"]}}

        assert _edits_since(old, edited) == []

    def test_an_action_stopped_partway_reads_a_scope_edit(self):
        details = {"answered_under": _stamp(CONFIG)}
        edited = _with_scope(observe=["a.x"])

        assert edited_since_its_work_began(details, edited) is True
        assert edited_since_its_work_began(details, CONFIG) is False
