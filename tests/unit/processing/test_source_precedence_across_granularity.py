"""Both granularities resolve a record's ``source`` namespace in the same order.

A record can carry a ``source`` namespace in its own content *and* resolve in the source
pool under its identity. The FILE-mode resolver reads identity first and treats the
carried namespace as the answer for a record the pool cannot place. The RECORD-mode
resolver read the carried namespace before looking at identity at all, so the same record
resolved to a different document depending on the granularity of the action reading it.

Identity is authoritative: the pool is the run's current source set, while the namespace a
record carries is a copy taken when the record was written and can be older. A record the
pool cannot place still resolves against what it carries, which is the only thing it has.

The carried namespace must also be a namespace. Gating on the key's presence alone let a
record whose ``source`` held a scalar be returned as its own source document, and the
namespace builder then exposed that record's other content — its upstream actions' output —
under ``source.*``.
"""

import pytest

from agent_actions.processing.guard_context import build_guard_context
from agent_actions.processing.source_resolution import resolve_source_content
from agent_actions.prompt.context.scope_application import apply_context_scope_for_records

POOL = [
    {"source_guid": "G0", "content": {"source": {"url": "POOL"}}},
    {"source_guid": "G1", "content": {"source": {"url": "OTHER"}}},
]
SCOPE = {"observe": ["source.url"]}


def record_mode_source(record, pool=POOL, scope=None):
    """The ``source`` namespace a RECORD-granularity action observes."""
    return build_guard_context(
        dict(record),
        agent_name="a2",
        agent_config={"granularity": "record", "context_scope": scope or SCOPE},
        agent_indices={"a1": 0, "a2": 1},
        source_data=pool,
        is_first_stage=False,
    ).get("source")


def file_mode_source(record, pool=POOL, scope=None):
    """The ``source`` namespace a FILE-granularity action observes, or None if skipped."""
    enriched, _ = apply_context_scope_for_records(
        [dict(record)], scope or SCOPE, action_name="a2", source_data=pool
    )
    return enriched[0]["content"].get("source") if enriched else None


def carrying(url, **kwargs):
    return {"content": {"source": {"url": url}, "a1": {"n": 1}}, **kwargs}


class TestIdentityOutranksTheCarriedNamespace:
    def test_record_mode_reads_the_pool_for_a_record_whose_guid_resolves(self):
        assert record_mode_source(carrying("CARRIED", source_guid="G0")) == {"url": "POOL"}

    def test_record_mode_reads_the_pool_for_a_record_resolving_through_its_parent(self):
        row = carrying("CARRIED", source_guid="MINTED", parent_source_guid="G1")

        assert record_mode_source(row) == {"url": "OTHER"}

    def test_both_granularities_observe_the_same_namespace(self):
        """The invariant, as a relationship: the answer may not depend on the
        granularity of the action that happens to read the record."""
        row = carrying("CARRIED", source_guid="G0")

        assert record_mode_source(row) == file_mode_source(row) == {"url": "POOL"}

    def test_the_resolver_returns_the_pool_record_not_the_item(self):
        """At the resolver boundary, so a caller reading ``content`` directly sees it too."""
        row = carrying("CARRIED", source_guid="G0")

        resolved = resolve_source_content(row, "G0", POOL, "a2")

        assert resolved["content"]["source"] == {"url": "POOL"}


class TestACarriedNamespaceStillResolvesARecordThePoolCannotPlace:
    def test_a_record_whose_identities_both_miss_reads_what_it_carries(self):
        row = carrying("CARRIED", source_guid="GHOST", parent_source_guid="ALSO-GHOST")

        assert record_mode_source(row) == {"url": "CARRIED"}

    def test_both_granularities_agree_on_that_record_too(self):
        row = carrying("CARRIED", source_guid="GHOST")

        assert record_mode_source(row) == file_mode_source(row) == {"url": "CARRIED"}

    def test_an_empty_pool_leaves_the_carried_namespace_as_the_answer(self):
        row = carrying("CARRIED", source_guid="G0")

        assert record_mode_source(row, pool=[]) == {"url": "CARRIED"}


class TestTheCarriedValueMustBeANamespace:
    """Gating on the key alone returned the record as its own source document."""

    def test_a_scalar_under_source_does_not_shadow_a_resolving_identity(self):
        row = {"content": {"source": "not-a-namespace", "a1": {"n": 1}}, "source_guid": "G0"}

        assert record_mode_source(row) == {"url": "POOL"}

    def test_a_scalar_under_source_resolves_to_nothing_not_the_records_own_content(self):
        """``a1`` and ``secret`` are this record's own content, not its source document.
        Served as the source namespace they are both wrong and a wider disclosure than
        the reference asked for, so an identity miss must resolve to nothing instead."""
        row = {
            "content": {"source": "not-a-namespace", "a1": {"n": 1}, "secret": "X"},
            "source_guid": "GHOST",
        }

        observed = record_mode_source(row)

        assert observed is None, f"the record's own content was served as its source: {observed}"

    @pytest.mark.parametrize("carried", [None, [{"url": "L"}], 0, ""])
    def test_no_other_non_namespace_shape_shadows_a_resolving_identity(self, carried):
        """The scalar is not a special case — anything that is not a namespace loses
        to an identity that resolves."""
        row = {"content": {"source": carried, "a1": {"n": 1}}, "source_guid": "G0"}

        assert record_mode_source(row) == {"url": "POOL"}

    def test_an_emptied_namespace_is_not_treated_as_a_missing_one(self):
        """``{}`` is a namespace, so it does not fall through to the pool — but it
        carries no fields, so an observe on one resolves to nothing rather than to
        the pool's value."""
        row = {"content": {"source": {}, "a1": {"n": 1}}, "source_guid": "GHOST"}

        assert record_mode_source(row) is None

    def test_a_record_carrying_no_source_key_at_all_still_resolves_by_identity(self):
        row = {"content": {"a1": {"n": 1}}, "source_guid": "G0"}

        assert record_mode_source(row) == {"url": "POOL"}

    def test_a_record_with_neither_an_identity_nor_a_namespace_resolves_to_nothing(self):
        row = {"content": {"a1": {"n": 1}}, "source_guid": "GHOST"}

        assert resolve_source_content(row, "GHOST", POOL, "a2") is None


class TestAPoolThatIsTheActionsOwnInputSet:
    """A workflow with no staging data of its own resolves against its input records,
    so a record matches itself by guid. That is not a resolved source document."""

    def test_a_self_hit_does_not_bypass_the_namespace_check(self):
        row = {"content": {"a1": {"n": 1}, "secret": "X"}, "source_guid": "G0"}

        assert resolve_source_content(row, "G0", [row], "a2") is None

    def test_a_self_hit_still_yields_the_namespace_the_record_carries(self):
        row = carrying("CARRIED", source_guid="G0")

        resolved = resolve_source_content(row, "G0", [row], "a2")

        assert resolved is not None
        assert resolved["content"]["source"] == {"url": "CARRIED"}

    def test_another_record_sharing_the_guid_is_still_resolved(self):
        """Only a hit that *is* this record is skipped; a different row under the
        same guid is a real pool entry and must still answer."""
        row = carrying("CARRIED", source_guid="G0")
        other = {"source_guid": "G0", "content": {"source": {"url": "OTHER-ROW"}}}

        resolved = resolve_source_content(row, "G0", [other, row], "a2")

        assert resolved["content"]["source"] == {"url": "OTHER-ROW"}


class TestTheTwoResolversPickTheSameRowFromADuplicatedPool:
    """A repair concatenates every staged path, so one guid can appear twice."""

    def test_both_granularities_take_the_first_row(self):
        pool = [
            {"source_guid": "G0", "content": {"source": {"url": "FIRST"}}},
            {"source_guid": "G0", "content": {"source": {"url": "LAST"}}},
        ]
        row = carrying("CARRIED", source_guid="G0")

        assert record_mode_source(row, pool=pool) == file_mode_source(row, pool=pool)

    def test_that_row_is_the_first_one(self):
        pool = [
            {"source_guid": "G0", "content": {"source": {"url": "FIRST"}}},
            {"source_guid": "G0", "content": {"source": {"url": "LAST"}}},
        ]
        row = carrying("CARRIED", source_guid="G0")

        assert file_mode_source(row, pool=pool) == {"url": "FIRST"}
