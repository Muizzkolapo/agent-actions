"""A guard reads the framework's resolved ``source`` namespace, not the record's copy.

The copy was taken when the record was written and the pool can have moved past it. The
symptom was a granularity split, but that was a side effect: a FILE-mode ``context_scope``
pass writes the resolved namespace onto the record first, so a FILE action declaring no
``context_scope`` read the stale copy exactly like a RECORD one.

``source``, ``version``, ``workflow`` and ``seed`` are reserved action names, so a key
under one of them in record content is never an action's output to prefer.
"""

import pytest

from agent_actions.input.preprocessing.filtering.evaluator import GuardEvaluator
from agent_actions.processing.guard_context import build_guard_context
from agent_actions.processing.prepared_task import PreparationContext
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


class TestAFirstStageRecordsSourceIsNotNestedTwice:
    """A first-stage action's source is the record itself. The namespace builder unwraps a
    record's own ``source``, but it was handed the bare content instead — so a record that
    had one got it wrapped a second time and ``source.field`` resolved to nothing, silently.

    Only reachable once a guard stops reading the record's carried copy: the copy is
    correctly shaped, so it was overriding the doubled one and a first-stage guard worked by
    accident. Pinned separately because either defect alone changes the answer.
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
