"""A `context_scope.drop` filters what an action forwards, not what it produces.

The declaring action's own namespace does not exist when drop runs, so a drop can never
remove a field the action produces. The analyzer discarded the namespace when recording
drops, so a drop aimed at an upstream field removed a same-named field from the
declaring action's own output — the shape every real `drop:` in `examples/` uses.
"""

from __future__ import annotations

from agent_actions.validation.static_analyzer.data_flow_graph import OutputSchema
from agent_actions.validation.static_analyzer.workflow_static_analyzer import analyze_workflow
from agent_actions.workflow.schema_service import WorkflowSchemaService

# `grade` drops the upstream score to avoid anchoring bias — the documented pattern,
# and the one `examples/review_analyzer` uses (`drop: [normalize_review.star_rating]`).
# `grade` also emits a field of its own called `score`.
ACTION_CONFIGS = {
    "first_pass": {
        "prompt": "rate {{ source.text }}",
        "context_scope": {"observe": ["source.text"]},
        "schema": {"score": "integer"},
    },
    "grade": {
        "prompt": "grade {{ source.text }} independently",
        "dependencies": ["first_pass"],
        "context_scope": {"observe": ["source.text"], "drop": ["first_pass.score"]},
        "schema": {"score": "integer", "note": "string"},
    },
    "report": {
        "prompt": "verdict {{ grade.score }} because {{ grade.note }}",
        "dependencies": ["grade"],
        "context_scope": {"observe": ["grade.score", "grade.note"]},
        "schema": {"final": "string"},
    },
}


def _as_workflow(action_configs: dict[str, dict]) -> dict:
    return {
        "name": "dropscope",
        "actions": [{"name": name, **cfg} for name, cfg in action_configs.items()],
    }


class TestDropLeavesTheProducersOwnFieldAlone:
    def test_validate_accepts_a_downstream_read_of_the_declaring_actions_own_field(self):
        """`report` reads `grade.score`, which `grade` produces. No error."""
        result = analyze_workflow(_as_workflow(ACTION_CONFIGS))

        messages = [getattr(e, "message", str(e)) for e in result.errors]
        assert messages == [], messages

    def test_the_dropped_upstream_field_is_still_readable_from_its_producer(self):
        """`first_pass.score` stays on the bus — a later action may observe it."""
        configs = {name: dict(cfg) for name, cfg in ACTION_CONFIGS.items()}
        configs["report"] = {
            **configs["report"],
            "prompt": "verdict {{ grade.note }} first {{ first_pass.score }}",
            "context_scope": {"observe": ["grade.note", "first_pass.score"]},
        }

        result = analyze_workflow(_as_workflow(configs))

        messages = [getattr(e, "message", str(e)) for e in result.errors]
        assert messages == [], messages

    def test_the_action_schema_does_not_mark_its_own_output_field_dropped(self):
        """The docs catalog and preflight read `is_dropped` off this."""
        service = WorkflowSchemaService.from_action_configs("dropscope", ACTION_CONFIGS)

        schema = service.get_action_schema("grade")
        assert schema is not None
        dropped = sorted(f.name for f in schema.output_fields if f.is_dropped)
        assert dropped == [], dropped
        assert "score" in schema.available_outputs, schema.available_outputs


class TestADropOnlyBindsTheNamespaceItNames:
    """The other two collisions the bare-name set produced.

    `apply_context_scope` pops `passthrough_fields[ns][field]`, so a drop naming one
    namespace leaves a same-named field forwarded from another alone, and a ref
    `parse_field_reference` rejects is logged "Field will NOT be removed" and skipped.
    """

    def test_a_sibling_namespace_still_forwards_a_field_of_the_dropped_name(self):
        configs = {
            "left": {
                "prompt": "l",
                "context_scope": {"observe": ["source.t"]},
                "schema": {"score": "integer"},
            },
            "right": {
                "prompt": "r",
                "context_scope": {"observe": ["source.t"]},
                "schema": {"score": "integer"},
            },
            "carry": {
                "prompt": "c {{ left.score }}",
                "dependencies": ["left", "right"],
                # Hide RIGHT's score from this prompt; LEFT's is still forwarded.
                "context_scope": {
                    "observe": ["left.score"],
                    "passthrough": ["left.score"],
                    "drop": ["right.score"],
                },
                "schema": {"note": "string"},
            },
            "report": {
                "prompt": "{{ carry.score }}",
                "dependencies": ["carry"],
                "context_scope": {"observe": ["carry.score"]},
                "schema": {"final": "string"},
            },
        }
        result = analyze_workflow(_as_workflow(configs))

        messages = [getattr(e, "message", str(e)) for e in result.errors]
        assert messages == [], messages

    def test_a_drop_the_runtime_refuses_withholds_nothing(self):
        """`drop: [verdict]` has no namespace; the runtime logs it and forwards on."""
        configs = {
            "up": {
                "prompt": "u",
                "context_scope": {"observe": ["source.t"]},
                "schema": {"verdict": "string"},
            },
            "carry": {
                "prompt": "c {{ up.verdict }}",
                "dependencies": ["up"],
                "context_scope": {
                    "observe": ["up.verdict"],
                    "passthrough": ["up.verdict"],
                    "drop": ["verdict"],
                },
                "schema": {"note": "string"},
            },
            "report": {
                "prompt": "{{ carry.verdict }}",
                "dependencies": ["carry"],
                "context_scope": {"observe": ["carry.verdict"]},
                "schema": {"final": "string"},
            },
        }
        result = analyze_workflow(_as_workflow(configs))

        messages = [getattr(e, "message", str(e)) for e in result.errors]
        assert messages == [], messages

    def test_a_schemaless_action_still_gets_the_namespace_rule(self):
        """The invariant must not rest on schema_fields, which a tool leaves empty."""
        schema = OutputSchema(
            passthrough_refs={("source", "score")},
            dropped_refs={("up", "score")},
            is_schemaless=True,
        )
        assert schema.available_fields == {"score"}
        assert not schema.drops_field("score")


class TestDropStillRemovesWhatItForwards:
    """Pins the half that must NOT change: drop beats passthrough.

    `apply_context_scope` removes a dropped ref from `passthrough_fields`
    (prompt/ARCHITECTURE.md: passthrough is extracted pre-drop, then drop is applied
    to both). Without these, deleting the subtraction outright would pass.
    """

    def test_a_passthrough_field_that_is_also_dropped_is_not_available(self):
        schema = OutputSchema(
            schema_fields={"verdict"},
            passthrough_refs={("up", "customer_id")},
            dropped_refs={("up", "customer_id")},
        )
        assert schema.available_fields == {"verdict"}
        assert not schema.has_field("customer_id")
        assert schema.drops_field("customer_id")

    def test_an_observed_field_that_is_also_dropped_is_not_available(self):
        schema = OutputSchema(
            schema_fields={"verdict"},
            observe_refs={("up", "prior_score")},
            dropped_refs={("up", "prior_score")},
        )
        assert schema.available_fields == {"verdict"}

    def test_a_wildcard_drop_takes_every_field_forwarded_from_that_namespace(self):
        """The runtime does `del passthrough_fields[ns]` for `ns.*`."""
        schema = OutputSchema(
            passthrough_refs={("scores", "a"), ("scores", "b"), ("meta", "id")},
            dropped_refs={("scores", "*")},
        )
        assert schema.available_fields == {"id"}
        # The wildcard names no field, so a ref-equality test would miss these two and
        # the catalog would advertise a field the runtime deletes.
        assert schema.drops_field("a")
        assert schema.drops_field("b")
        assert not schema.drops_field("id")
        assert schema.dropped_fields == {"a", "b"}

    def test_a_produced_field_survives_a_drop_of_the_same_name(self):
        schema = OutputSchema(schema_fields={"score"}, dropped_refs={("up", "score")})
        assert schema.available_fields == {"score"}

    def test_a_name_the_action_still_supplies_is_never_reported_dropped(self):
        """`drops_field` must agree with `available_fields`, both ways.

        A name in both answers would put the field in `available_outputs` AND
        `dropped_outputs`, and make `_build_field_mapping` skip a real producer.
        Two shapes reach it, and only a test that reads `drops_field` directly can:
        the drop collides with a name this action produces, or with one a sibling
        namespace still supplies.
        """
        produced_and_forwarded = OutputSchema(
            schema_fields={"score"},
            passthrough_refs={("up", "score")},
            dropped_refs={("up", "score")},
        )
        assert not produced_and_forwarded.drops_field("score")
        assert produced_and_forwarded.dropped_fields == set()
        assert "score" in produced_and_forwarded.available_fields

        sibling_still_forwards = OutputSchema(
            passthrough_refs={("a", "score"), ("b", "score")},
            dropped_refs={("a", "score")},
        )
        assert not sibling_still_forwards.drops_field("score")
        assert sibling_still_forwards.dropped_fields == set()
        assert "score" in sibling_still_forwards.available_fields

    def test_a_forwarding_ref_the_runtime_refuses_is_not_modelled(self):
        """A dotless passthrough is skipped at runtime, so nothing is forwarded."""
        from agent_actions.validation.static_analyzer.schema_extractor import SchemaExtractor

        schema = SchemaExtractor().extract_schema(
            {
                "name": "carry",
                "schema": {"type": "object", "properties": {"note": {"type": "string"}}},
                "context_scope": {"passthrough": ["score"], "drop": ["score"]},
            }
        )
        assert schema.passthrough_refs == set()
        assert schema.available_fields == {"note"}

    def test_a_nested_path_is_a_real_forwarding_ref_but_not_a_real_drop(self):
        """The two directives resolve a nested path differently, so the model must too.

        `passthrough`/`observe` go through `extract_field_value`, which walks a dotted
        path. `drop` does a flat `content[ns].pop(field)`, which matches no key — the
        silent no-op filed as #1116. `examples/review_analyzer` really observes
        `seed.rubric.product_feedback_categories`, so treating both alike would drop a
        field the run delivers.
        """
        from agent_actions.validation.static_analyzer.schema_extractor import SchemaExtractor

        schema = SchemaExtractor().extract_schema(
            {
                "name": "insights",
                "schema": {"type": "object", "properties": {"note": {"type": "string"}}},
                "context_scope": {
                    "observe": ["seed.rubric.categories"],
                    "passthrough": ["up.meta.id"],
                    "drop": ["up.meta.id"],
                },
            }
        )
        assert schema.observe_refs == {("seed", "rubric.categories")}
        assert schema.passthrough_refs == {("up", "meta.id")}
        assert schema.dropped_refs == set()
        assert schema.available_fields == {"note", "rubric.categories", "meta.id"}


class TestTheCatalogAndPreflightSeeTheWithheldField:
    """The consumers a `drops_field -> False` mutant would otherwise slip past."""

    def test_a_forwarded_then_dropped_field_is_absent_from_the_action_schema(self):
        configs = {name: dict(cfg) for name, cfg in ACTION_CONFIGS.items()}
        configs["grade"] = {
            **configs["grade"],
            "context_scope": {
                "observe": ["source.text"],
                "passthrough": ["first_pass.gist"],
                "drop": ["first_pass.score", "first_pass.gist"],
            },
        }
        configs["first_pass"] = {
            **configs["first_pass"],
            "schema": {"score": "integer", "gist": "string"},
        }
        service = WorkflowSchemaService.from_action_configs("dropscope", configs)

        schema = service.get_action_schema("grade")
        assert schema is not None
        assert schema.dropped_outputs == ["gist"]
        assert "gist" not in schema.available_outputs
        assert "score" in schema.available_outputs, schema.available_outputs
