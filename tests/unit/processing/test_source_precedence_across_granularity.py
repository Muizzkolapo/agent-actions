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


SKIPPED = "<record skipped>"


def file_mode_source(record, pool=POOL, scope=None):
    """The ``source`` namespace a FILE-granularity action observes.

    Returns the ``SKIPPED`` sentinel rather than None when the record was dropped,
    so a parity assertion cannot pass by both sides answering "nothing".
    """
    enriched, _ = apply_context_scope_for_records(
        [dict(record)], scope or SCOPE, action_name="a2", source_data=pool
    )
    if not enriched:
        return SKIPPED
    return enriched[0]["content"].get("source")


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

    @pytest.mark.parametrize("carried", ["a string", None, [{"url": "L"}], 0, ""])
    def test_no_non_namespace_shape_is_accepted_as_the_record_own_document(self, carried):
        """A pool-miss guid, so the type check is what decides: with the key-presence
        gate each of these returned the record and published ``a1`` as ``source.*``."""
        row = {"content": {"source": carried, "a1": {"n": 1}}, "source_guid": "GHOST"}

        assert resolve_source_content(row, "GHOST", POOL, "a2") is None

    def test_an_emptied_namespace_is_still_a_namespace(self):
        """``{}`` passes the type check, so the record is still its own answer. Asserted
        at the resolver: the namespace builder collapses ``{}`` and "no source key" to
        the same thing one layer down, which would hide the distinction."""
        row = {"content": {"source": {}, "a1": {"n": 1}}, "source_guid": "GHOST"}

        assert resolve_source_content(row, "GHOST", POOL, "a2") is row

    def test_a_record_carrying_no_source_key_at_all_still_resolves_by_identity(self):
        row = {"content": {"a1": {"n": 1}}, "source_guid": "G0"}

        assert record_mode_source(row) == {"url": "POOL"}

    def test_a_record_with_neither_an_identity_nor_a_namespace_resolves_to_nothing(self):
        row = {"content": {"a1": {"n": 1}}, "source_guid": "GHOST"}

        assert resolve_source_content(row, "GHOST", POOL, "a2") is None


class TestTheTwoResolversPickTheSameRowFromADuplicatedPool:
    """A repair concatenates every staged path, so one guid can appear twice."""

    def test_both_granularities_take_the_first_row(self):
        pool = [
            {"source_guid": "G0", "content": {"source": {"url": "FIRST"}}},
            {"source_guid": "G0", "content": {"source": {"url": "LAST"}}},
        ]
        row = carrying("CARRIED", source_guid="G0")

        assert (
            record_mode_source(row, pool=pool)
            == file_mode_source(row, pool=pool)
            == {"url": "FIRST"}
        )


class TestAPoolThatIsTheActionsOwnInputSet:
    """A workflow with no staging data of its own passes its input records as the pool
    (``workflow/pipeline.py``: "the input data IS the source"). A record then resolves to
    itself at the identity step, and its own content *is* the source document — so the
    rule that a record is never handed its own content applies only where the pool is a
    separate set. Pinned because it reads like a bug and is not one."""

    def test_a_record_in_its_own_pool_resolves_to_itself(self):
        row = {"content": {"a1": {"n": 1}}, "source_guid": "G0"}

        assert resolve_source_content(row, "G0", [row], "a2") is row

    def test_its_own_content_becomes_the_source_namespace(self):
        row = {"content": {"a1": {"n": 1}}, "source_guid": "G0"}

        assert record_mode_source(row, pool=[row], scope={"observe": ["source.a1"]}) == {
            "a1": {"n": 1}
        }

    def test_a_record_carrying_a_namespace_still_resolves_to_that_namespace(self):
        """Its self-hit returns itself, and the namespace builder then unwraps
        ``content.source`` — so carrying one is not overridden by being its own pool row."""
        row = carrying("CARRIED", source_guid="G0")

        assert record_mode_source(row, pool=[row]) == {"url": "CARRIED"}

    def test_a_separate_pool_row_is_still_preferred_over_the_records_own_content(self):
        """The boundary: once the pool is a separate set, identity answers from it."""
        row = {"content": {"a1": {"n": 1}}, "source_guid": "G0"}

        assert record_mode_source(row) == {"url": "POOL"}


class TestAFirstStageGuardReadsTheSameNamespaceAsTheActionItGuards:
    """``prefilter_by_guard`` builds guard context without a resolved ``source_content``,
    so a first-stage record was answered from ``get_existing_content`` — the inner content
    dict, one level below the record envelope the namespace builder reads. The builder
    found no ``content`` key, took its flat branch and published ``{"source": payload}``
    as the source namespace, so a guard on ``source.<field>`` resolved for every other
    action and not for the first one: the "works in batch, fails online" class
    ``guard_context`` exists to close.

    The same call also skipped the normalizer's first-stage mode, so a record whose user
    fields sit at the top level resolved to no source namespace at all.
    """

    def first_stage_guard_source(self, record, scope=None):
        """The ``source`` namespace a FILE-mode first-stage guard sees.

        Mirrors ``prefilter_by_guard``'s call: no ``source_content``, no pool,
        ``is_first_stage=True``.
        """
        return build_guard_context(
            dict(record),
            agent_name="a1",
            agent_config={"context_scope": scope or SCOPE},
            is_first_stage=True,
        ).get("source")

    def test_a_first_stage_guard_reads_the_records_own_source_fields(self):
        row = {"content": {"source": {"url": "CARRIED"}}, "source_guid": "G0"}

        assert self.first_stage_guard_source(row) == {"url": "CARRIED"}

    def test_the_first_stage_guard_agrees_with_every_later_action(self):
        """The invariant as a relationship: which action reads the record may not
        decide what ``source.*`` means. A first-stage record is its own input, so the
        later-action reading is the same record resolving against a pool of itself."""
        row = {"content": {"source": {"url": "CARRIED"}}, "source_guid": "G0"}

        assert self.first_stage_guard_source(row) == record_mode_source(row, pool=[row])

    def test_a_payload_field_named_content_is_not_read_as_the_envelope(self):
        """``content`` is a framework key at the envelope level and an ordinary user
        field inside the document. Reading the inner dict as an envelope conflated them."""
        row = {
            "content": {"source": {"content": "user text", "url": "U"}},
            "source_guid": "G0",
        }
        scope = {"observe": ["source.content", "source.url"]}

        assert self.first_stage_guard_source(row, scope=scope) == {
            "content": "user text",
            "url": "U",
        }

    def test_a_record_carrying_no_source_namespace_is_still_its_own_namespace(self):
        """Unchanged by the fix, and the reason the builder cannot simply be handed the
        record: a first-stage record without a ``source`` sub-namespace has its whole
        content as the source document."""
        row = {"content": {"a1": {"n": 1}}, "source_guid": "G0"}

        assert self.first_stage_guard_source(row, scope={"observe": ["source.a1"]}) == {
            "a1": {"n": 1}
        }

    def test_a_flat_record_offers_its_user_fields_and_not_the_frameworks(self):
        """A first-stage record whose user fields sit at the top level. The normalizer
        synthesizes the namespace from the keys ``RECORD_FRAMEWORK_FIELDS`` does not
        claim; skipping its first-stage mode resolved the whole record to nothing."""
        row = {
            "source_guid": "G0",
            "node_id": "n",
            "lineage": ["a0"],
            "url": "U",
            "title": "T",
        }
        scope = {"observe": ["source.url", "source.title"]}

        assert self.first_stage_guard_source(row, scope=scope) == {"url": "U", "title": "T"}
