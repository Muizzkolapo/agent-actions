"""The docs catalog must report the `context_scope` the runtime actually applies.

`WorkflowParser.parse_workflow` copies each action's own `context_scope` block and nothing
else, so a directive inherited from `defaults:` is discarded -- although `defaults.context_scope`
is a declared, runtime-read field that `deep_merge_context_scope` union-merges into every action
(`expander.py`). The panel then reports no drop for an action the runtime drops a field on, which
is the one config shape where the Drops panel is silently empty.
"""

from __future__ import annotations

import yaml

from agent_actions.tooling.docs.parser import WorkflowParser

# `upstream` declares no context_scope of its own; the drop reaches it only through defaults.
_INHERITED = {
    "name": "inherited_scope",
    "description": "defaults carries the only context_scope",
    "defaults": {
        "model_vendor": "anthropic",
        "model_name": "claude-3",
        "context_scope": {"drop": ["upstream.secret"]},
    },
    "actions": [
        {"name": "upstream", "intent": "produce", "prompt": "make {{ source.text }}"},
        {
            "name": "downstream",
            "intent": "consume",
            "dependencies": ["upstream"],
            "prompt": "read {{ upstream.headline }}",
            "context_scope": {"observe": ["upstream.*"]},
        },
    ],
}


def _parse(tmp_path, workflow: dict) -> dict:
    yml = tmp_path / "workflow.yml"
    yml.write_text(yaml.dump(workflow))
    result = WorkflowParser.parse_workflow(str(yml))
    assert result is not None, "parse_workflow returned None on valid YAML"
    return result


def _action(parsed: dict, name: str) -> dict:
    actions = parsed["actions"]
    assert name in actions, f"{name} missing from {sorted(actions)}"
    return actions[name]


class TestAnInheritedDirectiveIsReported:
    def test_a_defaults_level_drop_reaches_an_action_with_no_scope_of_its_own(self, tmp_path):
        """`upstream` declares nothing; the runtime still drops `upstream.secret` on it."""
        parsed = _parse(tmp_path, _INHERITED)

        scope = _action(parsed, "upstream").get("context_scope") or {}
        assert scope.get("drop") == ["upstream.secret"], scope

    def test_a_defaults_level_drop_also_reaches_an_action_that_declares_its_own(self, tmp_path):
        """deep_merge_context_scope unions; it does not let the action's block replace it."""
        parsed = _parse(tmp_path, _INHERITED)

        scope = _action(parsed, "downstream").get("context_scope") or {}
        assert scope.get("drop") == ["upstream.secret"], scope
        assert scope.get("observe") == ["upstream.*"], scope

    def test_an_action_directive_and_an_inherited_one_of_the_same_name_merge(self, tmp_path):
        """Lists concatenate and deduplicate -- the action does not win outright."""
        workflow = {
            **_INHERITED,
            "actions": [
                {"name": "upstream", "intent": "produce", "prompt": "make {{ source.text }}"},
                {
                    "name": "downstream",
                    "intent": "consume",
                    "dependencies": ["upstream"],
                    "prompt": "read {{ upstream.headline }}",
                    "context_scope": {"drop": ["upstream.other"], "observe": ["upstream.*"]},
                },
            ],
        }
        parsed = _parse(tmp_path, workflow)

        drops = (_action(parsed, "downstream").get("context_scope") or {}).get("drop") or []
        assert sorted(drops) == ["upstream.other", "upstream.secret"], drops


class TestTheHalfThatAlreadyWorks:
    """Controls. A fix must not break the case the parser already handles."""

    def test_an_action_with_no_defaults_still_reports_its_own_scope(self, tmp_path):
        workflow = {
            "name": "own_scope_only",
            "description": "no defaults context_scope",
            "actions": [
                {"name": "a", "intent": "x", "prompt": "p {{ source.t }}"},
                {
                    "name": "b",
                    "intent": "y",
                    "dependencies": ["a"],
                    "prompt": "q {{ a.f }}",
                    "context_scope": {"observe": ["a.f"], "drop": ["a.secret"]},
                },
            ],
        }
        parsed = _parse(tmp_path, workflow)

        scope = _action(parsed, "b").get("context_scope") or {}
        assert scope.get("observe") == ["a.f"], scope
        assert scope.get("drop") == ["a.secret"], scope

    def test_a_workflow_with_no_context_scope_anywhere_reports_none(self, tmp_path):
        workflow = {
            "name": "bare",
            "description": "nothing to report",
            "actions": [{"name": "a", "intent": "x", "prompt": "p"}],
        }
        parsed = _parse(tmp_path, workflow)

        scope = _action(parsed, "a").get("context_scope")
        assert not scope, scope


class TestAVersionBaseReferenceIsExpanded:
    """`normalize_context_scope` rewrites a ref naming a version base into one per variant.

    The runtime never sees `voter.score`; it sees `voter_1.score`, `voter_2.score`. Reading the
    raw YAML, the panel names a namespace that exists at runtime under no action.
    """

    def test_a_drop_naming_a_version_base_is_reported_per_variant(self, tmp_path):
        workflow = {
            "name": "versioned",
            "description": "a versioned producer and a consumer that drops one of its fields",
            "actions": [
                {
                    "name": "voter",
                    "intent": "vote",
                    "prompt": "vote on {{ source.text }}",
                    "versions": {"param": "voter_id", "range": [1, 2, 3]},
                },
                {
                    "name": "tally",
                    "intent": "count",
                    "dependencies": ["voter"],
                    "prompt": "count {{ voter.verdict }}",
                    "context_scope": {"observe": ["voter.verdict"], "drop": ["voter.score"]},
                },
            ],
        }
        parsed = _parse(tmp_path, workflow)

        drops = (_action(parsed, "tally").get("context_scope") or {}).get("drop") or []
        assert sorted(drops) == ["voter_1.score", "voter_2.score", "voter_3.score"], drops

    def test_a_non_versioned_reference_is_left_alone(self, tmp_path):
        """The expansion must not rewrite a name that is already a real action."""
        parsed = _parse(tmp_path, _INHERITED)

        drops = (_action(parsed, "upstream").get("context_scope") or {}).get("drop") or []
        assert drops == ["upstream.secret"], drops
