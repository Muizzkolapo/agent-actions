"""`observe: [up.*]` enumerates the fields it brings in.

It recorded only the source name, so the fields never reached `available_outputs` and a
`drop` aimed at one had no entry to mark — `dropped_outputs` came back empty while the run
withheld the field. Spelling the same observe out explicitly made both work, which is the
asymmetry this closes.

The wildcard cannot always be expanded: an upstream that is schemaless or template-based
has no field list. Those expand to nothing and keep the source name recorded, so a reader
can tell "brings in nothing" from "brings in something unlistable".
"""

from agent_actions.workflow.schema_service import WorkflowSchemaService


def _schema(observe: list[str], drop: list[str] | None = None, upstream: dict | None = None):
    configs = {
        "upstream": {
            "name": "upstream",
            "kind": "llm",
            "intent": "x",
            **(
                upstream
                or {"schema": {"headline": {"type": "string"}, "secret": {"type": "string"}}}
            ),
        },
        "consume": {
            "name": "consume",
            "kind": "llm",
            "intent": "y",
            "dependencies": ["upstream"],
            "schema": {"verdict": {"type": "string"}},
            "context_scope": {"observe": observe, **({"drop": drop} if drop else {})},
        },
    }
    return WorkflowSchemaService.from_action_configs("p", configs).get_action_schema("consume")


class TestTheFieldsAWildcardBringsInAreReported:
    def test_a_wildcard_observe_enumerates_the_upstream_fields(self):
        assert _schema(["upstream.*"]).available_outputs == ["headline", "secret", "verdict"]

    def test_it_matches_spelling_the_same_observe_out(self):
        """The asymmetry the issue reports: the two spellings must agree."""
        wildcard = _schema(["upstream.*"], drop=["upstream.secret"])
        explicit = _schema(["upstream.headline", "upstream.secret"], drop=["upstream.secret"])

        assert wildcard.available_outputs == explicit.available_outputs
        assert wildcard.dropped_outputs == explicit.dropped_outputs

    def test_a_drop_on_a_wildcard_observed_field_is_named(self):
        """Was empty: nothing put `secret` in the outputs, so the drop had nothing to mark."""
        schema = _schema(["upstream.*"], drop=["upstream.secret"])

        assert schema.dropped_outputs == ["secret"], schema.dropped_outputs
        assert "secret" not in schema.available_outputs

    def test_the_action_s_own_fields_survive_a_namespaced_drop_of_the_same_name(self):
        """`upstream.verdict` and the action's own `verdict` are different claims."""
        schema = _schema(["upstream.*"], drop=["upstream.verdict"])

        assert "verdict" in schema.available_outputs


class TestAnUpstreamWithNoFieldListExpandsToNothing:
    def test_a_schemaless_upstream_adds_no_fields(self):
        """Built directly: a config-level schemaless upstream has no schema_fields either
        way, so it cannot tell whether the guard is doing anything."""
        from agent_actions.validation.static_analyzer.data_flow_graph import OutputSchema
        from agent_actions.workflow.schema_service import WorkflowSchemaService

        service = WorkflowSchemaService.from_action_configs(
            "p",
            {
                "upstream": {
                    "name": "upstream",
                    "kind": "llm",
                    "intent": "x",
                    "schema": {"headline": {"type": "string"}},
                },
                "consume": {
                    "name": "consume",
                    "kind": "llm",
                    "intent": "y",
                    "dependencies": ["upstream"],
                    "schema": {"verdict": {"type": "string"}},
                    "context_scope": {"observe": ["upstream.*"]},
                },
            },
        )
        upstream_output = service.graph.nodes["upstream"].output_schema
        observing = OutputSchema(observe_wildcard_sources={"upstream"})

        assert service._wildcard_observe_refs(observing) == {("upstream", "headline")}

        upstream_output.is_schemaless = True
        assert service._wildcard_observe_refs(observing) == set(), (
            "a schemaless upstream lists nothing"
        )

        upstream_output.is_schemaless = False
        upstream_output.is_dynamic = True
        assert service._wildcard_observe_refs(observing) == set(), (
            "a dynamic upstream lists nothing"
        )

    def test_an_unknown_upstream_adds_no_fields(self):
        """Naming a namespace no action declares must not invent fields for it."""
        assert _schema(["nosuch.*"]).available_outputs == ["verdict"]


def _two_suppliers(drop: list[str]):
    """Two upstreams both supplying `score`, so a drop on one leaves the other forwarding it."""
    configs = {
        "a": {
            "name": "a",
            "kind": "llm",
            "intent": "x",
            "schema": {"score": {"type": "string"}},
        },
        "b": {
            "name": "b",
            "kind": "llm",
            "intent": "x",
            "schema": {"score": {"type": "string"}},
        },
        "consume": {
            "name": "consume",
            "kind": "llm",
            "intent": "y",
            "dependencies": ["a", "b"],
            "schema": {"verdict": {"type": "string"}},
            "context_scope": {"observe": ["a.score", "b.score"], "drop": drop},
        },
    }
    return WorkflowSchemaService.from_action_configs("p", configs).get_action_schema("consume")


class TestAFieldTwoNamespacesSupply:
    """`drops_field` documents the rule: a forwarded field is dropped "only when *every*
    namespace supplying that name drops it". The observe loop keeps one entry per bare name
    and took `is_dropped` from whichever `(namespace, field)` pair sorted first, so the
    answer depended on sort order — and the passthrough loop three lines below still called
    `drops_field`, so the two disagreed inside one function.

    Measured before the fix: `drop: [a.score]` reported `score` dropped and withheld it,
    `drop: [b.score]` reported it available. Same shape, opposite verdict.
    """

    def test_dropping_one_supplier_does_not_report_the_name_dropped(self):
        """`b.score` still forwards `score`. `a` sorts first, which is why this is the
        direction that failed."""
        schema = _two_suppliers(drop=["a.score"])

        assert schema.dropped_outputs == [], schema.dropped_outputs

    def test_dropping_one_supplier_keeps_it_available(self):
        schema = _two_suppliers(drop=["a.score"])

        assert "score" in schema.available_outputs, sorted(schema.available_outputs)

    def test_the_verdict_does_not_depend_on_which_supplier_is_dropped(self):
        """The asymmetry itself, asserted directly rather than inferred from one side."""
        dropping_a = _two_suppliers(drop=["a.score"])
        dropping_b = _two_suppliers(drop=["b.score"])

        assert dropping_a.dropped_outputs == dropping_b.dropped_outputs
        assert sorted(dropping_a.available_outputs) == sorted(dropping_b.available_outputs)

    def test_dropping_every_supplier_does_report_it_dropped(self):
        """The edge the rule exists for: with nothing forwarding it, it is gone."""
        schema = _two_suppliers(drop=["a.score", "b.score"])

        assert schema.dropped_outputs == ["score"], schema.dropped_outputs
        assert "score" not in schema.available_outputs
