"""
Integration tests for the deterministic record matcher.

Exercises the FULL pipeline path with a mock StorageBackend:
    build_field_context_with_history()
        -> _load_historical_node()
            -> load_historical_node_data()
                -> _find_target_node_id() + _find_record_by_identifiers()

These tests validate mission-critical matching behavior:
- Ancestor mode (node_id in lineage)
- Merge-parent mode (node_id in lineage_sources)
- Fan-out correctness (same source_guid, different node_ids)
- Prefix disambiguation (extract vs extract_raw_qa)
- No-fallback guarantee (source_guid/parent/root never used for matching)
- HITL gate dedup (the production bug that motivated this change)
"""

import pytest

from agent_actions.input.context.historical import (
    HistoricalDataRequest,
    HistoricalNodeDataLoader,
)
from agent_actions.prompt.context.scope_builder import build_field_context_with_history
from tests.integration.conftest import MockStorageBackend

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def linear_pipeline_storage():
    """Storage with two extract records from different source documents."""
    records = [
        {
            "source_guid": "src-001",
            "node_id": "extract_uuid_aaa",
            "lineage": ["source_uuid_000", "extract_uuid_aaa"],
            "content": {
                "answer_text": "Paris is the capital of France",
                "raw_html": "<p>Paris</p>",
            },
        },
        {
            "source_guid": "src-002",
            "node_id": "extract_uuid_bbb",
            "lineage": ["source_uuid_111", "extract_uuid_bbb"],
            "content": {
                "answer_text": "Berlin is the capital of Germany",
                "raw_html": "<p>Berlin</p>",
            },
        },
    ]
    return MockStorageBackend({"extract": records})


@pytest.fixture
def fanout_storage():
    """Storage with 6 extract records from same source (fan-out)."""
    records = [
        {
            "source_guid": "src-fanout",
            "node_id": f"extract_uuid_{i:03d}",
            "lineage": ["source_uuid_fanout", f"extract_uuid_{i:03d}"],
            "content": {"answer": f"Answer #{i}", "quote": f"Quote from record {i}"},
        }
        for i in range(6)
    ]
    return MockStorageBackend({"extract": records})


@pytest.fixture
def merge_storage():
    """Storage with branch_a and branch_b records for merge testing."""
    return MockStorageBackend(
        {
            "branch_a": [
                {
                    "source_guid": "src-merge",
                    "node_id": "branch_a_uuid_aaa",
                    "lineage": ["source_uuid_m", "branch_a_uuid_aaa"],
                    "content": {"score": 0.85, "label": "positive"},
                }
            ],
            "branch_b": [
                {
                    "source_guid": "src-merge",
                    "node_id": "branch_b_uuid_bbb",
                    "lineage": ["source_uuid_m", "branch_b_uuid_bbb"],
                    "content": {"score": 0.42, "label": "neutral"},
                }
            ],
        }
    )


@pytest.fixture
def hitl_storage():
    """Storage simulating post-HITL dedup: only record #3 survived out of 6."""
    surviving = {
        "source_guid": "src-hitl-003",
        "node_id": "consolidate_uuid_003",
        "lineage": ["source_uuid_003", "extract_uuid_003", "consolidate_uuid_003"],
        "content": {
            "final_source_quote": "The MCP protocol enables tool use",
            "answer": "Answer variant #3",
        },
    }
    return MockStorageBackend({"consolidate": [surviving]})


# ---------------------------------------------------------------------------
# Scenario 1: Ancestor Mode — Linear Pipeline
# ---------------------------------------------------------------------------


class TestAncestorMode:
    """Downstream action resolves upstream fields via lineage chain."""

    def test_loader_returns_correct_content(self, linear_pipeline_storage):
        request = HistoricalDataRequest(
            action_name="extract",
            lineage=[
                "source_uuid_000",
                "extract_uuid_aaa",
                "transform_uuid_xxx",
                "classify_uuid_ccc",
            ],
            source_guid="src-001",
            file_path="/mock/test.json",
            agent_indices={"source": 0, "extract": 1, "transform": 2, "classify": 3},
            storage_backend=linear_pipeline_storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert content is not None
        assert content["answer_text"] == "Paris is the capital of France"

    def test_e2e_context_build_loads_observed_field(self, linear_pipeline_storage):
        """build_field_context_with_history resolves extract.answer_text correctly."""
        current_item = {
            "source_guid": "src-001",
            "node_id": "classify_uuid_ccc",
            "lineage": [
                "source_uuid_000",
                "extract_uuid_aaa",
                "transform_uuid_xxx",
                "classify_uuid_ccc",
            ],
            "content": {},
        }

        field_context = build_field_context_with_history(
            agent_name="classify",
            agent_config={
                "idx": 3,
                "dependencies": [],
                "context_scope": {"observe": ["extract.answer_text"]},
            },
            agent_indices={"source": 0, "extract": 1, "transform": 2, "classify": 3},
            current_item=current_item,
            file_path="/mock/test.json",
            context_scope={"observe": ["extract.answer_text"]},
            storage_backend=linear_pipeline_storage,
        )

        assert "extract" in field_context
        assert field_context["extract"]["answer_text"] == "Paris is the capital of France"


# ---------------------------------------------------------------------------
# Scenario 2: Fan-Out — Same source_guid, Different node_ids
# ---------------------------------------------------------------------------


class TestFanOut:
    """When source fans out, matcher returns the exact ancestor, not first match."""

    def test_resolves_exact_record_not_first(self, fanout_storage):
        """Record #4 must be returned, not record #0 (old fallback behavior)."""
        request = HistoricalDataRequest(
            action_name="extract",
            lineage=[
                "source_uuid_fanout",
                "extract_uuid_004",
                "transform_uuid_t4",
                "classify_uuid_c4",
            ],
            source_guid="src-fanout",
            file_path="/mock/test.json",
            agent_indices={"source": 0, "extract": 1, "transform": 2, "classify": 3},
            storage_backend=fanout_storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert content is not None
        assert content["answer"] == "Answer #4"

    def test_each_branch_resolves_its_own_record(self, fanout_storage):
        """Each downstream branch must resolve to its own ancestor."""
        indices = {"source": 0, "extract": 1, "transform": 2, "classify": 3}

        for i in range(6):
            request = HistoricalDataRequest(
                action_name="extract",
                lineage=[
                    "source_uuid_fanout",
                    f"extract_uuid_{i:03d}",
                    f"transform_uuid_t{i}",
                    f"classify_uuid_c{i}",
                ],
                source_guid="src-fanout",
                file_path="/mock/test.json",
                agent_indices=indices,
                storage_backend=fanout_storage,
            )
            content = HistoricalNodeDataLoader.load_historical_node_data(request)

            assert content is not None, f"Branch {i} should resolve"
            assert content["answer"] == f"Answer #{i}", (
                f"Branch {i} got wrong answer: {content['answer']}"
            )


# ---------------------------------------------------------------------------
# Scenario 3: Merge-Parent Mode — lineage_sources
# ---------------------------------------------------------------------------


class TestMergeParentMode:
    """Merged record resolves branch parents via lineage_sources."""

    def test_branch_in_lineage_uses_ancestor_mode(self, merge_storage):
        """branch_a is in lineage — resolved via Mode 1 (ancestor)."""
        request = HistoricalDataRequest(
            action_name="branch_a",
            lineage=["source_uuid_m", "branch_a_uuid_aaa", "merge_action_uuid_mmm"],
            lineage_sources=["branch_a_uuid_aaa", "branch_b_uuid_bbb"],
            source_guid="src-merge",
            file_path="/mock/test.json",
            agent_indices={"source": 0, "branch_a": 1, "branch_b": 2, "merge_action": 3},
            storage_backend=merge_storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert content is not None
        assert content["score"] == 0.85
        assert content["label"] == "positive"

    def test_branch_not_in_lineage_uses_merge_parent_mode(self, merge_storage):
        """branch_b is NOT in lineage but IS in lineage_sources — resolved via Mode 2."""
        request = HistoricalDataRequest(
            action_name="branch_b",
            lineage=["source_uuid_m", "branch_a_uuid_aaa", "merge_action_uuid_mmm"],
            lineage_sources=["branch_a_uuid_aaa", "branch_b_uuid_bbb"],
            source_guid="src-merge",
            file_path="/mock/test.json",
            agent_indices={"source": 0, "branch_a": 1, "branch_b": 2, "merge_action": 3},
            storage_backend=merge_storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert content is not None
        assert content["score"] == 0.42
        assert content["label"] == "neutral"

    def test_e2e_context_build_with_lineage_sources(self, merge_storage):
        """build_field_context_with_history passes lineage_sources through the full chain."""
        merged_item = {
            "source_guid": "src-merge",
            "node_id": "merge_action_uuid_mmm",
            "lineage": ["source_uuid_m", "branch_a_uuid_aaa", "merge_action_uuid_mmm"],
            "lineage_sources": ["branch_a_uuid_aaa", "branch_b_uuid_bbb"],
            "content": {},
        }

        field_context = build_field_context_with_history(
            agent_name="merge_action",
            agent_config={
                "idx": 3,
                "dependencies": [],
                "context_scope": {"observe": ["branch_b.score", "branch_b.label"]},
            },
            agent_indices={"source": 0, "branch_a": 1, "branch_b": 2, "merge_action": 3},
            current_item=merged_item,
            file_path="/mock/test.json",
            context_scope={"observe": ["branch_b.score", "branch_b.label"]},
            storage_backend=merge_storage,
        )

        assert "branch_b" in field_context, (
            f"Expected branch_b, got keys: {list(field_context.keys())}"
        )
        assert field_context["branch_b"]["score"] == 0.42
        assert field_context["branch_b"]["label"] == "neutral"


# ---------------------------------------------------------------------------
# Scenario 4: Prefix Disambiguation
# ---------------------------------------------------------------------------


class TestPrefixDisambiguation:
    """extract must not match extract_raw_qa's node_id, and vice versa."""

    INDICES = {"source": 0, "extract": 1, "extract_raw_qa": 2, "downstream": 3}

    def test_short_name_does_not_match_longer_action_node(self):
        """'extract' must NOT match a node_id owned by 'extract_raw_qa'."""
        target = HistoricalNodeDataLoader._find_target_node_id(
            action_name="extract",
            lineage=["source_uuid_p", "extract_raw_qa_uuid_long", "downstream_uuid_d"],
            agent_indices=self.INDICES,
        )
        assert target is None

    def test_long_name_matches_its_own_node(self):
        """'extract_raw_qa' correctly matches its own node_id."""
        target = HistoricalNodeDataLoader._find_target_node_id(
            action_name="extract_raw_qa",
            lineage=["source_uuid_p", "extract_raw_qa_uuid_long", "downstream_uuid_d"],
            agent_indices=self.INDICES,
        )
        assert target == "extract_raw_qa_uuid_long"

    def test_both_in_lineage_each_resolves_correctly(self):
        """When both actions are ancestors, each resolves to its own node_id."""
        lineage = [
            "source_uuid_p",
            "extract_uuid_short",
            "extract_raw_qa_uuid_long",
            "downstream_uuid_d",
        ]

        target_e = HistoricalNodeDataLoader._find_target_node_id(
            action_name="extract",
            lineage=lineage,
            agent_indices=self.INDICES,
        )
        target_rq = HistoricalNodeDataLoader._find_target_node_id(
            action_name="extract_raw_qa",
            lineage=lineage,
            agent_indices=self.INDICES,
        )

        assert target_e == "extract_uuid_short"
        assert target_rq == "extract_raw_qa_uuid_long"

    def test_e2e_with_storage(self):
        """Full loader with prefix-colliding actions resolves correctly."""
        storage = MockStorageBackend(
            {
                "extract": [
                    {
                        "source_guid": "src-p",
                        "node_id": "extract_uuid_short",
                        "content": {"type": "extract_result"},
                    }
                ],
                "extract_raw_qa": [
                    {
                        "source_guid": "src-p",
                        "node_id": "extract_raw_qa_uuid_long",
                        "content": {"type": "raw_qa_result"},
                    }
                ],
            }
        )

        lineage = [
            "source_uuid_p",
            "extract_uuid_short",
            "extract_raw_qa_uuid_long",
            "downstream_uuid_d",
        ]

        # extract resolves to extract_result
        content_e = HistoricalNodeDataLoader.load_historical_node_data(
            HistoricalDataRequest(
                action_name="extract",
                lineage=lineage,
                source_guid="src-p",
                file_path="/mock/test.json",
                agent_indices=self.INDICES,
                storage_backend=storage,
            )
        )
        assert content_e is not None
        assert content_e["type"] == "extract_result"

        # extract_raw_qa resolves to raw_qa_result
        content_rq = HistoricalNodeDataLoader.load_historical_node_data(
            HistoricalDataRequest(
                action_name="extract_raw_qa",
                lineage=lineage,
                source_guid="src-p",
                file_path="/mock/test.json",
                agent_indices=self.INDICES,
                storage_backend=storage,
            )
        )
        assert content_rq is not None
        assert content_rq["type"] == "raw_qa_result"


# ---------------------------------------------------------------------------
# Scenario 5: No Fallbacks — Strict Guarantees
# ---------------------------------------------------------------------------


class TestNoFallbacks:
    """source_guid, parent_target_id, root_target_id must NEVER be used for matching."""

    def test_source_guid_match_alone_returns_none(self):
        """source_guid is for logging only — a match on it alone must not return a record."""
        storage = MockStorageBackend(
            {
                "extract": [
                    {
                        "source_guid": "src-001",
                        "node_id": "extract_uuid_wrong",
                        "content": {"field": "WRONG"},
                    }
                ]
            }
        )

        request = HistoricalDataRequest(
            action_name="extract",
            lineage=["source_uuid_000", "transform_uuid_xxx"],  # No extract node
            source_guid="src-001",  # Matches record's source_guid
            file_path="/mock/test.json",
            agent_indices={"source": 0, "extract": 1, "transform": 2},
            storage_backend=storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert content is None

    def test_parent_target_id_match_alone_returns_none(self):
        """parent_target_id is metadata — must not be used for matching."""
        storage = MockStorageBackend(
            {
                "extract": [
                    {
                        "source_guid": "src-001",
                        "node_id": "extract_uuid_wrong",
                        "parent_target_id": "parent-match",
                        "content": {"field": "WRONG"},
                    }
                ]
            }
        )

        request = HistoricalDataRequest(
            action_name="extract",
            lineage=["source_uuid_000", "transform_uuid_xxx"],  # No extract node
            source_guid="src-001",
            file_path="/mock/test.json",
            agent_indices={"source": 0, "extract": 1, "transform": 2},
            parent_target_id="parent-match",  # Matches record
            storage_backend=storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert content is None

    def test_root_target_id_match_alone_returns_none(self):
        """root_target_id is metadata — must not be used for matching."""
        storage = MockStorageBackend(
            {
                "extract": [
                    {
                        "source_guid": "src-001",
                        "node_id": "extract_uuid_wrong",
                        "root_target_id": "root-match",
                        "content": {"field": "WRONG"},
                    }
                ]
            }
        )

        request = HistoricalDataRequest(
            action_name="extract",
            lineage=["source_uuid_000", "transform_uuid_xxx"],  # No extract node
            source_guid="src-001",
            file_path="/mock/test.json",
            agent_indices={"source": 0, "extract": 1, "transform": 2},
            root_target_id="root-match",  # Matches record
            storage_backend=storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert content is None


# ---------------------------------------------------------------------------
# Scenario 6: HITL Gate Dedup — The Production Bug
# ---------------------------------------------------------------------------


class TestHITLGateDedup:
    """The qanalabs_quiz_gen production bug: HITL dedup must be respected downstream.

    Before this fix, the old matcher would silently fall back to source_guid matching,
    returning the surviving record even for lineage chains from rejected branches.
    """

    def test_surviving_record_descendant_resolves(self, hitl_storage):
        """Downstream of the surviving record gets its content."""
        request = HistoricalDataRequest(
            action_name="consolidate",
            lineage=[
                "source_uuid_003",
                "extract_uuid_003",
                "consolidate_uuid_003",
                "generate_question_uuid_gq",
            ],
            source_guid="src-hitl-003",
            file_path="/mock/test.json",
            agent_indices={"source": 0, "extract": 1, "consolidate": 2, "generate_question": 3},
            storage_backend=hitl_storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert content is not None
        assert content["answer"] == "Answer variant #3"

    def test_rejected_record_descendant_gets_none(self, hitl_storage):
        """Downstream of a REJECTED record must get None — no silent fallback.

        This is the core bug. The old matcher would return the surviving record
        because it shared the same source_guid pattern and fell through to
        the source_guid-only fallback tier.
        """
        request = HistoricalDataRequest(
            action_name="consolidate",
            lineage=[
                "source_uuid_000",
                "extract_uuid_000",
                "consolidate_uuid_000",  # This record was REJECTED in HITL
                "generate_question_uuid_rejected",
            ],
            source_guid="src-hitl-000",
            file_path="/mock/test.json",
            agent_indices={"source": 0, "extract": 1, "consolidate": 2, "generate_question": 3},
            storage_backend=hitl_storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert content is None, (
            "Rejected record's descendant must get None. "
            "Old matcher would have silently returned the surviving record via source_guid fallback."
        )

    def test_all_rejected_branches_get_none(self, hitl_storage):
        """All 5 rejected branches (0,1,2,4,5) must get None."""
        indices = {"source": 0, "extract": 1, "consolidate": 2, "generate_question": 3}

        for i in [0, 1, 2, 4, 5]:
            request = HistoricalDataRequest(
                action_name="consolidate",
                lineage=[
                    f"source_uuid_{i:03d}",
                    f"extract_uuid_{i:03d}",
                    f"consolidate_uuid_{i:03d}",
                    f"generate_question_uuid_{i}",
                ],
                source_guid=f"src-hitl-{i:03d}",
                file_path="/mock/test.json",
                agent_indices=indices,
                storage_backend=hitl_storage,
            )
            content = HistoricalNodeDataLoader.load_historical_node_data(request)

            assert content is None, (
                f"Rejected branch {i} should get None but got content: {content}"
            )
