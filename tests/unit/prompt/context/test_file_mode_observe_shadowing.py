"""FILE-mode flat observed keys must never destroy what already holds their name.

Each observed field is injected into a record's ``content`` as a bare top-level
key. Written blind, that key overwrites whatever already owns the name — a
sibling namespace, a framework bus namespace, or another observed field a
wildcard expanded to. The overwrite is last-writer-wins and order-dependent,
and clobbering a namespace additionally strands that namespace's own observed
fields: they resolve against a non-dict and vanish.

The enriched record is the data bus for ``kind: tool`` and ``kind: hitl`` FILE
actions, so every one of these is silent data loss on the way into a UDF.
"""

import logging

from agent_actions.prompt.context.scope_application import apply_context_scope_for_records
from agent_actions.workflow.pipeline_file_mode import extract_tool_input


def _enrich(content, observe, *, source_data=None, action_name="probe"):
    enriched, skipped = apply_context_scope_for_records(
        records=[{"source_guid": "g1", "content": content}],
        context_scope={"observe": observe},
        action_name=action_name,
        source_data=source_data,
    )
    assert not skipped, "record must enrich, not skip"
    return enriched[0]


class TestWildcardExpandedFieldCollision:
    """A wildcard expansion and an explicit ref can claim the same bare key."""

    CONTENT = {"a": {"x": "FROM_A", "y": 2}, "b": {"x": "FROM_B"}}

    def test_both_namespaces_values_survive(self):
        record = _enrich(dict(self.CONTENT), ["a.*", "b.x"])
        content = record["content"]

        assert content["a.x"] == "FROM_A"
        assert content["b.x"] == "FROM_B"
        assert content["y"] == 2
        assert "x" not in content, "a bare key can only carry one of the two values"

    def test_key_shape_is_order_independent(self):
        forward = _enrich(dict(self.CONTENT), ["a.*", "b.x"])["content"]
        reverse = _enrich(dict(self.CONTENT), ["b.x", "a.*"])["content"]

        assert forward == reverse

    def test_tool_input_delivers_both_values(self):
        cs = {"observe": ["a.*", "b.x"]}
        record = _enrich(dict(self.CONTENT), cs["observe"])

        assert extract_tool_input(record, cs) == {"a.x": "FROM_A", "y": 2, "b.x": "FROM_B"}

    def test_collision_is_announced(self, caplog):
        with caplog.at_level(logging.WARNING):
            _enrich(dict(self.CONTENT), ["a.*", "b.x"], action_name="merge")

        assert any("merge" in r.message and "x" in r.message for r in caplog.records)


class TestSiblingNamespaceShadowing:
    """An observed field whose name equals a sibling namespace must not replace it."""

    CONTENT = {"a": {"b": "CLOBBER"}, "b": {"y": "REAL_B_Y"}}

    def test_shadowed_namespace_survives(self):
        content = _enrich(dict(self.CONTENT), ["a.b", "b.y"])["content"]

        assert content["b"] == {"y": "REAL_B_Y"}
        assert content["a.b"] == "CLOBBER"

    def test_field_from_shadowed_namespace_still_injected(self):
        """``b.y`` is explicitly observed — clobbering ``b`` used to strand it."""
        content = _enrich(dict(self.CONTENT), ["a.b", "b.y"])["content"]

        assert content["y"] == "REAL_B_Y"

    def test_tool_input_carries_both_observed_fields(self):
        cs = {"observe": ["a.b", "b.y"]}
        record = _enrich(dict(self.CONTENT), cs["observe"])

        assert extract_tool_input(record, cs) == {"a.b": "CLOBBER", "y": "REAL_B_Y"}

    def test_unobserved_sibling_namespace_survives(self):
        """The enriched record carries every namespace for downstream guards,
        so an unobserved namespace is no less protected than an observed one."""
        content = _enrich({"a": {"c": "CLOBBER"}, "c": {"z": 1}}, ["a.c"])["content"]

        assert content["c"] == {"z": 1}
        assert content["a.c"] == "CLOBBER"


class TestFrameworkNamespaceShadowing:
    """Observed fields must not shadow the runtime bus namespaces."""

    SOURCE_DATA = [
        {"source_guid": "g1", "content": {"source": {"url": "http://real", "body": "REAL"}}}
    ]

    def test_source_namespace_survives(self):
        content = _enrich(
            {"extract": {"source": "CLOBBER", "title": "T"}},
            ["extract.source", "source.url"],
            source_data=self.SOURCE_DATA,
        )["content"]

        assert content["source"] == {"url": "http://real", "body": "REAL"}
        assert content["extract.source"] == "CLOBBER"

    def test_observed_source_field_still_injected(self):
        content = _enrich(
            {"extract": {"source": "CLOBBER", "title": "T"}},
            ["extract.source", "source.url"],
            source_data=self.SOURCE_DATA,
        )["content"]

        assert content["url"] == "http://real"

    def test_tool_input_keeps_source_url_reachable(self):
        cs = {"observe": ["extract.source", "source.url"]}
        record = _enrich(
            {"extract": {"source": "CLOBBER", "title": "T"}},
            cs["observe"],
            source_data=self.SOURCE_DATA,
        )

        assert extract_tool_input(record, cs) == {
            "extract.source": "CLOBBER",
            "url": "http://real",
        }

    def test_bus_namespace_name_qualified_even_when_absent(self):
        """``version`` is injected downstream for guards and templates; a bare
        flat key of that name would shadow it there."""
        content = _enrich({"extract": {"version": 3, "title": "T"}}, ["extract.version"])[
            "content"
        ]

        assert content["extract.version"] == 3
        assert "version" not in content


class TestNonCollidingKeysStayBare:
    """The qualification only fires on real collisions."""

    def test_distinct_fields_across_namespaces_stay_bare(self):
        content = _enrich(
            {"extract": {"text": "hello"}, "classify": {"topic": "science"}},
            ["extract.text", "classify.topic"],
        )["content"]

        assert content["text"] == "hello"
        assert content["topic"] == "science"

    def test_single_wildcard_stays_bare(self):
        content = _enrich({"extract": {"q": "Q", "a": "A"}}, ["extract.*"])["content"]

        assert content["q"] == "Q"
        assert content["a"] == "A"

    def test_same_namespace_wildcard_and_explicit_do_not_collide(self):
        """``a.*`` and ``a.x`` name the same value — that is not a collision."""
        content = _enrich({"a": {"x": 1, "y": 2}}, ["a.*", "a.x"])["content"]

        assert content["x"] == 1
        assert content["y"] == 2

    def test_no_warning_when_nothing_collides(self, caplog):
        with caplog.at_level(logging.WARNING):
            _enrich({"extract": {"text": "hello"}}, ["extract.text"])

        assert caplog.records == []
