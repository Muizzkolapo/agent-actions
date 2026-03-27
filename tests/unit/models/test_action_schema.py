"""Tests for ActionSchema, FieldInfo, ActionKind, FieldSource, UpstreamReference."""

from agent_actions.models.action_schema import (
    ActionKind,
    ActionSchema,
    FieldInfo,
    FieldSource,
    UpstreamReference,
)

# ---------------------------------------------------------------------------
# ActionKind enum
# ---------------------------------------------------------------------------


class TestActionKind:
    """ActionKind enum has exactly 4 members with expected string values."""

    def test_llm_value(self):
        assert ActionKind.LLM.value == "llm"

    def test_tool_value(self):
        assert ActionKind.TOOL.value == "tool"

    def test_source_value(self):
        assert ActionKind.SOURCE.value == "source"

    def test_hitl_value(self):
        assert ActionKind.HITL.value == "hitl"

    def test_seed_value(self):
        assert ActionKind.SEED.value == "seed"

    def test_member_count(self):
        assert len(ActionKind) == 5

    def test_construct_from_value(self):
        assert ActionKind("llm") is ActionKind.LLM

    def test_case_insensitive_lookup(self):
        assert ActionKind("LLM") is ActionKind.LLM
        assert ActionKind("Tool") is ActionKind.TOOL

    def test_is_str_enum(self):
        assert isinstance(ActionKind.LLM, str)
        assert ActionKind.LLM == "llm"

    def test_members_are_unique(self):
        values = [m.value for m in ActionKind]
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# FieldSource enum
# ---------------------------------------------------------------------------


class TestFieldSource:
    """FieldSource enum has exactly 4 members with expected string values."""

    def test_schema_value(self):
        assert FieldSource.SCHEMA.value == "schema"

    def test_observe_value(self):
        assert FieldSource.OBSERVE.value == "observe"

    def test_passthrough_value(self):
        assert FieldSource.PASSTHROUGH.value == "passthrough"

    def test_tool_output_value(self):
        assert FieldSource.TOOL_OUTPUT.value == "tool_output"

    def test_member_count(self):
        assert len(FieldSource) == 4

    def test_construct_from_value(self):
        assert FieldSource("observe") is FieldSource.OBSERVE


# ---------------------------------------------------------------------------
# FieldInfo dataclass
# ---------------------------------------------------------------------------


class TestFieldInfo:
    """FieldInfo creation, defaults, and serialization."""

    def test_defaults(self):
        f = FieldInfo(name="x", source=FieldSource.SCHEMA)
        assert f.is_required is True
        assert f.is_dropped is False

    def test_explicit_optional(self):
        f = FieldInfo(name="y", source=FieldSource.OBSERVE, is_required=False)
        assert f.is_required is False

    def test_explicit_dropped(self):
        f = FieldInfo(name="z", source=FieldSource.PASSTHROUGH, is_dropped=True)
        assert f.is_dropped is True

    def test_to_dict_schema_source(self):
        f = FieldInfo(name="a", source=FieldSource.SCHEMA)
        d = f.to_dict()
        assert d == {
            "name": "a",
            "source": "schema",
            "is_required": True,
            "is_dropped": False,
            "type": "unknown",
            "description": "",
        }

    def test_to_dict_with_type_and_description(self):
        f = FieldInfo(
            name="age",
            source=FieldSource.SCHEMA,
            field_type="integer",
            description="User age",
        )
        d = f.to_dict()
        assert d["type"] == "integer"
        assert d["description"] == "User age"

    def test_to_dict_tool_output_source(self):
        f = FieldInfo(
            name="b",
            source=FieldSource.TOOL_OUTPUT,
            is_required=False,
            is_dropped=True,
        )
        d = f.to_dict()
        assert d == {
            "name": "b",
            "source": "tool_output",
            "is_required": False,
            "is_dropped": True,
            "type": "unknown",
            "description": "",
        }

    def test_all_field_sources_serialize(self):
        """Every FieldSource member produces a valid to_dict result."""
        for src in FieldSource:
            f = FieldInfo(name="test", source=src)
            d = f.to_dict()
            assert d["source"] == src.value

    def test_equality(self):
        a = FieldInfo(name="x", source=FieldSource.SCHEMA)
        b = FieldInfo(name="x", source=FieldSource.SCHEMA)
        assert a == b

    def test_inequality_different_name(self):
        a = FieldInfo(name="x", source=FieldSource.SCHEMA)
        b = FieldInfo(name="y", source=FieldSource.SCHEMA)
        assert a != b


# ---------------------------------------------------------------------------
# UpstreamReference dataclass
# ---------------------------------------------------------------------------


class TestUpstreamReference:
    """UpstreamReference creation and serialization."""

    def test_construction(self):
        ref = UpstreamReference(
            source_agent="agent_a",
            field_name="output_1",
            location="prompt",
            raw_reference="{{agent_a.output_1}}",
        )
        assert ref.source_agent == "agent_a"
        assert ref.field_name == "output_1"
        assert ref.location == "prompt"
        assert ref.raw_reference == "{{agent_a.output_1}}"

    def test_to_dict(self):
        ref = UpstreamReference(
            source_agent="src",
            field_name="fld",
            location="loc",
            raw_reference="raw",
        )
        assert ref.to_dict() == {
            "source_agent": "src",
            "field_name": "fld",
            "location": "loc",
            "raw_reference": "raw",
        }

    def test_equality(self):
        args = dict(
            source_agent="a",
            field_name="f",
            location="l",
            raw_reference="r",
        )
        assert UpstreamReference(**args) == UpstreamReference(**args)

    def test_inequality(self):
        base = dict(
            source_agent="a",
            field_name="f",
            location="l",
            raw_reference="r",
        )
        altered = {**base, "source_agent": "b"}
        assert UpstreamReference(**base) != UpstreamReference(**altered)


# ---------------------------------------------------------------------------
# ActionSchema dataclass — construction and defaults
# ---------------------------------------------------------------------------


class TestActionSchemaConstruction:
    """ActionSchema defaults and basic construction."""

    def test_minimal_construction(self):
        s = ActionSchema(name="act", kind=ActionKind.LLM)
        assert s.name == "act"
        assert s.kind is ActionKind.LLM
        assert s.upstream_refs == []
        assert s.input_fields == []
        assert s.output_fields == []
        assert s.dependencies == []
        assert s.downstream == []
        assert s.is_dynamic is False
        assert s.is_schemaless is False
        assert s.is_template_based is False

    def test_all_kinds_accepted(self):
        for kind in ActionKind:
            s = ActionSchema(name="x", kind=kind)
            assert s.kind is kind

    def test_with_dependencies_and_downstream(self):
        s = ActionSchema(
            name="mid",
            kind=ActionKind.TOOL,
            dependencies=["a", "b"],
            downstream=["c"],
        )
        assert s.dependencies == ["a", "b"]
        assert s.downstream == ["c"]

    def test_boolean_flags(self):
        s = ActionSchema(
            name="dyn",
            kind=ActionKind.SOURCE,
            is_dynamic=True,
            is_schemaless=True,
            is_template_based=True,
        )
        assert s.is_dynamic is True
        assert s.is_schemaless is True
        assert s.is_template_based is True


# ---------------------------------------------------------------------------
# ActionSchema computed properties
# ---------------------------------------------------------------------------


class TestActionSchemaProperties:
    """Tests for the computed property accessors."""

    def _make_schema(self):
        return ActionSchema(
            name="test",
            kind=ActionKind.TOOL,
            input_fields=[
                FieldInfo(name="req1", source=FieldSource.SCHEMA, is_required=True),
                FieldInfo(name="req2", source=FieldSource.SCHEMA, is_required=True),
                FieldInfo(name="opt1", source=FieldSource.OBSERVE, is_required=False),
            ],
            output_fields=[
                FieldInfo(name="out_a", source=FieldSource.TOOL_OUTPUT),
                FieldInfo(name="out_b", source=FieldSource.TOOL_OUTPUT),
                FieldInfo(
                    name="dropped",
                    source=FieldSource.TOOL_OUTPUT,
                    is_dropped=True,
                ),
            ],
            upstream_refs=[
                UpstreamReference(
                    source_agent="src1",
                    field_name="f1",
                    location="prompt",
                    raw_reference="{{src1.f1}}",
                ),
                UpstreamReference(
                    source_agent="src2",
                    field_name="f2",
                    location="prompt",
                    raw_reference="{{src2.f2}}",
                ),
            ],
        )

    def test_available_outputs_excludes_dropped(self):
        s = self._make_schema()
        assert s.available_outputs == ["out_a", "out_b"]

    def test_dropped_outputs(self):
        s = self._make_schema()
        assert s.dropped_outputs == ["dropped"]

    def test_required_inputs(self):
        s = self._make_schema()
        assert s.required_inputs == ["req1", "req2"]

    def test_optional_inputs(self):
        s = self._make_schema()
        assert s.optional_inputs == ["opt1"]

    def test_uses_fields(self):
        s = self._make_schema()
        assert s.uses_fields == ["src1.f1", "src2.f2"]

    def test_available_outputs_sorted(self):
        s = ActionSchema(
            name="s",
            kind=ActionKind.LLM,
            output_fields=[
                FieldInfo(name="z", source=FieldSource.SCHEMA),
                FieldInfo(name="a", source=FieldSource.SCHEMA),
            ],
        )
        assert s.available_outputs == ["a", "z"]

    def test_uses_fields_deduplicates(self):
        """Duplicate upstream references to the same agent.field are collapsed."""
        s = ActionSchema(
            name="s",
            kind=ActionKind.LLM,
            upstream_refs=[
                UpstreamReference(
                    source_agent="x",
                    field_name="y",
                    location="a",
                    raw_reference="r1",
                ),
                UpstreamReference(
                    source_agent="x",
                    field_name="y",
                    location="b",
                    raw_reference="r2",
                ),
            ],
        )
        assert s.uses_fields == ["x.y"]


# ---------------------------------------------------------------------------
# ActionSchema — empty / edge cases
# ---------------------------------------------------------------------------


class TestActionSchemaEdgeCases:
    """Edge cases: empty fields, no outputs, etc."""

    def test_empty_outputs(self):
        s = ActionSchema(name="e", kind=ActionKind.HITL)
        assert s.available_outputs == []
        assert s.dropped_outputs == []

    def test_empty_inputs(self):
        s = ActionSchema(name="e", kind=ActionKind.HITL)
        assert s.required_inputs == []
        assert s.optional_inputs == []

    def test_empty_upstream_refs(self):
        s = ActionSchema(name="e", kind=ActionKind.HITL)
        assert s.uses_fields == []

    def test_all_outputs_dropped(self):
        s = ActionSchema(
            name="e",
            kind=ActionKind.LLM,
            output_fields=[
                FieldInfo(name="x", source=FieldSource.SCHEMA, is_dropped=True),
                FieldInfo(name="y", source=FieldSource.SCHEMA, is_dropped=True),
            ],
        )
        assert s.available_outputs == []
        assert s.dropped_outputs == ["x", "y"]

    def test_all_inputs_optional(self):
        s = ActionSchema(
            name="e",
            kind=ActionKind.SOURCE,
            input_fields=[
                FieldInfo(name="a", source=FieldSource.SCHEMA, is_required=False),
                FieldInfo(name="b", source=FieldSource.OBSERVE, is_required=False),
            ],
        )
        assert s.required_inputs == []
        assert s.optional_inputs == ["a", "b"]


# ---------------------------------------------------------------------------
# ActionSchema.to_dict serialization
# ---------------------------------------------------------------------------


class TestActionSchemaToDict:
    """Full round-trip serialization via to_dict."""

    def test_minimal_to_dict(self):
        s = ActionSchema(name="min", kind=ActionKind.SOURCE)
        d = s.to_dict()
        assert d["name"] == "min"
        assert d["kind"] == "source"
        assert d["upstream_refs"] == []
        assert d["input_fields"] == []
        assert d["output_fields"] == []
        assert d["dependencies"] == []
        assert d["downstream"] == []
        assert d["is_dynamic"] is False
        assert d["is_schemaless"] is False
        assert d["is_template_based"] is False
        assert d["available_outputs"] == []
        assert d["dropped_outputs"] == []
        assert d["required_inputs"] == []
        assert d["optional_inputs"] == []
        assert d["uses_fields"] == []

    def test_full_to_dict(self):
        s = ActionSchema(
            name="full",
            kind=ActionKind.TOOL,
            upstream_refs=[
                UpstreamReference(
                    source_agent="a",
                    field_name="f",
                    location="l",
                    raw_reference="r",
                ),
            ],
            input_fields=[
                FieldInfo(name="in1", source=FieldSource.SCHEMA, is_required=True),
                FieldInfo(name="in2", source=FieldSource.OBSERVE, is_required=False),
            ],
            output_fields=[
                FieldInfo(name="out1", source=FieldSource.TOOL_OUTPUT),
                FieldInfo(
                    name="out2",
                    source=FieldSource.PASSTHROUGH,
                    is_dropped=True,
                ),
            ],
            dependencies=["dep1"],
            downstream=["ds1", "ds2"],
            is_dynamic=True,
            is_schemaless=False,
            is_template_based=True,
        )
        d = s.to_dict()
        assert d["name"] == "full"
        assert d["kind"] == "tool"
        assert d["is_dynamic"] is True
        assert d["is_template_based"] is True
        assert d["dependencies"] == ["dep1"]
        assert d["downstream"] == ["ds1", "ds2"]
        # Computed properties included in serialization
        assert d["available_outputs"] == ["out1"]
        assert d["dropped_outputs"] == ["out2"]
        assert d["required_inputs"] == ["in1"]
        assert d["optional_inputs"] == ["in2"]
        assert d["uses_fields"] == ["a.f"]
        # Nested dicts
        assert len(d["upstream_refs"]) == 1
        assert d["upstream_refs"][0]["source_agent"] == "a"
        assert len(d["input_fields"]) == 2
        assert len(d["output_fields"]) == 2

    def test_to_dict_returns_new_dict_each_call(self):
        s = ActionSchema(name="x", kind=ActionKind.LLM)
        d1 = s.to_dict()
        d2 = s.to_dict()
        assert d1 == d2
        assert d1 is not d2

    def test_to_dict_kind_is_string(self):
        """kind is serialized as its string value, not the enum object."""
        for kind in ActionKind:
            s = ActionSchema(name="k", kind=kind)
            assert isinstance(s.to_dict()["kind"], str)
            assert s.to_dict()["kind"] == kind.value
