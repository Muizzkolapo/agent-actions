"""A list of methods is merged by weighted reciprocal rank fusion (k = 60).

Ties are ordered by the best rank any method gave, then by chunk id. One method keeps its
own scores.
"""

from __future__ import annotations

import pytest

from agent_actions.knowledge.search import RRF_K, fused


def test_one_method_keeps_its_own_order_and_scores():
    hits = [("b", 9.5), ("a", 3.0)]
    assert fused({"keyword": hits}, {"keyword": 1.0}) == hits


def test_a_chunk_both_methods_find_ranks_above_one_only_one_finds():
    merged = fused(
        {"keyword": [("a", 5), ("b", 4)], "fuzzy": [("b", 2), ("c", 1)]},
        {"keyword": 1.0, "fuzzy": 1.0},
    )

    assert [cid for cid, _ in merged] == ["b", "a", "c"]
    assert merged[0][1] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))


def test_weights_scale_each_method():
    merged = fused(
        {"keyword": [("a", 5)], "fuzzy": [("b", 5)]},
        {"keyword": 0.3, "fuzzy": 0.7},
    )
    assert [cid for cid, _ in merged] == ["b", "a"]


def test_equal_fused_scores_are_ordered_by_id_when_their_best_ranks_are_equal():
    merged = fused(
        {"keyword": [("z", 1), ("m", 2)], "fuzzy": [("a", 1), ("q", 2)]},
        {"keyword": 1.0, "fuzzy": 1.0},
    )
    assert [cid for cid, _ in merged] == ["a", "z", "m", "q"]


def test_an_equal_fused_score_goes_to_the_better_single_rank_before_the_id():
    # z: keyword rank 1, weight 1 -> 1/61. a: fuzzy rank 62, weight 2 -> 2/122, the same.
    fillers = [(f"f{n:02d}", 1.0) for n in range(61)]
    merged = fused(
        {"keyword": [("z", 1.0)], "fuzzy": [*fillers, ("a", 1.0)]},
        {"keyword": 1.0, "fuzzy": 2.0},
    )
    order = [cid for cid, _ in merged]
    scores = dict(merged)

    assert scores["z"] == scores["a"]
    assert order.index("z") < order.index("a")
