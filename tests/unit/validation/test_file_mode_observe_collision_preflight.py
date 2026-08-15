"""Preflight must flag FILE-mode observe refs whose flat keys collide.

``_check_file_tool_observe_collision`` reuses the runtime resolver so the two
can't drift — which also means it inherits the resolver's blind spots. It saw
collisions only between two explicitly named refs, so a wildcard expansion
claiming an explicit ref's name, or an observed field shadowing a namespace,
reached runtime unannounced. It was also gated on ``kind: tool``, leaving
``kind: hitl`` FILE actions — which run the identical enrichment path — with
no preflight coverage at all.
"""

from agent_actions.validation.static_analyzer.workflow_static_analyzer import (
    WorkflowStaticAnalyzer,
)

_COLLISION_MARKER = "namespace-qualified"


def _collision_warnings(workflow):
    result = WorkflowStaticAnalyzer(workflow).analyze()
    return [w for w in result.warnings if _COLLISION_MARKER in w.message]


def _llm(name, fields, depends_on=None, observe=None):
    action = {"name": name, "prompt": f"Run {name}"}
    if fields:
        action["schema"] = {
            "type": "object",
            "properties": {f: {"type": "string"} for f in fields},
        }
    if depends_on:
        action["depends_on"] = depends_on
    if observe:
        action["context_scope"] = {"observe": observe}
    return action


def _file_action(name, kind, depends_on, observe, *, granularity="file"):
    action = {
        "name": name,
        "kind": kind,
        "depends_on": depends_on,
        "context_scope": {"observe": observe},
    }
    if granularity is not None:
        action["granularity"] = granularity
    if kind == "tool":
        action["function"] = f"{name}_fn"
    return action


class TestHitlCoverage:
    """HITL FILE actions run the same enrichment path as FILE tools."""

    def test_hitl_collision_is_reported(self):
        workflow = {
            "actions": [
                _llm("review_a", ["title"]),
                _llm("review_b", ["title"]),
                _file_action(
                    "approve",
                    "hitl",
                    ["review_a", "review_b"],
                    ["review_a.title", "review_b.title"],
                ),
            ]
        }

        warnings = _collision_warnings(workflow)

        assert len(warnings) == 1
        assert "approve" in warnings[0].message

    def test_hitl_without_explicit_granularity_is_covered(self):
        """HITL defaults to FILE granularity when the key is absent."""
        workflow = {
            "actions": [
                _llm("review_a", ["title"]),
                _llm("review_b", ["title"]),
                _file_action(
                    "approve",
                    "hitl",
                    ["review_a", "review_b"],
                    ["review_a.title", "review_b.title"],
                    granularity=None,
                ),
            ]
        }

        assert len(_collision_warnings(workflow)) == 1


class TestWildcardExpansionCollision:
    """A wildcard expands to schema fields that can collide with explicit refs."""

    def test_wildcard_versus_explicit_is_reported(self):
        workflow = {
            "actions": [
                _llm("gen_a", ["code", "notes"]),
                _llm("gen_b", ["code"]),
                _file_action("merge", "tool", ["gen_a", "gen_b"], ["gen_a.*", "gen_b.code"]),
            ]
        }

        warnings = _collision_warnings(workflow)

        assert len(warnings) == 1
        assert "code" in warnings[0].message

    def test_explicit_ref_beside_a_wildcard_is_reported(self):
        """Even with disjoint schemas today, `gen_a.*` could grow a `score`, so
        the key is qualified up front and preflight says so."""
        workflow = {
            "actions": [
                _llm("gen_a", ["code", "notes"]),
                _llm("gen_b", ["score"]),
                _file_action("merge", "tool", ["gen_a", "gen_b"], ["gen_a.*", "gen_b.score"]),
            ]
        }

        warnings = _collision_warnings(workflow)

        assert len(warnings) == 1
        assert "gen_b.score" in warnings[0].message


class TestNamespaceShadowing:
    """An observed field named for an observed namespace lands qualified."""

    def test_field_shadowing_observed_namespace_is_reported(self):
        workflow = {
            "actions": [
                _llm("extract", ["classify", "title"]),
                _llm("classify", ["label"]),
                _file_action(
                    "merge",
                    "tool",
                    ["extract", "classify"],
                    ["extract.classify", "classify.label"],
                ),
            ]
        }

        warnings = _collision_warnings(workflow)

        assert len(warnings) == 1
        assert "extract.classify" in warnings[0].message

    def test_unrelated_action_sharing_a_field_name_is_silent(self):
        """`title` is not on `merge`'s bus and is not observed, so the runtime
        delivers a bare `title` — warning about a qualified key would misdirect."""
        workflow = {
            "actions": [
                _llm("extract", ["title"]),
                _llm("title", ["z"]),
                _file_action("merge", "tool", ["extract"], ["extract.title"]),
            ]
        }

        assert _collision_warnings(workflow) == []

    def test_field_shadowing_bus_namespace_is_reported(self):
        workflow = {
            "actions": [
                _llm("extract", ["source", "title"]),
                _file_action("merge", "tool", ["extract"], ["extract.source", "extract.title"]),
            ]
        }

        warnings = _collision_warnings(workflow)

        assert len(warnings) == 1
        assert "extract.source" in warnings[0].message


class TestGranularityResolution:
    def test_workflow_defaults_granularity_is_honoured(self):
        """A tool inheriting `granularity: file` from workflow defaults runs the
        same flat-key path as one declaring it inline."""
        workflow = {
            "defaults": {"granularity": "file"},
            "actions": [
                _llm("gen_a", ["code"]),
                _llm("gen_b", ["code"]),
                _file_action(
                    "merge",
                    "tool",
                    ["gen_a", "gen_b"],
                    ["gen_a.code", "gen_b.code"],
                    granularity=None,
                ),
            ],
        }

        assert len(_collision_warnings(workflow)) == 1

    def test_workflow_defaults_record_granularity_stays_silent(self):
        workflow = {
            "defaults": {"granularity": "record"},
            "actions": [
                _llm("gen_a", ["code"]),
                _llm("gen_b", ["code"]),
                _file_action(
                    "merge",
                    "tool",
                    ["gen_a", "gen_b"],
                    ["gen_a.code", "gen_b.code"],
                    granularity=None,
                ),
            ],
        }

        assert _collision_warnings(workflow) == []


class TestProductionActionShape:
    """The expander capitalizes granularity and folds defaults into each action,
    so preflight sees `granularity: "File"` and no defaults block. Comparing
    against the lowercase literal made this check dead in production."""

    def test_capitalized_granularity_from_the_expander_is_covered(self):
        workflow = {
            "actions": [
                _llm("gen_a", ["code"]),
                _llm("gen_b", ["code"]),
                {
                    "name": "merge",
                    "kind": "tool",
                    "function": "merge_fn",
                    "granularity": "File",
                    "depends_on": ["gen_a", "gen_b"],
                    "context_scope": {"observe": ["gen_a.code", "gen_b.code"]},
                },
            ]
        }

        assert len(_collision_warnings(workflow)) == 1

    def test_capitalized_record_granularity_stays_silent(self):
        workflow = {
            "actions": [
                _llm("gen_a", ["code"]),
                _llm("gen_b", ["code"]),
                {
                    "name": "merge",
                    "kind": "tool",
                    "function": "merge_fn",
                    "granularity": "Record",
                    "depends_on": ["gen_a", "gen_b"],
                    "context_scope": {"observe": ["gen_a.code", "gen_b.code"]},
                },
            ]
        }

        assert _collision_warnings(workflow) == []


class TestSchemalessNamespaces:
    def test_schemaless_wildcard_does_not_invent_a_collision(self):
        """A schemaless namespace's fields are unknown before the run, so its
        wildcard must not be expanded into a claim preflight reports."""
        workflow = {
            "actions": [
                {"name": "gen_a", "prompt": "p"},
                _llm("gen_b", ["content"]),
                _file_action("merge", "tool", ["gen_a", "gen_b"], ["gen_a.*", "gen_b.content"]),
            ]
        }

        warnings = _collision_warnings(workflow)

        assert len(warnings) == 1
        assert "gen_b.content" in warnings[0].message
        assert "gen_a." not in warnings[0].message


class TestNoFalsePositives:
    def test_distinct_field_names_are_silent(self):
        workflow = {
            "actions": [
                _llm("extract", ["text"]),
                _llm("classify", ["topic"]),
                _file_action(
                    "merge", "tool", ["extract", "classify"], ["extract.text", "classify.topic"]
                ),
            ]
        }

        assert _collision_warnings(workflow) == []

    def test_record_granularity_tool_is_silent(self):
        """RECORD mode never injects flat keys, so there is nothing to collide."""
        workflow = {
            "actions": [
                _llm("gen_a", ["code"]),
                _llm("gen_b", ["code"]),
                _file_action(
                    "merge",
                    "tool",
                    ["gen_a", "gen_b"],
                    ["gen_a.code", "gen_b.code"],
                    granularity="record",
                ),
            ]
        }

        assert _collision_warnings(workflow) == []
