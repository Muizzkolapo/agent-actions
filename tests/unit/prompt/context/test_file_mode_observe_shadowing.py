"""FILE-mode flat observed keys must never destroy what already holds their name.

Each observed field lands in a record's ``content`` as a bare top-level key.
Written blind it overwrites whatever owns that name — a sibling namespace, a bus
namespace, or a field a wildcard expanded onto — last writer wins, by ref order.
Clobbering a namespace also strands that namespace's own observed fields, which
then resolve against a non-dict and vanish. That record is the data bus for FILE
``kind: tool`` and ``kind: hitl``, so each case is silent data loss into a UDF.

Key names come from the observe refs alone; deriving them from the values would
make a UDF's keys depend on which records share its file.
"""

import logging
from copy import deepcopy

import pytest

from agent_actions.prompt.context.scope_application import (
    apply_context_scope_for_records,
    plan_flat_observed_keys,
)
from agent_actions.workflow.pipeline_file_mode import extract_tool_input

_SCOPE_LOGGER = "agent_actions.prompt.context.scope_application"


class _Collector(logging.Handler):
    def __init__(self, messages):
        super().__init__(logging.WARNING)
        self.messages = messages

    def emit(self, record):
        self.messages.append(record.getMessage())


@pytest.fixture
def scope_warnings():
    """Warnings emitted by the scope logger, captured on that logger directly.

    ``LoggerFactory`` sets ``propagate = False`` on the ``agent_actions`` logger
    once initialized, so caplog's root handler sees these records only when no
    earlier test has set the bridge up.
    """
    logger = logging.getLogger(_SCOPE_LOGGER)
    messages: list[str] = []
    handler = _Collector(messages)
    saved_level, saved_disabled = logger.level, logger.disabled
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    logger.disabled = False
    try:
        yield messages
    finally:
        logger.removeHandler(handler)
        logger.setLevel(saved_level)
        logger.disabled = saved_disabled


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

        assert content["x"] == "FROM_A"
        assert content["b.x"] == "FROM_B"
        assert content["y"] == 2

    def test_key_shape_is_order_independent(self):
        forward = _enrich(dict(self.CONTENT), ["a.*", "b.x"])["content"]
        reverse = _enrich(dict(self.CONTENT), ["b.x", "a.*"])["content"]

        assert forward == reverse

    def test_tool_input_delivers_both_values(self):
        cs = {"observe": ["a.*", "b.x"]}
        record = _enrich(dict(self.CONTENT), cs["observe"])

        assert extract_tool_input(record, cs) == {"x": "FROM_A", "y": 2, "b.x": "FROM_B"}

    def test_collision_is_announced(self, scope_warnings):
        _enrich(dict(self.CONTENT), ["a.*", "b.x"], action_name="merge")

        assert any("merge" in m and "b.x" in m for m in scope_warnings)


class TestKeyShapeIsDeclarationDerived:
    """Key names come from the observe refs, never the values, so a record's keys
    cannot depend on which other records share its file."""

    def test_explicit_ref_qualifies_whenever_a_wildcard_could_reach_it(self):
        """`a.*` may or may not expand onto `x` depending on the data; qualifying
        `b.x` only when it actually does would make the key data-dependent."""
        cs = {"observe": ["a.*", "b.x"]}
        records = [
            {"source_guid": "g1", "content": {"a": {"x": 1}, "b": {"x": 2}}},
            {"source_guid": "g2", "content": {"a": {"y": 3}, "b": {"x": 2}}},
        ]
        enriched, _ = apply_context_scope_for_records(
            records=records, context_scope=cs, action_name="agg"
        )

        payloads = [extract_tool_input(r, cs) for r in enriched]

        assert payloads == [{"x": 1, "b.x": 2}, {"y": 3, "b.x": 2}]

    def test_same_record_gives_the_same_keys_alone_or_with_file_mates(self):
        cs = {"observe": ["a.*", "b.status"]}
        keeper = {"source_guid": "k", "content": {"a": {"keep": "yes"}, "b": {"status": "B"}}}
        collider = {"source_guid": "c", "content": {"a": {"status": "X"}, "b": {"status": "Y"}}}

        alone, _ = apply_context_scope_for_records(
            records=[deepcopy(keeper)], context_scope=cs, action_name="agg"
        )
        together, _ = apply_context_scope_for_records(
            records=[deepcopy(keeper), collider], context_scope=cs, action_name="agg"
        )

        assert extract_tool_input(alone[0], cs) == extract_tool_input(together[0], cs)

    def test_single_wildcard_with_no_other_namespace_stays_bare(self):
        cs = {"observe": ["a.*", "a.x"]}
        enriched, _ = apply_context_scope_for_records(
            records=[{"source_guid": "g", "content": {"a": {"x": 1, "y": 2}}}],
            context_scope=cs,
            action_name="agg",
        )

        assert extract_tool_input(enriched[0], cs) == {"x": 1, "y": 2}

    def test_record_and_payload_agree_on_every_key(self):
        cs = {"observe": ["a.*", "b.x"]}
        enriched, _ = apply_context_scope_for_records(
            records=[{"source_guid": "g", "content": {"a": {"x": 1}, "b": {"x": 2}}}],
            context_scope=cs,
            action_name="agg",
        )
        payload = extract_tool_input(enriched[0], cs)

        for key, value in payload.items():
            assert enriched[0]["content"][key] == value


class TestNamespaceProtectionIsBatchStable:
    """An unobserved namespace present on only some records of a batch must not
    make a guard see a namespace dict on one record and the observed value on
    the next, for the identical observe ref."""

    def test_namespace_present_on_only_one_record_qualifies_on_both(self):
        cs = {"observe": ["a.c"]}
        records = [
            {"source_guid": "r1", "content": {"a": {"c": "CLOBBER1"}, "c": {"z": 1}}},
            {"source_guid": "r2", "content": {"a": {"c": "CLOBBER2"}}},
        ]
        enriched, _ = apply_context_scope_for_records(
            records=records, context_scope=cs, action_name="agg"
        )

        assert enriched[0]["content"]["a.c"] == "CLOBBER1"
        assert enriched[0]["content"]["c"] == {"z": 1}
        # r2 never had a "c" namespace, but the batch did — qualified here too.
        assert enriched[1]["content"]["a.c"] == "CLOBBER2"
        assert "c" not in enriched[1]["content"]

    def test_a_guard_on_the_bare_name_sees_the_same_thing_for_every_record(self):
        from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

        cs = {"observe": ["a.c"]}
        records = [
            {"source_guid": "r1", "content": {"a": {"c": "TARGET"}, "c": {"z": 1}}},
            {"source_guid": "r2", "content": {"a": {"c": "TARGET"}}},
        ]
        enriched, _ = apply_context_scope_for_records(
            records=records, context_scope=cs, action_name="agg"
        )

        passing, _, _, filtered = prefilter_by_guard(
            enriched, {"guard": {"clause": "c == 'TARGET'", "behavior": "filter"}}, "agg"
        )

        # Both records observed the identical value under the identical ref;
        # the bare-key guard must not accept one and reject the other.
        assert {r["source_guid"] for r in passing} == set()
        assert {r["source_guid"] for r in filtered} == {"r1", "r2"}


class TestPlanFlatObservedKeysDotCollision:
    """A field name containing a literal dot can produce the same qualified key
    as another namespace's own qualified key. The second write must not
    silently clobber the first."""

    def test_second_claimant_of_an_already_written_key_is_dropped_not_overwritten(
        self, scope_warnings
    ):
        # "enrich" observes a field literally named "b.x" (dot-in-name), which
        # qualifies to the same key "b.x" that qualifying (ns=b, field=x) would.
        content = {"enrich": {"b.x": "FIRST"}, "b": {"x": "SECOND"}}
        resolved = [("enrich", "b.x", "b.x"), ("b", "x", "x")]

        flat, _ = plan_flat_observed_keys(
            content, resolved, qualify_wildcards=False, reserved_names={"x"}, action_name="probe"
        )

        assert flat["b.x"] == "FIRST"
        assert any("probe" in m and "b.x" in m for m in scope_warnings)


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

    def test_namespace_shadowing_is_announced(self, scope_warnings):
        """The observed-namespace case is payload-visible, so it must be said."""
        _enrich(dict(self.CONTENT), ["a.b", "b.y"], action_name="merge")

        assert any("merge" in m and "a.b" in m for m in scope_warnings)

    def test_unobserved_sibling_namespace_survives(self):
        """The enriched record carries every namespace for downstream guards,
        so an unobserved namespace is no less protected than an observed one."""
        content = _enrich({"a": {"c": "CLOBBER"}, "c": {"z": 1}}, ["a.c"])["content"]

        assert content["c"] == {"z": 1}

    def test_tool_input_delivers_the_unobserved_shadowed_field(self):
        """The payload is flat, so nothing there can be shadowed: `c` stays bare.
        The record qualifies it only to protect a namespace the payload has no
        concept of — the value reaches the action either way."""
        cs = {"observe": ["a.c"]}
        record = _enrich({"a": {"c": "CLOBBER"}, "c": {"z": 1}}, cs["observe"])

        assert extract_tool_input(record, cs) == {"c": "CLOBBER"}

    def test_record_only_qualification_is_not_announced(self, scope_warnings):
        """Telling the user to 'read the qualified key' would send them to a key
        the payload does not have — so this protection stays quiet."""
        content = _enrich({"a": {"c": "CLOBBER"}, "c": {"z": 1}}, ["a.c"])["content"]

        assert content["a.c"] == "CLOBBER"
        assert scope_warnings == []
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
        content = _enrich({"extract": {"version": 3, "title": "T"}}, ["extract.version"])["content"]

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

    def test_no_warning_when_nothing_collides(self, scope_warnings):
        _enrich({"extract": {"text": "hello"}}, ["extract.text"])

        assert scope_warnings == []
