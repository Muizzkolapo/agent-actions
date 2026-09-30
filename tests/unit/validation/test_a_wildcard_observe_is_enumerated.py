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
