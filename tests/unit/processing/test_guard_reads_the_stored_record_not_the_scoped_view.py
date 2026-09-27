"""A guard reads the record as stored, not the view ``context_scope`` shaped for the prompt.

FILE mode runs the scope pass first, so the record reaching the guard had ``drop`` applied and
its observed fields flattened to bare keys. Three clauses answered differently per granularity
as a result: ``a1.tier`` (dropped) filtered at FILE and kept at RECORD, while ``n`` and ``url``
(bare names of observed fields) did the reverse. ``prefilter_by_guard`` already holds the
pre-scope records, index-aligned; it read the other list.

``TestTheActionStillReceivesTheRedactedRecord`` is the anti-cheat half: disabling the scope
pass satisfies every clause assertion here and fails those three."""

from copy import deepcopy

import pytest

from agent_actions.processing.prepared_task import PreparationContext
from agent_actions.processing.task_preparer import TaskPreparer
from agent_actions.prompt.context.scope_application import apply_context_scope_for_records
from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

INDICES = {"a1": 0, "a2": 1}
POOL = [{"source_guid": "G0", "content": {"source": {"tier": "secret", "url": "u"}}}]

STORED = {"source": {"tier": "secret", "url": "u"}, "a1": {"tier": "secret", "n": 1}}
DROP_DEP = {"observe": ["source.url", "a1.n"], "drop": ["a1.tier"]}

KEPT = "kept"
FILTERED = "filtered"
SKIPPED = "skipped"


def guard(clause, behavior="filter"):
    return {"clause": clause, "behavior": behavior, "scope": "item"}


def stored(source_guid="G0", **overrides):
    content = deepcopy(STORED)
    content.update(overrides)
    return {"source_guid": source_guid, "content": content}


def file_mode(records, clause, *, scope=DROP_DEP, behavior="filter", pool=POOL):
    """Drive the FILE path the way ``pipeline.py`` does.

    The scope pass runs first, and its output is handed to the guard alongside the
    pre-scope records — matched to the *kept* positions, not to the input list, because
    a record the scope could not place is gone from one list and not the other.

    Returns ``(verdicts, passing, original_passing)``: one verdict per input record by
    ``source_guid``, the records the strategy would receive, and the stored records paired
    with them.
    """
    scoped, scope_skipped = apply_context_scope_for_records(
        [deepcopy(r) for r in records], scope, action_name="a2", source_data=pool
    )
    dropped = {skip["position"] for skip in scope_skipped}
    pre_scope = [deepcopy(r) for at, r in enumerate(records) if at not in dropped]

    config = {"granularity": "file", "context_scope": scope, "guard": guard(clause, behavior)}
    passing, skipped, originals, filtered = prefilter_by_guard(
        scoped,
        config,
        "a2",
        original_data=pre_scope,
        agent_indices=INDICES,
        source_data=pool,
        is_first_stage=False,
    )

    verdicts = {}
    for bucket, verdict in ((passing, KEPT), (skipped, SKIPPED), (filtered, FILTERED)):
        for item in bucket:
            verdicts[item.get("source_guid")] = verdict
    for skip in scope_skipped:
        verdicts.setdefault(skip["source_guid"], "scope-skipped")
    return verdicts, passing, originals


def record_mode(record, clause, *, scope=DROP_DEP, behavior="filter", pool=POOL):
    context = PreparationContext(
        agent_config={
            "granularity": "record",
            "context_scope": scope,
            "guard": guard(clause, behavior),
        },
        agent_name="a2",
        source_data=pool,
        agent_indices=INDICES,
        is_first_stage=False,
    )
    prepared = TaskPreparer().prepare(deepcopy(record), context)
    return KEPT if prepared.should_execute else FILTERED


def file_verdict(clause, **kwargs):
    verdicts, _passing, _originals = file_mode([stored()], clause, **kwargs)
    return verdicts["G0"]


class TestADroppedDependencyFieldStillAnswersAGuard:
    """The reported defect. ``drop: [a1.tier]`` with a guard on ``a1.tier``."""

    def test_a_file_mode_guard_keeps_the_record(self):
        assert file_verdict("a1.tier == 'secret'") == KEPT

    def test_a_record_mode_guard_keeps_it_too(self):
        assert record_mode(stored(), "a1.tier == 'secret'") == KEPT

    def test_a_clause_the_stored_value_does_not_satisfy_still_filters(self):
        """The other half. Without it, the two rows above are satisfied by a guard that
        stopped reading the clause at all."""
        assert file_verdict("a1.tier == 'public'") == FILTERED
        assert record_mode(stored(), "a1.tier == 'public'") == FILTERED


class TestTheActionStillReceivesTheRedactedRecord:
    """``drop`` still does its job. The guard's reading of the stored record does not put
    the dropped field back into what the action is handed.

    This is what separates the fix from deleting the scope pass, which would satisfy every
    clause assertion in this module.
    """

    def test_the_passing_record_has_no_dropped_field(self):
        _verdicts, passing, _originals = file_mode([stored()], "a1.tier == 'secret'")

        assert len(passing) == 1
        assert "tier" not in passing[0]["content"]["a1"]

    def test_the_passing_record_keeps_what_was_not_dropped(self):
        """So the assertion above cannot pass by the namespace being empty or absent."""
        _verdicts, passing, _originals = file_mode([stored()], "a1.tier == 'secret'")

        assert passing[0]["content"]["a1"]["n"] == 1

    def test_the_original_handed_back_is_the_stored_record(self):
        """``original_passing`` feeds the enricher and the skipped tombstones."""
        _verdicts, _passing, originals = file_mode([stored()], "a1.tier == 'secret'")

        assert len(originals) == 1
        assert originals[0]["content"]["a1"] == {"tier": "secret", "n": 1}


class TestNoGranularityAnswersTheSameClauseDifferently:
    """Every clause shape, both surfaces, one expected answer each.

    The expected verdict is spelled out rather than asserted as ``file == record``:
    two paths agreeing on the wrong answer satisfies an equality.
    """

    @pytest.mark.parametrize(
        ("clause", "expected"),
        [
            pytest.param("a1.tier == 'secret'", KEPT, id="dropped-dependency-field"),
            pytest.param("a1.n == 1", KEPT, id="observed-dependency-field"),
            pytest.param("source.tier == 'secret'", KEPT, id="dropped-source-field"),
            pytest.param("source.url == 'u'", KEPT, id="observed-source-field"),
            pytest.param("n == 1", FILTERED, id="bare-name-of-observed-field"),
            pytest.param("url == 'u'", FILTERED, id="bare-name-of-observed-source-field"),
        ],
    )
    def test_both_surfaces_give_the_expected_answer(self, clause, expected):
        assert file_verdict(clause) == expected
        assert record_mode(stored(), clause) == expected


class TestABareObservedNameIsNotAFieldAGuardCanRead:
    """The scope pass flattens an observed field to a bare top-level key for the prompt.
    That made ``n == 1`` resolve in FILE mode and nowhere else. The framework's own error
    names the supported spelling: "use dotted paths (e.g. action_name.field)".
    """

    def test_the_bare_name_does_not_resolve(self):
        assert file_verdict("n == 1") == FILTERED

    def test_the_dotted_name_does(self):
        """Paired, so the row above is not passing because the value is simply wrong."""
        assert file_verdict("a1.n == 1") == KEPT

    def test_a_bare_source_name_does_not_resolve_either(self):
        assert file_verdict("url == 'u'") == FILTERED

    def test_its_dotted_form_does(self):
        assert file_verdict("source.url == 'u'") == KEPT


class TestADropOfAWholeNamespace:
    WILDCARD = {"observe": ["source.url"], "drop": ["a1.*"]}

    def test_a_wildcard_drop_does_not_hide_the_namespace_from_a_guard(self):
        assert file_verdict("a1.tier == 'secret'", scope=self.WILDCARD) == KEPT
        assert record_mode(stored(), "a1.tier == 'secret'", scope=self.WILDCARD) == KEPT

    def test_the_action_still_receives_none_of_it(self):
        _verdicts, passing, _originals = file_mode(
            [stored()], "a1.tier == 'secret'", scope=self.WILDCARD
        )

        assert len(passing) == 1
        assert passing[0]["content"]["a1"] == {}


class TestADropOnAPassthroughField:
    """``drop`` beats ``passthrough`` for the action's view. It still does not decide the
    guard, which is the interaction the two features share a field on."""

    SCOPE = {"observe": ["source.url"], "passthrough": ["a1.tier"], "drop": ["a1.tier"]}

    def test_the_guard_reads_it(self):
        assert file_verdict("a1.tier == 'secret'", scope=self.SCOPE) == KEPT

    def test_the_action_does_not_receive_it(self):
        _verdicts, passing, _originals = file_mode(
            [stored()], "a1.tier == 'secret'", scope=self.SCOPE
        )

        assert len(passing) == 1
        assert "tier" not in passing[0]["content"]["a1"]


class TestSkipBehaviourReadsTheSameRecord:
    """``on_false: skip`` routes elsewhere than ``filter``; both read the stored record."""

    def test_a_dropped_field_satisfying_the_clause_is_not_skipped(self):
        assert file_verdict("a1.tier == 'secret'", behavior="skip") == KEPT

    def test_one_that_does_not_satisfy_it_is_skipped_not_filtered(self):
        assert file_verdict("a1.tier == 'public'", behavior="skip") == SKIPPED


class TestManyRecordsStayAligned:
    """Position pairing is what makes the stored record findable. A record the scope could
    not place leaves the scoped list, so the two lists only line up after that removal.
    """

    def _records(self):
        return [
            stored("G0"),
            {"source_guid": "G1", "content": {"a1": {"tier": "public", "n": 2}}},
            stored("G2", a1={"tier": "secret", "n": 3}),
        ]

    def test_each_record_is_judged_on_its_own_stored_value(self):
        verdicts, _passing, _originals = file_mode(self._records(), "a1.tier == 'secret'")

        assert verdicts["G0"] == KEPT
        assert verdicts["G2"] == KEPT

    def test_the_record_the_scope_could_not_place_never_reaches_the_guard(self):
        """G1 carries no ``source`` namespace and the pool cannot answer for it, so the
        scope pass drops it. Its absence is what the position filtering accounts for."""
        verdicts, _passing, _originals = file_mode(self._records(), "a1.tier == 'secret'")

        assert verdicts["G1"] == "scope-skipped"

    def test_each_passing_record_is_paired_with_its_own_original(self):
        _verdicts, passing, originals = file_mode(self._records(), "a1.tier == 'secret'")

        assert [r["source_guid"] for r in passing] == ["G0", "G2"]
        assert [r["source_guid"] for r in originals] == ["G0", "G2"]
        for scoped, original in zip(passing, originals, strict=True):
            assert "tier" not in scoped["content"]["a1"]
            assert original["content"]["a1"]["tier"] == "secret"

    def test_a_mixed_file_filters_only_the_records_that_fail(self):
        records = [stored("G0"), stored("G2", a1={"tier": "public", "n": 3})]

        verdicts, passing, _originals = file_mode(records, "a1.tier == 'secret'")

        assert verdicts == {"G0": KEPT, "G2": FILTERED}
        assert [r["source_guid"] for r in passing] == ["G0"]


class TestTheGuardContextIsResolvedFromTheStoredRecordToo:
    """Reading the stored record decides two things: the item the clause is evaluated
    against, and the record the guard *context* is resolved from.

    The second only shows on a record the pool cannot place. ``resolve_source_content``
    then falls back to the ``source`` namespace the record itself carries — and the scoped
    copy of that namespace has the drop applied. A resolved framework namespace beats the
    record's own, so building the context from the scoped copy would let the drop decide
    the clause after all.
    """

    POOL = [{"source_guid": "OTHER", "content": {"source": {"tier": "secret", "url": "u"}}}]
    DROP_SOURCE = {"observe": ["source.url"], "drop": ["source.tier"]}

    def _unplaceable(self):
        return {
            "source_guid": "UNPLACEABLE",
            "content": {"source": {"tier": "secret", "url": "u"}, "a1": {"n": 1}},
        }

    def _run(self, clause):
        return file_mode([self._unplaceable()], clause, scope=self.DROP_SOURCE, pool=self.POOL)

    def test_a_dropped_source_field_answers_for_a_record_the_pool_cannot_place(self):
        verdicts, _passing, _originals = self._run("source.tier == 'secret'")

        assert verdicts["UNPLACEABLE"] == KEPT
        assert (
            record_mode(
                self._unplaceable(),
                "source.tier == 'secret'",
                scope=self.DROP_SOURCE,
                pool=self.POOL,
            )
            == KEPT
        )

    def test_the_clause_still_has_to_match(self):
        """So the row above is not satisfied by a guard that stopped reading the clause."""
        verdicts, _passing, _originals = self._run("source.tier == 'public'")

        assert verdicts["UNPLACEABLE"] == FILTERED

    def test_the_action_still_receives_the_redacted_source(self):
        _verdicts, passing, _originals = self._run("source.tier == 'secret'")

        assert len(passing) == 1
        assert "tier" not in passing[0]["content"]["source"]
        assert passing[0]["content"]["source"]["url"] == "u"


class TestWithoutOriginalsTheRecordIsTheOnlyAnswer:
    """RECORD mode reaches ``prefilter_by_guard`` with no originals, and the records it
    passes were never scope-stripped. Nothing there changes."""

    def test_a_call_with_no_originals_reads_the_records_it_was_given(self):
        passing, _skipped, originals, _filtered = prefilter_by_guard(
            [stored()],
            {"granularity": "record", "guard": guard("a1.tier == 'secret'")},
            "a2",
            agent_indices=INDICES,
            source_data=POOL,
            is_first_stage=False,
        )

        assert len(passing) == 1
        assert originals == passing

    def test_a_length_mismatch_is_still_refused(self):
        with pytest.raises(RuntimeError, match="length mismatch"):
            prefilter_by_guard(
                [stored("G0"), stored("G1")],
                {"granularity": "file", "guard": guard("a1.tier == 'secret'")},
                "a2",
                original_data=[stored("G0")],
                agent_indices=INDICES,
                source_data=POOL,
                is_first_stage=False,
            )
