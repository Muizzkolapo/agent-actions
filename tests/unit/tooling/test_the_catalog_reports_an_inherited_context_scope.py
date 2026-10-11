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

    def test_the_graph_keeps_every_upstream_the_scope_names(self, tmp_path):
        """Inference is checked against the EXPANDED names, or it raises and edges vanish.

        The scope handed to infer_dependencies is already normalised to `voter_1`,
        `voter_2`. Checking it against a name list built from the raw actions, where only
        `voter` exists, makes inference raise on every variant; the parser then falls back
        to explicit dependencies and the catalog silently loses the rest. Measured before
        this was fixed: 13 fallbacks across the shipped workflows, four actions short of
        upstreams their own context_scope names.
        """
        workflow = {
            "name": "versioned",
            "description": "a fan-in that also observes a plain upstream and the source",
            "actions": [
                {"name": "prep", "intent": "prep", "prompt": "prep {{ source.text }}"},
                {
                    "name": "voter",
                    "intent": "vote",
                    "prompt": "vote on {{ source.text }}",
                    "versions": {"param": "voter_id", "range": [1, 2]},
                },
                {
                    "name": "tally",
                    "intent": "count",
                    "dependencies": ["voter"],
                    "prompt": "count {{ voter.verdict }}",
                    "context_scope": {"observe": ["voter.verdict", "prep.note", "source.text"]},
                },
            ],
        }
        parsed = _parse(tmp_path, workflow)
        deps = _action(parsed, "tally").get("dependencies") or []

        assert "prep" in deps, f"a plain upstream the scope names went missing: {deps}"
        assert "source" in deps, f"the source edge went missing: {deps}"
        assert "voter_1" in deps and "voter_2" in deps, deps
        assert "voter" not in deps, f"the base is never a runtime namespace: {deps}"
        assert len(deps) == len(set(deps)), f"the catalog must not print an edge twice: {deps}"

    def test_an_upstream_named_only_by_defaults_is_still_an_edge(self, tmp_path):
        """Inference must see the MERGED scope, not the action's own block.

        This is the half the post-expansion pass cannot reproduce: expanding version bases
        afterwards recovers a variant edge, but an upstream the action never names itself --
        it inherits the reference from `defaults.context_scope` -- is simply absent from the
        graph if inference was handed the raw block.
        """
        workflow = {
            "name": "inherited-edge",
            "description": "the only reference to `prep` lives in defaults",
            "defaults": {"context_scope": {"observe": ["prep.note"]}},
            "actions": [
                {"name": "prep", "intent": "prep", "prompt": "prep {{ source.text }}"},
                {
                    "name": "tally",
                    "intent": "count",
                    "prompt": "count it",
                    "context_scope": {"observe": ["source.text"]},
                },
            ],
        }
        parsed = _parse(tmp_path, workflow)
        deps = _action(parsed, "tally").get("dependencies") or []

        assert "prep" in deps, (
            f"`prep` is named only by defaults.context_scope; inferring from the raw "
            f"action block loses the edge entirely: {deps}"
        )

    def test_a_non_versioned_reference_is_left_alone(self, tmp_path):
        """The expansion must not rewrite a name that is already a real action."""
        parsed = _parse(tmp_path, _INHERITED)

        drops = (_action(parsed, "upstream").get("context_scope") or {}).get("drop") or []
        assert drops == ["upstream.secret"], drops


class TestADirectiveTheNormaliserRejectsDoesNotFailTheBuild:
    """A retired directive is the loader's error to raise on a run, not the catalog's.

    `artefact/rendered_workflows/` is read when a project has run before, and a rendered
    file can carry a spelling the normaliser no longer accepts (`seed_path` in the sample
    project). Routing the merged block through `normalize_context_scope` without this guard
    turned a working `agac docs` into an uncaught ConfigurationError.
    """

    def test_a_workflow_with_a_retired_directive_still_parses(self, tmp_path):
        workflow = {
            "name": "retired_directive",
            "description": "defaults carry a directive the normaliser refuses",
            "defaults": {
                "model_vendor": "anthropic",
                "model_name": "claude-3",
                "context_scope": {"seed_path": {"rubric": "$file:rubric.json"}},
            },
            "actions": [{"name": "solo", "intent": "x", "prompt": "p {{ source.t }}"}],
        }
        parsed = _parse(tmp_path, workflow)

        scope = _action(parsed, "solo").get("context_scope") or {}
        assert scope == {"seed_path": {"rubric": "$file:rubric.json"}}, scope

    def test_a_valid_directive_beside_a_retired_one_survives(self, tmp_path):
        workflow = {
            "name": "mixed",
            "description": "one directive the normaliser knows, one it does not",
            "defaults": {
                "model_vendor": "anthropic",
                "model_name": "claude-3",
                "context_scope": {
                    "seed_path": {"rubric": "$file:rubric.json"},
                    "drop": ["upstream.secret"],
                },
            },
            "actions": [{"name": "solo", "intent": "x", "prompt": "p {{ source.t }}"}],
        }
        parsed = _parse(tmp_path, workflow)

        scope = _action(parsed, "solo").get("context_scope") or {}
        assert scope.get("drop") == ["upstream.secret"], scope


class TestTheRenderedShapeIsWhatRealProjectsHave:
    """`scan_workflows` prefers `artefact/rendered_workflows/` once a project has run.

    `render_workflow` expands versions at render time and strips the `versions:` key, leaving
    the base name in `_version_context`. A map built only from `versions:` is therefore empty
    for every project that has ever run -- which is the shape all 37 workflows in the sample
    project have, and the one the first version of this fix silently did nothing for.
    """

    def _rendered(self) -> dict:
        return {
            "name": "rendered_shape",
            "description": "expanded at render time, no versions: key",
            "defaults": {
                "model_vendor": "anthropic",
                "model_name": "claude-3",
                "context_scope": {"drop": ["upstream.secret"]},
            },
            "actions": [
                {"name": "upstream", "intent": "p", "prompt": "m {{ source.text }}"},
                *(
                    {
                        "name": f"voter_{i}",
                        "intent": "v",
                        "prompt": "v {{ upstream.headline }}",
                        "dependencies": ["upstream"],
                        "_version_context": {
                            "i": i,
                            "idx": i - 1,
                            "length": 3,
                            "base_name": "voter",
                            "param_name": "voter_id",
                        },
                    }
                    for i in (1, 2, 3)
                ),
                {
                    "name": "tally",
                    "intent": "c",
                    "dependencies": ["voter_1", "voter_2", "voter_3"],
                    "prompt": "q {{ voter.verdict }}",
                    "context_scope": {"observe": ["voter.verdict"], "drop": ["voter.score"]},
                },
            ],
        }

    def test_a_version_base_ref_expands_without_a_versions_key(self, tmp_path):
        parsed = _parse(tmp_path, self._rendered())

        drops = (_action(parsed, "tally").get("context_scope") or {}).get("drop") or []
        assert sorted(drops) == [
            "upstream.secret",
            "voter_1.score",
            "voter_2.score",
            "voter_3.score",
        ], drops

    def test_a_retired_directive_does_not_suppress_expansion(self, tmp_path):
        """Per directive, not per block: qana_quiz carries `seed_path` and versioned actions,
        and normalising nothing when one key is unknown lost expansion for the whole file."""
        workflow = self._rendered()
        workflow["defaults"]["context_scope"] = {
            "drop": ["upstream.secret"],
            "seed_path": {"rubric": "$file:rubric.json"},
        }
        parsed = _parse(tmp_path, workflow)

        scope = _action(parsed, "tally").get("context_scope") or {}
        assert "voter_1.score" in (scope.get("drop") or []), scope
        assert scope.get("seed_path") == {"rubric": "$file:rubric.json"}, scope
