"""A guard reads the framework's resolved ``source`` namespace, not the record's copy.

The copy was taken when the record was written and the pool can have moved past it. The
symptom was a granularity split, but that was a side effect: a FILE-mode ``context_scope``
pass writes the resolved namespace onto the record first, so a FILE action declaring no
``context_scope`` read the stale copy exactly like a RECORD one.

A namespace displaces a namespace and nothing else: ``source``, ``version``, ``workflow``
and ``seed`` are reserved *action* names, which does not make a plain field spelled that way
the framework's. Both sides must be a namespace before the resolved one wins.
"""

from copy import deepcopy

import pytest

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.processing.guard_context import build_guard_context
from agent_actions.processing.prepared_task import PreparationContext
from agent_actions.processing.record_helpers import apply_version_merge
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.prompt.context.scope_application import apply_context_scope_for_records
from agent_actions.utils.constants import RESERVED_AGENT_NAMES, RUNTIME_BUS_NAMESPACES
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

POOL = [{"source_guid": "G0", "content": {"source": {"url": "POOL"}}}]
SCOPE = {"observe": ["source.url"]}
INDICES = {"a1": 0, "a2": 1}

RESOLVED = "source.url == 'POOL'"
CARRIED = "source.url == 'CARRIED'"


def carrying(url="CARRIED", *, source_guid="G0", **extra):
    """A record whose content holds a ``source`` namespace of its own."""
    return {
        "source_guid": source_guid,
        "content": {"source": {"url": url}, "a1": {"n": 1}},
        **extra,
    }


def guard(clause):
    return {"clause": clause, "behavior": "filter", "scope": "item"}


def record_mode(record, clause, *, pool=POOL, version_context=None, workflow_metadata=None):
    """Does a RECORD-granularity guard keep this record? Driven through its real caller."""
    context = PreparationContext(
        agent_config={"granularity": "record", "context_scope": SCOPE, "guard": guard(clause)},
        agent_name="a2",
        source_data=pool,
        agent_indices=INDICES,
        is_first_stage=False,
        version_context=version_context,
        workflow_metadata=workflow_metadata,
    )
    return TaskPreparer().prepare(dict(record), context).should_execute


def file_mode(record, clause, *, pool=POOL, scope=SCOPE):
    """Does a FILE-granularity guard keep this record?

    Mirrors the caller: the scope pass runs first when the action declares one, and
    ``prefilter_by_guard`` sees whatever that left behind. With *scope* ``None`` no pass
    runs, which is what an action declaring no ``context_scope`` hands the guard.
    """
    config = {"granularity": "file", "guard": guard(clause)}
    records = [dict(record)]
    if scope is not None:
        config["context_scope"] = scope
        records, _skipped = apply_context_scope_for_records(
            records, scope, action_name="a2", source_data=pool
        )
    passing, _skipped, _originals, _filtered = prefilter_by_guard(
        records, config, "a2", agent_indices=INDICES, source_data=pool, is_first_stage=False
    )
    return len(passing) == 1


class TestTheResolvedNamespaceIsWhatAGuardEvaluates:
    """The pool is the run's current source set; the carried copy is a snapshot."""

    def test_a_clause_on_the_resolved_value_keeps_the_record(self):
        assert record_mode(carrying(), RESOLVED) is True

    def test_a_clause_on_the_stale_carried_value_does_not_keep_it(self):
        """The other half: a clause matching only the snapshot must stop matching. Without
        it the assertion above is satisfied by a guard that passes everything."""
        assert record_mode(carrying(), CARRIED) is False


class TestNoSurfaceAnswersTheSameClauseDifferently:
    @pytest.mark.parametrize(
        "surface",
        [
            pytest.param(lambda r, c: record_mode(r, c), id="record"),
            pytest.param(lambda r, c: file_mode(r, c), id="file-with-context-scope"),
            pytest.param(lambda r, c: file_mode(r, c, scope=None), id="file-without-context-scope"),
        ],
    )
    def test_every_surface_reads_the_resolved_value(self, surface):
        """Parametrized over the surface rather than asserted as one equality: a bare
        ``record == file`` passes when both are wrong in the same direction."""
        assert surface(carrying(), RESOLVED) is True
        assert surface(carrying(), CARRIED) is False

    def test_the_file_surfaces_are_not_the_same_surface(self):
        """Guards the parametrization above: the no-scope case exists because the scope
        writeback is what made FILE mode look correct, so a fixture that silently ran the
        writeback in both would test one thing twice."""
        scoped, _ = apply_context_scope_for_records(
            [carrying()], SCOPE, action_name="a2", source_data=POOL
        )

        assert scoped[0]["content"]["source"] == {"url": "POOL"}
        assert carrying()["content"]["source"] == {"url": "CARRIED"}


class TestARecordThePoolCannotPlaceStillHasAnAnswer:
    """Preferring the resolved namespace costs nothing: where the carried copy is the only
    answer, the resolver already returns it, so the two agree by construction."""

    def test_the_carried_value_is_what_a_guard_reads_for_an_unplaceable_record(self):
        ghost = carrying("ONLY-COPY", source_guid="GHOST")

        assert record_mode(ghost, "source.url == 'ONLY-COPY'") is True

    def test_an_empty_pool_leaves_the_carried_value_as_the_answer(self):
        assert record_mode(carrying("ONLY-COPY"), "source.url == 'ONLY-COPY'", pool=[]) is True

    def test_a_record_that_resolves_does_not_read_its_own_copy(self):
        """The boundary of the rule above — a placeable record takes the pool's answer."""
        assert record_mode(carrying("ONLY-COPY"), "source.url == 'ONLY-COPY'") is False


class TestTheSiblingFrameworkNamespaces:
    """``source`` is the reachable case; these share the defect and the merge site.
    ``version`` is the one that would bite — a guard inside a fan-out reading a carried
    copy instead of the live iteration."""

    def test_a_carried_version_does_not_shadow_the_live_iteration(self):
        record = {"source_guid": "G0", "content": {"version": {"i": "CARRIED"}, "a1": {"n": 1}}}

        assert (
            record_mode(
                record, "version.i == 'RESOLVED'", version_context={"i": "RESOLVED", "idx": 0}
            )
            is True
        )

    def test_a_carried_workflow_does_not_shadow_the_run_metadata(self):
        record = {"source_guid": "G0", "content": {"workflow": {"name": "CARRIED"}, "a1": {"n": 1}}}

        assert (
            record_mode(
                record, "workflow.name == 'RESOLVED'", workflow_metadata={"name": "RESOLVED"}
            )
            is True
        )


class TestEveryFrameworkNamespaceIsAReservedActionName:
    """What makes the rule safe. The fix takes these keys from the resolved context only,
    which is sound exactly while no action can be named one of them and legitimately write
    its output there. Adding a bus namespace without reserving the name would break that,
    and this is where it shows up."""

    def test_no_bus_namespace_can_be_claimed_by_an_action(self):
        assert RUNTIME_BUS_NAMESPACES <= RESERVED_AGENT_NAMES


class TestAnActionNamespaceStillComesFromTheRecord:
    """The precedence the fix must leave alone: for an action's own output the record holds
    the in-flight value and the context a copy read back from storage."""

    def test_the_records_own_output_outranks_the_stored_copy(self):
        evaluator = GuardEvaluator()
        stored = {"a1": {"n": "FROM-STORAGE"}}
        in_flight = {"a1": {"n": "IN-FLIGHT"}}

        merged = evaluator._build_evaluation_context(in_flight, stored)

        assert merged["a1"] == {"n": "IN-FLIGHT"}

    def test_a_top_level_record_key_still_reaches_the_guard(self):
        evaluator = GuardEvaluator()
        item = {"source_guid": "sg-1", "doc_type": "pdf", "content": {"a1": {"n": 1}}}

        merged = evaluator._build_evaluation_context(item, {"upstream": {"d": 1}})

        assert merged["source_guid"] == "sg-1"
        assert merged["doc_type"] == "pdf"
        assert merged["upstream"] == {"d": 1}
        assert merged["a1"] == {"n": 1}


class TestAFirstStageGuardReadsTheResolvedNamespaceToo:
    """A first-stage action's source is the record itself, resolved by
    ``resolve_first_stage_source``. Asserted here at the guard outcome, which the resolver's
    own tests in ``test_source_resolution.py`` do not reach.

    Worth its own class because these two fixes were masking each other: while the resolver
    handed the namespace builder a record's bare content, a record carrying its own
    ``source`` had it nested twice and every ``source.*`` clause read a missing field — and
    the carried copy, which is correctly shaped, was overriding it, so first-stage guards
    worked by accident. Neither defect was visible while the other stood.
    """

    FIRST_STAGE = {
        "agent_name": "flatten",
        "agent_config": {"context_scope": {}},
        "agent_indices": {"flatten": 0},
        "is_first_stage": True,
    }

    def test_a_record_carrying_a_source_namespace_is_unwrapped(self):
        record = {"source_guid": "S1", "content": {"source": {"page_content": "real"}}}

        context = build_guard_context(record, **self.FIRST_STAGE)

        assert context["source"] == {"page_content": "real"}

    def test_a_record_carrying_none_is_taken_whole(self):
        """The other shape reaching the same branch — staging that never namespaced its
        rows. It read correctly before and must keep doing so."""
        record = {"source_guid": "S2", "content": {"page_content": "real"}}

        context = build_guard_context(record, **self.FIRST_STAGE)

        assert context["source"] == {"page_content": "real"}

    def test_a_first_stage_guard_keeps_a_record_its_clause_matches(self):
        """Through the caller: the doubled namespace made every ``source.*`` clause read a
        missing field, which is *not matched*, so the guard silently skipped the record."""
        record = {"source_guid": "S1", "content": {"source": {"page_content": "real"}}}
        config = {"guard": guard("source.page_content == 'real'")}

        passing, _skipped, _originals, _filtered = prefilter_by_guard(
            [record], config, "flatten", agent_indices={"flatten": 0}, is_first_stage=True
        )

        assert len(passing) == 1

    def test_a_first_stage_guard_still_refuses_one_it_does_not(self):
        record = {"source_guid": "S1", "content": {"source": {"page_content": "real"}}}
        config = {"guard": guard("source.page_content == 'other'")}

        passing, _skipped, _originals, filtered = prefilter_by_guard(
            [record], config, "flatten", agent_indices={"flatten": 0}, is_first_stage=True
        )

        assert len(passing) == 0
        assert len(filtered) == 1


class TestBothItemShapesFollowTheSameRule:
    """The evaluator takes either a record's content or a whole record, and merges each of
    them over the context. Production passes the content; other callers pass the record.
    The rule has to hold on both or a guard's answer depends on which shape reached it.
    """

    RESOLVED_CONTEXT = {"source": {"url": "POOL"}}

    def test_a_whole_record_takes_the_resolved_namespace(self):
        record = {"source_guid": "G0", "content": {"source": {"url": "CARRIED"}, "a1": {"n": 1}}}

        merged = GuardEvaluator()._build_evaluation_context(record, self.RESOLVED_CONTEXT)

        assert merged["source"] == {"url": "POOL"}

    def test_a_whole_record_still_supplies_its_action_namespaces(self):
        """So the assertion above cannot be satisfied by dropping the record's content."""
        record = {"source_guid": "G0", "content": {"source": {"url": "CARRIED"}, "a1": {"n": 1}}}

        merged = GuardEvaluator()._build_evaluation_context(record, self.RESOLVED_CONTEXT)

        assert merged["a1"] == {"n": 1}
        assert merged["source_guid"] == "G0"

    def test_the_bare_content_shape_agrees(self):
        content = {"source": {"url": "CARRIED"}, "a1": {"n": 1}}

        merged = GuardEvaluator()._build_evaluation_context(content, self.RESOLVED_CONTEXT)

        assert merged["source"] == {"url": "POOL"}
        assert merged["a1"] == {"n": 1}


class TestWhatADropDoesNotHideFromAGuard:
    """The resolved namespace is the pool's document, which ``context_scope.drop`` never
    touched — so a dropped ``source`` field is still readable by a guard clause.

    This is a change on the FILE side and it closes a divergence rather than opening one:
    FILE mode used to hide the field, because the writeback put the scoped copy on the
    record, while RECORD mode never did. Measured on the parent commit, FILE answered
    ``kept=0`` and RECORD ``kept=True`` for the same clause. They now agree on RECORD's
    answer, which is also the one that matches a guard's job — it gates the action before
    it runs, and ``drop`` shapes what the action then receives.

    A dependency namespace still comes from the record, so a FILE-mode drop still hides
    one. That asymmetry is characterized here, not endorsed.
    """

    POOL = [{"source_guid": "G0", "content": {"source": {"tier": "secret", "url": "u"}}}]
    CONTENT = {"source": {"tier": "secret", "url": "u"}, "a1": {"tier": "secret", "n": 1}}

    def _file(self, scope, clause):
        record = {"source_guid": "G0", "content": deepcopy(self.CONTENT)}
        enriched, _ = apply_context_scope_for_records(
            [record], scope, action_name="a2", source_data=self.POOL
        )
        passing, _skipped, _originals, _filtered = prefilter_by_guard(
            enriched,
            {"granularity": "file", "context_scope": scope, "guard": guard(clause)},
            "a2",
            agent_indices=INDICES,
            source_data=self.POOL,
            is_first_stage=False,
        )
        return len(passing) == 1

    def _record(self, scope, clause):
        context = PreparationContext(
            agent_config={"granularity": "record", "context_scope": scope, "guard": guard(clause)},
            agent_name="a2",
            source_data=self.POOL,
            agent_indices=INDICES,
            is_first_stage=False,
        )
        record = {"source_guid": "G0", "content": deepcopy(self.CONTENT)}
        return TaskPreparer().prepare(record, context).should_execute

    DROP_SOURCE = {"observe": ["source.url"], "drop": ["source.tier"]}

    def test_both_granularities_agree_a_dropped_source_field_is_still_readable(self):
        clause = "source.tier == 'secret'"

        assert self._file(self.DROP_SOURCE, clause) is True
        assert self._record(self.DROP_SOURCE, clause) is True

    def test_dropping_it_does_not_change_the_answer_either(self):
        """Against the no-drop run, so the test above cannot pass by the clause simply
        never matching. Asserted as ``is True`` on both sides rather than as an equality:
        ``False == False`` would satisfy an equality while proving nothing."""
        no_drop = {"observe": ["source.url"]}
        clause = "source.tier == 'secret'"

        assert self._file(no_drop, clause) is True
        assert self._file(self.DROP_SOURCE, clause) is True

    def test_a_dropped_dependency_field_is_still_hidden_from_a_file_mode_guard(self):
        """Unchanged by the fix and inconsistent with the rows above — a dependency
        namespace comes from the record, which the scope pass did strip."""
        scope = {"observe": ["source.url"], "drop": ["a1.tier"]}

        assert self._file(scope, "a1.tier == 'secret'") is False


class TestOnlyANamespaceIsDisplacedByANamespace:
    """A namespace shadowing a namespace is the defect; a *field* whose name happens to
    match a framework one is somebody's data, and both sides must be a dict before the
    resolved one wins. Three places put a non-namespace under a framework name:

    - a first-stage record's content is the user's staging row, so ``source`` there can be
      a string they staged;
    - a version-merge tool spreads its output flat instead of under its action name, so
      ``version`` or ``source`` can be that tool's own output field;
    - a dependency's ``output_field`` is promoted into the context by name, putting a key
      there that no resolver produced — so presence in the context does not mean resolved.

    Taking such a key away leaves the clause reading a missing field, which counts as *not
    matched*, so the record is silently filtered rather than erroring.
    """

    POOL = [{"source_guid": "G0", "content": {"source": {"u": 1}}}]

    @staticmethod
    def _merged_content():
        """Built through the real function so the shape cannot drift from what ships."""
        return apply_version_merge(
            {
                "kind": "tool",
                "action_name": "pick",
                "version_consumption_config": {"mode": "merge"},
            },
            {"version": "v2", "source": "tool-said-this", "winner": "gen_1"},
            {"source": {"u": 1}, "gen_1": {"n": 1}},
        )

    def _kept(self, content, clause, *, scope, first=False, guid="G0", deps=None):
        context = PreparationContext(
            agent_config={"granularity": "record", "context_scope": scope, "guard": guard(clause)},
            agent_name="a2",
            source_data=self.POOL,
            agent_indices=INDICES,
            is_first_stage=first,
            dependency_configs=deps,
        )
        record = {"source_guid": guid, "content": deepcopy(content)}
        return TaskPreparer().prepare(record, context).should_execute

    A1 = {"observe": ["a1.n"]}
    GEN = {"observe": ["gen_1.n"]}

    def test_a_version_merge_tools_flat_version_field_is_readable(self):
        assert self._kept(self._merged_content(), "version == 'v2'", scope=self.GEN) is True

    def test_a_version_merge_tools_flat_source_field_is_readable(self):
        """The same spread can name an output field ``source``, and the pool *does* resolve
        a ``source`` namespace for this record — so presence on both sides is not enough."""
        assert (
            self._kept(self._merged_content(), "source == 'tool-said-this'", scope=self.GEN) is True
        )

    def test_a_first_stage_staging_field_named_source_is_readable(self):
        """First stage resolves the namespace *out of the record's own content*, so
        ``source`` is in the context — and the staged string is still the user's data."""
        content = {"source": "reuters", "body": "hi"}

        assert (
            self._kept(
                content,
                "source == 'reuters'",
                scope={"observe": ["source.body"]},
                first=True,
                guid="S2",
            )
            is True
        )

    @pytest.mark.parametrize("field,value", [("version", 3), ("workflow", "intake"), ("seed", 42)])
    def test_a_first_stage_staging_field_named_for_a_bus_namespace_is_readable(self, field, value):
        content = {field: value, "body": "hi"}

        assert (
            self._kept(
                content,
                f"{field} == {value!r}",
                scope={"observe": ["source.body"]},
                first=True,
                guid="S1",
            )
            is True
        )

    def test_a_promoted_output_field_does_not_count_as_resolved(self):
        """``build_guard_context`` promotes a dependency's ``output_field`` to a top-level
        key by name. Treating that as a resolved namespace made a clause read a different
        action's output — a clause's answer changing because of config elsewhere, which is
        the shape this fix exists to remove."""
        content = self._merged_content()
        deps = {"a1": {"output_field": "version", "idx": 0}}

        assert self._kept(content, "version == 'v2'", scope=self.A1, deps=deps) is True

    @pytest.mark.parametrize("carried", ["flat-string", [1, 2], 0, ""])
    def test_a_carried_source_that_is_not_a_namespace_is_readable(self, carried):
        content = {"source": carried, "a1": {"n": 1}}

        assert self._kept(content, f"source == {carried!r}", scope=self.A1, guid="MISS") is True

    def test_a_carried_seed_namespace_is_readable_because_no_seed_is_ever_resolved(self):
        """Asserted with its reason: the guard context has no ``seed``, so there is nothing
        to prefer. The first assertion is what fails the day that stops being true."""
        content = {"seed": {"tier": "gold"}, "a1": {"n": 1}}
        context = build_guard_context(
            {"source_guid": "G0", "content": content},
            agent_name="a2",
            agent_config={"granularity": "record", "context_scope": self.A1},
            agent_indices=INDICES,
            source_data=self.POOL,
        )

        assert "seed" not in context
        assert self._kept(content, "seed.tier == 'gold'", scope=self.A1) is True

    def test_but_a_carried_namespace_is_still_displaced(self):
        """The boundary — without this the class is satisfied by reverting the fix."""
        content = {"source": {"u": 99}, "a1": {"n": 1}}
        scope = {"observe": ["source.u"]}

        assert self._kept(content, "source.u == 99", scope=scope) is False
        assert self._kept(content, "source.u == 1", scope=scope) is True


class TestAFieldTheResolvedDocumentLacksBecomesUnreadable:
    """The cost of preferring the resolved namespace, stated where it can be seen. No
    namespace *key* is removed, but the resolved document is a different document: a field
    only the carried copy had goes from matched to missing, which counts as *not matched*.
    That is inherent to resolving against the pool rather than the snapshot, not a
    separable defect — pinned so nobody reads the guarantee as covering fields.
    """

    def test_a_field_only_the_carried_copy_had_stops_matching(self):
        record = {
            "source_guid": "G0",
            "content": {"source": {"u": 1, "extra": "E"}, "a1": {"n": 1}},
        }
        config = {
            "granularity": "file",
            "context_scope": SCOPE,
            "guard": guard("source.extra == 'E'"),
        }

        passing, _s, _o, _f = prefilter_by_guard(
            [record],
            config,
            "a2",
            agent_indices=INDICES,
            source_data=[{"source_guid": "G0", "content": {"source": {"u": 1}}}],
            is_first_stage=False,
        )

        assert len(passing) == 0

    def test_a_field_the_resolved_document_has_is_what_a_clause_reads(self):
        """The same record, the field the pool does carry — so the test above is about the
        document differing, not about the clause never matching."""
        record = {
            "source_guid": "G0",
            "content": {"source": {"u": 99, "extra": "E"}, "a1": {"n": 1}},
        }
        config = {"granularity": "file", "context_scope": SCOPE, "guard": guard("source.u == 1")}

        passing, _s, _o, _f = prefilter_by_guard(
            [record],
            config,
            "a2",
            agent_indices=INDICES,
            source_data=[{"source_guid": "G0", "content": {"source": {"u": 1}}}],
            is_first_stage=False,
        )

        assert len(passing) == 1


class TestAVersionedActionDoesNotDisplaceAToolsOwnField:
    """The narrowest overlap there is, and it does not bite. An action declaring both
    ``versions:`` and ``version_consumption:`` carries a version context *and* has its tool
    output spread flat, so the loop iteration and an output field named ``version`` claim
    one key. The field is a string and the iteration is a namespace, so the two are told
    apart by shape and the field is what a clause reads — with or without the loop.

    Pinned because requiring both sides to be a namespace is what makes this work, and a
    rule keyed on the name alone would answer these two differently.
    """

    POOL = [{"source_guid": "G0", "content": {"source": {"u": 1}}}]

    def _kept(self, version_context):
        content = apply_version_merge(
            {
                "kind": "tool",
                "action_name": "pick",
                "version_consumption_config": {"mode": "merge"},
            },
            {"version": "v2", "winner": "gen_1"},
            {"source": {"u": 1}, "gen_1": {"n": 1}},
        )
        config = {
            "granularity": "file",
            "context_scope": {"observe": ["gen_1.n"]},
            "guard": guard("version == 'v2'"),
        }
        passing, _s, _o, _f = prefilter_by_guard(
            [{"source_guid": "G0", "content": deepcopy(content)}],
            config,
            "a2",
            agent_indices=INDICES,
            source_data=self.POOL,
            is_first_stage=False,
            version_context=version_context,
        )
        return len(passing) == 1

    def test_a_plain_fan_in_reads_the_tools_field(self):
        assert self._kept(None) is True

    def test_a_versioned_fan_in_reads_it_too(self):
        """A version context exists here, so a name-only rule would prefer the iteration
        and this clause would stop matching."""
        assert self._kept({"i": 1, "idx": 0}) is True


class TestAPromotionCannotClaimAFrameworkNamespacesName:
    """What makes the evaluator's rule sound rather than lucky. It reads a bus-namespace key
    in the context as the framework's own answer, so nothing else may put one there.

    ``output_field`` promotion writes a dependency's field into the context by name, and it
    already declines a name another key holds. A framework name is declined too, because a
    promoted field sitting under one would be preferred over the record's — and a dict-valued
    one is indistinguishable from a resolved namespace by shape alone.
    """

    POOL = [{"source_guid": "G0", "content": {"source": {"u": 1}}}]

    def _context(self, content, deps, scope=None):
        return build_guard_context(
            {"source_guid": "G0", "content": deepcopy(content)},
            agent_name="a2",
            agent_config={
                "granularity": "record",
                "context_scope": scope or {"observe": ["a1.n"]},
            },
            agent_indices=INDICES,
            source_data=self.POOL,
            dependency_configs=deps,
        )

    @pytest.mark.parametrize("name", sorted(RUNTIME_BUS_NAMESPACES))
    def test_a_promotion_named_for_a_bus_namespace_is_refused(self, name):
        content = {"a1": {"n": 1, name: {"tier": "FROM-UPSTREAM"}}}
        scope = {"observe": ["a1.n", f"a1.{name}"]}

        context = self._context(content, {"a1": {"output_field": name, "idx": 0}}, scope=scope)

        assert context.get(name) != {"tier": "FROM-UPSTREAM"}

    def test_the_record_keeps_its_own_key_when_a_promotion_is_refused(self):
        """The consequence that matters: a dict-valued promotion would otherwise look like a
        resolved namespace and displace the record's."""
        content = {"a1": {"n": 1, "seed": {"tier": "FROM-UPSTREAM"}}, "seed": {"tier": "gold"}}
        deps = {"a1": {"output_field": "seed", "idx": 0}}
        context = self._context(content, deps, scope={"observe": ["a1.n", "a1.seed"]})

        merged = GuardEvaluator()._build_evaluation_context(content, context)

        assert merged["seed"] == {"tier": "gold"}

    def test_an_ordinary_output_field_is_still_promoted(self):
        """So the refusal is scoped to the reserved names and has not broken the feature."""
        content = {"a1": {"n": 1, "severity": "high"}}
        scope = {"observe": ["a1.n", "a1.severity"]}

        context = self._context(
            content, {"a1": {"output_field": "severity", "idx": 0}}, scope=scope
        )

        assert context["severity"] == "high"
