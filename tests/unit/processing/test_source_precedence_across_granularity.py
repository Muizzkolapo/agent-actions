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
from agent_actions.processing.prepared_task import PreparationContext
from agent_actions.processing.source_resolution import resolve_source_content
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.prompt.context.scope_application import apply_context_scope_for_records
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

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
            "content": {"source": {"content": {"body": "user text"}, "url": "U"}},
            "source_guid": "G0",
        }
        scope = {"observe": ["source.content", "source.url"]}

        assert self.first_stage_guard_source(row, scope=scope) == {
            "content": {"body": "user text"},
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


FLAT = {"source_guid": "G0", "node_id": "n", "lineage": ["a0"], "title": "T", "keep": "yes"}
WILDCARD = {"observe": ["source.*"]}


def prompt_source(record, scope):
    """The ``source`` namespace that reaches the model, through the real batch preparer."""
    config = {
        "agent_type": "llm_agent",
        "prompt": "Title: {{ source.title }}",
        "context_scope": scope,
    }
    context = PreparationContext(agent_config=config, agent_name="a1", is_first_stage=True)
    item = dict(record) if isinstance(record, dict) else record
    task = TaskPreparer().prepare(item, context)
    return (task.llm_context or {}).get("source")


class TestAFlatFirstStageRecordDoesNotSendFrameworkKeysToTheModel:
    """A record whose user fields sit at the top level carries no boundary between them
    and the framework's own keys, so the namespace builder's flat branch published the
    whole record as the source document. An ``observe`` naming fields hid it; a wildcard
    did not, and ``source_guid``, ``node_id`` and ``lineage`` went to the model as fields
    of the user's document. ``RECORD_FRAMEWORK_FIELDS`` is the list that draws the
    boundary, and the first-stage path did not consult it.
    """

    def test_a_wildcard_does_not_offer_framework_keys_as_document_fields(self):
        assert prompt_source(FLAT, WILDCARD) == {"title": "T", "keep": "yes"}

    def test_a_wildcard_still_offers_every_user_field(self):
        """The other half: withholding must not cost the user a field they staged."""
        observed = prompt_source(FLAT, WILDCARD)

        assert observed is not None and observed.get("title") == "T"

    def test_naming_the_fields_explicitly_is_unchanged(self):
        """Already correct, because the observe list never named a framework key."""
        scope = {"observe": ["source.title", "source.keep"]}

        assert prompt_source(FLAT, scope) == {"title": "T", "keep": "yes"}

    def test_an_enveloped_record_under_a_wildcard_is_unchanged(self):
        """The only shape the staging pipeline writes: the envelope already draws the
        boundary, so the wildcard was always safe there and must stay so."""
        row = {
            "content": {"source": {"title": "T", "keep": "yes"}},
            "source_guid": "G0",
            "node_id": "n",
        }

        assert prompt_source(row, WILDCARD) == {"title": "T", "keep": "yes"}

    def test_the_envelope_is_what_lets_a_user_field_share_a_framework_name(self):
        """``lineage`` inside the document is the user's and survives a wildcard. That is
        the whole value of the envelope: a flat record cannot make this distinction, and
        the framework withholds the name rather than guess."""
        row = {"content": {"source": {"lineage": "user value", "title": "T"}}, "source_guid": "G0"}

        assert prompt_source(row, WILDCARD) == {"lineage": "user value", "title": "T"}


class TestAFirstStageItemThatIsNotARecord:
    """``_normalize_input`` returns the item unchanged at first stage whatever its type, so
    a str, list or scalar reaches source resolution. Normalizing one unconditionally raises
    ``AttributeError`` on ``record.get("content")``; these pin the shapes that keep the
    resolver from being written that way.
    """

    @pytest.mark.parametrize("item", ["just some text", [{"title": "T"}], 7, 0.5, True])
    def test_a_non_record_item_resolves_to_no_source_namespace(self, item):
        assert prompt_source(item, WILDCARD) is None


POOLED_BUT_CARRYING = {
    "source_guid": "G0",
    "content": {"a1": {"n": 1}, "source": {"url": "CARRIED"}},
}
"""Resolves two ways if a surface reads the wrong one: identity places it in the pool at
``POOL``, while the namespace it carries says ``CARRIED``."""

NOT_CARRYING = {"source_guid": "G0", "content": {"a1": {"n": 1}}}


def prepare_pooled(record, guard=None):
    """Run the real preparer over a later-stage record against ``POOL``."""
    config = {
        "agent_type": "llm_agent",
        "prompt": "URL: {{ source.url }}",
        "granularity": "record",
        "context_scope": SCOPE,
    }
    if guard is not None:
        config["guard"] = guard
    context = PreparationContext(
        agent_config=config,
        agent_name="a2",
        agent_indices={"a1": 0, "a2": 1},
        source_data=POOL,
        is_first_stage=False,
    )
    return TaskPreparer().prepare(dict(record), context)


class TestThePromptAndThePrefilterGuardResolveOneNamespace:
    """``PreparedTask.source_content`` was assigned on both exit paths and read nowhere, so
    it could not become the single carrier of the resolved namespace: ``prefilter_by_guard``
    runs over raw records before any ``PreparedTask`` exists, and within
    ``TaskPreparer.prepare`` the guard and the prompt already share one ``field_context``
    built from one resolution. What the field stood in for is the agreement between the two
    surfaces that do resolve independently — the preparer resolves and threads the value
    into ``build_guard_context``, the prefilter lets it resolve inside. These pin that
    agreement directly, which is what makes the field safe to delete.
    """

    def test_the_prompt_reads_the_namespace_a_guard_context_resolves_unaided(self):
        """``record_mode_source`` is ``build_guard_context`` called with no pre-resolved
        value — the resolution path the prefilter takes, not the prefilter itself. The
        function proper is driven in
        ``TestTheGuardThePromptAndThePrefilterReadOneResolvedNamespace``.
        """
        task = prepare_pooled(POOLED_BUT_CARRYING)

        assert task.llm_context["source"] == record_mode_source(POOLED_BUT_CARRYING)

    def test_that_shared_namespace_is_the_pool_row_not_the_carried_copy(self):
        """Agreement alone is also satisfied by both surfaces being wrong together."""
        task = prepare_pooled(POOLED_BUT_CARRYING)

        assert task.llm_context["source"] == {"url": "POOL"}
        assert task.formatted_prompt == "URL: POOL"


class TestTheGuardThePromptAndThePrefilterReadOneResolvedNamespace:
    """The agreement a carrier field would have been for, asserted across all three
    surfaces at once. A record that both resolves in the pool and carries its own
    ``source`` namespace has two available answers, so a surface reading the wrong one is
    visible rather than silent.

    Until #1135 the in-prepare guard was the odd one out: the evaluator merged the guard's
    item after the resolved context, so the record's carried copy overrode it and a guard
    admitted on a value the prompt would never show. That is fixed on trunk.

    Overlap with #1135, stated rather than implied: ``test_guard_source_precedence_across_
    granularity.py`` drives the same two callers these do — ``TaskPreparer.prepare`` and
    ``prefilter_by_guard`` — and its ``TestNoSurfaceAnswersTheSameClauseDifferently``
    already pins guard-to-guard agreement on this record shape. The guard cases below are
    a second angle on that, kept because this file is where the carrier question is
    answered. What is *not* covered there is the **prompt**: that the value a guard
    admitted on is the one the model is then shown (``formatted_prompt == "URL: POOL"``).
    That assertion is the new coverage, and it is the half a carrier field would have been
    for.
    """

    def test_the_guard_admits_on_the_resolved_value_not_the_carried_copy(self):
        admitted = prepare_pooled(
            POOLED_BUT_CARRYING, guard={"clause": "source.url == 'POOL'", "behavior": "filter"}
        )

        assert admitted.should_execute

    def test_the_carried_copy_does_not_satisfy_the_guard(self):
        """The other side: the value sitting in the record is not what the guard reads.

        Filtering alone would also follow from ``source`` being absent from the context
        entirely — a missing field reads as not matched — so this pins that the namespace
        is present and holds the resolved value while the carried one fails to match.
        """
        filtered = prepare_pooled(
            POOLED_BUT_CARRYING,
            guard={"clause": "source.url == 'CARRIED'", "behavior": "filter"},
        )

        assert filtered.is_filtered
        assert prepare_pooled(POOLED_BUT_CARRYING).llm_context["source"] == {"url": "POOL"}

    def test_the_prompt_shows_the_value_the_guard_admitted_on(self):
        """Both surfaces in one run, which is the invariant: a guard may not admit a
        record on a value the model is then not shown."""
        admitted = prepare_pooled(
            POOLED_BUT_CARRYING, guard={"clause": "source.url == 'POOL'", "behavior": "filter"}
        )

        assert admitted.should_execute
        assert admitted.formatted_prompt == "URL: POOL"

    def test_carrying_a_copy_at_all_changes_no_answer(self):
        """The record's own copy is not the discriminator it used to be: the same record
        without one resolves and guards identically."""
        carrying = prepare_pooled(
            POOLED_BUT_CARRYING, guard={"clause": "source.url == 'POOL'", "behavior": "filter"}
        )
        bare = prepare_pooled(
            NOT_CARRYING, guard={"clause": "source.url == 'POOL'", "behavior": "filter"}
        )

        assert carrying.should_execute == bare.should_execute
        assert carrying.formatted_prompt == bare.formatted_prompt == "URL: POOL"

    def test_the_prefilter_agrees_with_the_preparer_for_either_shape(self):
        """``prefilter_by_guard`` itself, not a stand-in for it: the surface that resolves
        internally rather than being handed a value, and the reason the resolved namespace
        cannot be carried on a ``PreparedTask`` — it runs over raw records, before one
        exists. Both shapes are admitted on the resolved value, and the preparer then
        renders the prompt from the same one.
        """
        guard = {"clause": "source.url == 'POOL'", "behavior": "filter"}
        config = {"granularity": "record", "context_scope": SCOPE, "guard": guard}

        for record in (POOLED_BUT_CARRYING, NOT_CARRYING):
            passing, skipped, _originals, filtered = prefilter_by_guard(
                [dict(record)],
                config,
                "a2",
                agent_indices={"a1": 0, "a2": 1},
                source_data=POOL,
            )

            assert (len(passing), len(skipped), len(filtered)) == (1, 0, 0)
            assert prepare_pooled(record, guard=guard).formatted_prompt == "URL: POOL"

    def test_the_prefilter_filters_on_the_resolved_value_too(self):
        """The falsifiable half: the carried copy does not admit a record here either."""
        config = {
            "granularity": "record",
            "context_scope": SCOPE,
            "guard": {"clause": "source.url == 'CARRIED'", "behavior": "filter"},
        }

        passing, _skipped, _originals, filtered = prefilter_by_guard(
            [dict(POOLED_BUT_CARRYING)],
            config,
            "a2",
            agent_indices={"a1": 0, "a2": 1},
            source_data=POOL,
        )

        assert (len(passing), len(filtered)) == (0, 1)
