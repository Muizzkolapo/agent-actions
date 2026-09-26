"""A minted row's derived correlation id names the action that minted it.

``_reattach_source_guid`` suffixes the inherited id with the row's output index,
``f"{inherited}#{i}"``. The index carries no action identity, so two different FILE
actions expanding one upstream record mint the same ids, and a fan-in over both keys
on ``version_correlation_id`` and pairs row 0 of one with row 0 of the other.

The suffix cannot simply carry ``action_name``: in a version fan-out the branches are
``summarize_1`` and ``summarize_2``, and their matching rows must keep one id or the
fan-in halves. ``version_base_name`` is the value stable across branches and distinct
across actions; a plain action has none and its own name already is its base.
"""

from agent_actions.utils.udf_management.registry import FileUDFResult
from agent_actions.workflow.merge import merge_records_by_key
from agent_actions.workflow.pipeline_file_mode import reconcile_outputs

UPSTREAM = [{"source_guid": "G0", "version_correlation_id": "corr_abc", "content": {"u": {"x": 1}}}]


def expand(action_name, count, version_base_name=None, upstream=None):
    """One FILE action inventing *count* rows from a single upstream record.

    ``source_index: None`` is a row the tool invented — it names no input, so it is
    minted here and takes the derived id.
    """
    kwargs = {} if version_base_name is None else {"version_base_name": version_base_name}
    rows, _ = reconcile_outputs(
        FileUDFResult([{"source_index": None, "data": {"o": i}} for i in range(count)]),
        action_name,
        upstream if upstream is not None else UPSTREAM,
        **kwargs,
    )
    return rows


def ids(rows):
    return [r.get("version_correlation_id") for r in rows]


def namespaces(record):
    return sorted(k for k in (record.get("content") or {}) if k.startswith("agg_"))


class TestTwoSiblingActionsDoNotPairTheirRows:
    """The reported bug: one upstream record, two FILE actions expanding it."""

    def test_their_ids_are_disjoint(self):
        region = ids(expand("agg_by_region", 2))
        category = ids(expand("agg_by_category", 3))

        assert not set(region) & set(category)

    def test_a_fan_in_over_both_keeps_every_row(self):
        pool = expand("agg_by_region", 2) + expand("agg_by_category", 3)

        assert len(merge_records_by_key(pool)) == len(pool)

    def test_no_row_absorbs_the_other_actions_namespace(self):
        """The damage the collision does: row 0 of each action deep-merged into one
        record carrying both namespaces, which no single action produced."""
        pool = expand("agg_by_region", 2) + expand("agg_by_category", 3)

        assert all(len(namespaces(record)) == 1 for record in merge_records_by_key(pool))


class TestVersionBranchesOfOneActionStillPair:
    """The property the derived id exists for, and the reason the action name alone
    cannot go in the suffix: two branches of one versioned action carry different
    ``action_name`` values and one ``version_base_name``."""

    def test_matching_rows_of_two_branches_share_an_id(self):
        left = ids(expand("summarize_1", 2, version_base_name="summarize"))
        right = ids(expand("summarize_2", 2, version_base_name="summarize"))

        assert left == right

    def test_a_fan_in_over_two_branches_merges_them_pairwise(self):
        pool = expand("summarize_1", 2, version_base_name="summarize") + expand(
            "summarize_2", 2, version_base_name="summarize"
        )

        assert len(merge_records_by_key(pool)) == 2

    def test_a_different_versioned_action_does_not_join_them(self):
        """The guard on the test above: equality must come from sharing a base name,
        not from every versioned expansion collapsing onto one id."""
        summarize = ids(expand("summarize_1", 2, version_base_name="summarize"))
        classify = ids(expand("classify_1", 2, version_base_name="classify"))

        assert not set(summarize) & set(classify)


class TestWhatTheSuffixAlreadyGuaranteed:
    """Held before the change and must still hold — a fix that buys separation by
    collapsing or by exploding the ids cannot pass."""

    def test_rows_of_one_action_stay_distinct(self):
        assert len(set(ids(expand("agg_by_region", 3)))) == 3

    def test_a_row_inheriting_nothing_gets_no_derived_id(self):
        """No inherited id means nothing to derive from; the row must not acquire one
        out of the action name alone."""
        rows = expand("agg_by_region", 2, upstream=[{"source_guid": "G0", "content": {}}])

        assert ids(rows) == [None, None]

    def test_a_chained_aggregation_does_not_reuse_the_ids_above_it(self):
        """A second FILE stage over the first's rows appends a segment rather than
        replacing one, so the two stages never share a key."""
        first = expand("agg_by_region", 2)
        second, _ = reconcile_outputs(
            FileUDFResult([{"source_index": None, "data": {"o": 0}}]), "roll_up", first
        )

        assert not set(ids(first)) & set(ids(second))


class TestAPlainActionUsesItsOwnName:
    """A non-versioned action has no ``version_base_name`` — ``expander.py`` sets that
    key only for versioned agents — and its own name is already its base."""

    def test_it_is_separated_from_a_sibling_by_name_alone(self):
        region = ids(expand("agg_by_region", 2))
        category = ids(expand("agg_by_category", 2))

        assert not set(region) & set(category)

    def test_it_matches_what_it_would_get_from_an_explicit_base(self):
        implicit = ids(expand("agg_by_region", 2))
        explicit = ids(expand("agg_by_region", 2, version_base_name="agg_by_region"))

        assert implicit == explicit
