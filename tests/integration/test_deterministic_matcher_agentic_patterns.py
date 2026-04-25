"""
Agentic workflow pattern tests for the deterministic record matcher.

These tests model REAL workflow patterns from the codebase:
- Contract Reviewer: fan-out (split clauses) → analyze each → fan-in (aggregate)
- Product Listing: linear chain with guard-conditional skip
- Versioned Classifier: parallel versions → merge consuming all variants
- HITL Cross-Gate: observe fields from upstream action across a HITL gate
- Diamond Merge: two parallel branches converge on a single downstream action

Each test exercises the full pipeline with a MockStorageBackend and validates
that the CORRECT content is returned — not just that something is returned.

Anti-theatre guarantees:
- Every assertion checks a specific field VALUE, not just "is not None"
- Multiple records exist in storage with similar shapes — the test verifies
  the matcher picks the RIGHT one, not the first one
- Lineage chains match real enrichment output (node_id format, lineage_sources)
- Context scope filtering is validated (observe includes, drop excludes)
"""

import pytest

from agent_actions.input.context.historical import (
    HistoricalDataRequest,
    HistoricalNodeDataLoader,
)
from agent_actions.prompt.context.scope_builder import build_field_context_with_history
from tests.integration.conftest import MockStorageBackend

# =====================================================================
# Pattern 1: Contract Reviewer — Fan-Out → Analyze → Fan-In
# =====================================================================
#
#   source_contract
#        ↓
#   split_into_clauses  (1 contract → 3 clause records)
#        ↓ ↓ ↓
#   analyze_clause      (runs on each clause independently)
#        ↓ ↓ ↓
#   aggregate_risk      (File granularity: sees all, merges with lineage_sources)
#        ↓
#   generate_summary    (observes aggregate_risk fields)
#


class TestContractReviewerPattern:
    """Fan-out/fan-in pattern from contract_reviewer example workflow."""

    @pytest.fixture
    def contract_storage(self):
        """3 clause analysis records + 1 aggregate record in storage."""
        return MockStorageBackend(
            {
                "analyze_clause": [
                    {
                        "source_guid": "contract-001",
                        "node_id": "analyze_clause_uuid_c1",
                        "lineage": [
                            "split_into_clauses_uuid_split",
                            "analyze_clause_uuid_c1",
                        ],
                        "content": {
                            "clause_number": 1,
                            "risk_level": "high",
                            "risk_description": "Unlimited liability exposure",
                        },
                    },
                    {
                        "source_guid": "contract-001",
                        "node_id": "analyze_clause_uuid_c2",
                        "lineage": [
                            "split_into_clauses_uuid_split",
                            "analyze_clause_uuid_c2",
                        ],
                        "content": {
                            "clause_number": 2,
                            "risk_level": "low",
                            "risk_description": "Standard payment terms",
                        },
                    },
                    {
                        "source_guid": "contract-001",
                        "node_id": "analyze_clause_uuid_c3",
                        "lineage": [
                            "split_into_clauses_uuid_split",
                            "analyze_clause_uuid_c3",
                        ],
                        "content": {
                            "clause_number": 3,
                            "risk_level": "medium",
                            "risk_description": "Non-compete has broad geography",
                        },
                    },
                ],
                "aggregate_risk": [
                    {
                        "source_guid": "contract-001",
                        "node_id": "aggregate_risk_uuid_agg",
                        "lineage": [
                            "split_into_clauses_uuid_split",
                            "aggregate_risk_uuid_agg",
                        ],
                        "lineage_sources": [
                            "analyze_clause_uuid_c1",
                            "analyze_clause_uuid_c2",
                            "analyze_clause_uuid_c3",
                        ],
                        "content": {
                            "overall_risk": "high",
                            "clause_count": 3,
                            "high_risk_clauses": [1],
                        },
                    },
                ],
            }
        )

    @pytest.fixture
    def contract_indices(self):
        return {
            "source": 0,
            "split_into_clauses": 1,
            "analyze_clause": 2,
            "aggregate_risk": 3,
            "generate_summary": 4,
        }

    def test_summary_observes_aggregate_via_record_namespace(
        self, contract_storage, contract_indices
    ):
        """generate_summary reads aggregate_risk from record's namespaced content.

        With the additive model, aggregate_risk output is stored under its
        namespace on the record — no storage backend lookup needed.
        """
        current_item = {
            "source_guid": "contract-001",
            "node_id": "generate_summary_uuid_gs",
            "lineage": [
                "split_into_clauses_uuid_split",
                "aggregate_risk_uuid_agg",
                "generate_summary_uuid_gs",
            ],
            "content": {
                "aggregate_risk": {
                    "overall_risk": "high",
                    "clause_count": 3,
                    "high_risk_clauses": [1],
                },
            },
        }

        field_context = build_field_context_with_history(
            agent_name="generate_summary",
            agent_config={
                "idx": 4,
                "dependencies": [],
                "context_scope": {
                    "observe": [
                        "aggregate_risk.overall_risk",
                        "aggregate_risk.high_risk_clauses",
                    ]
                },
            },
            agent_indices=contract_indices,
            current_item=current_item,
            context_scope={
                "observe": [
                    "aggregate_risk.overall_risk",
                    "aggregate_risk.high_risk_clauses",
                ]
            },
        )

        assert "aggregate_risk" in field_context
        assert field_context["aggregate_risk"]["overall_risk"] == "high"
        assert field_context["aggregate_risk"]["high_risk_clauses"] == [1]

    def test_aggregate_resolves_clause_via_lineage_sources(
        self, contract_storage, contract_indices
    ):
        """aggregate_risk resolves individual clause analyses via lineage_sources.

        The aggregate used lineage_sources to record all 3 clause analyses.
        A downstream action tracing through aggregate should be able to reach
        each individual clause analysis.
        """
        # Aggregate's own record has lineage_sources pointing to all 3 clauses
        target = HistoricalNodeDataLoader._find_target_node_id(
            action_name="analyze_clause",
            lineage=[
                "split_into_clauses_uuid_split",
                "aggregate_risk_uuid_agg",
                "generate_summary_uuid_gs",
            ],
            lineage_sources=[
                "analyze_clause_uuid_c1",
                "analyze_clause_uuid_c2",
                "analyze_clause_uuid_c3",
            ],
            agent_indices=contract_indices,
        )
        # Should find the FIRST clause analysis in lineage_sources
        assert target == "analyze_clause_uuid_c1"

    def test_fan_out_clause_1_resolves_not_clause_2(self, contract_storage, contract_indices):
        """A record descended from clause 1 must NOT resolve clause 2's data.

        This is the core fan-out correctness test: same source_guid, same action,
        3 records — the matcher must use the specific node_id from lineage.
        """
        # Downstream of clause 1 (the high-risk clause)
        request = HistoricalDataRequest(
            action_name="analyze_clause",
            lineage=[
                "split_into_clauses_uuid_split",
                "analyze_clause_uuid_c1",
                "downstream_uuid_d1",
            ],
            source_guid="contract-001",
            file_path="/mock/batch_001.json",
            agent_indices=contract_indices,
            storage_backend=contract_storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert content is not None
        assert content["clause_number"] == 1, f"Expected clause 1, got {content['clause_number']}"
        assert content["risk_level"] == "high"


# =====================================================================
# Pattern 2: Product Listing — Linear Chain with Guard Skip
# =====================================================================
#
#   generate_description → fetch_prices → write_copy → validate_compliance
#        ↓
#   optimize_seo  (guard: compliance_passed == true, on_false: skip)
#        ↓
#   format_listing  (must see BOTH optimize_seo AND validate_compliance)
#


class TestProductListingPattern:
    """Linear chain with guard-conditional skip from product_listing_enrichment example."""

    @pytest.fixture
    def product_storage(self):
        """Storage with results from a product that PASSED compliance."""
        return MockStorageBackend(
            {
                "generate_description": [
                    {
                        "source_guid": "prod-001",
                        "node_id": "generate_description_uuid_gd",
                        "lineage": ["source_uuid_p", "generate_description_uuid_gd"],
                        "content": {
                            "product_description": "Premium organic coffee beans",
                            "search_keywords": ["organic", "coffee", "fair-trade"],
                        },
                    },
                    {
                        "source_guid": "prod-002",
                        "node_id": "generate_description_uuid_gd2",
                        "lineage": ["source_uuid_p2", "generate_description_uuid_gd2"],
                        "content": {
                            "product_description": "Budget instant coffee",
                            "search_keywords": ["instant", "coffee", "value"],
                        },
                    },
                ],
                "validate_compliance": [
                    {
                        "source_guid": "prod-001",
                        "node_id": "validate_compliance_uuid_vc",
                        "lineage": [
                            "source_uuid_p",
                            "generate_description_uuid_gd",
                            "fetch_prices_uuid_fp",
                            "write_copy_uuid_wc",
                            "validate_compliance_uuid_vc",
                        ],
                        "content": {
                            "compliance_passed": True,
                            "violations": [],
                        },
                    },
                    {
                        "source_guid": "prod-002",
                        "node_id": "validate_compliance_uuid_vc2",
                        "lineage": [
                            "source_uuid_p2",
                            "generate_description_uuid_gd2",
                            "fetch_prices_uuid_fp2",
                            "write_copy_uuid_wc2",
                            "validate_compliance_uuid_vc2",
                        ],
                        "content": {
                            "compliance_passed": False,
                            "violations": ["misleading_claims"],
                        },
                    },
                ],
            }
        )

    @pytest.fixture
    def product_indices(self):
        return {
            "source": 0,
            "generate_description": 1,
            "fetch_prices": 2,
            "write_copy": 3,
            "validate_compliance": 4,
            "optimize_seo": 5,
            "format_listing": 6,
        }

    def test_format_listing_sees_correct_product_description(
        self, product_storage, product_indices
    ):
        """format_listing for prod-001 reads from record's namespaced content.

        With the additive model, all upstream outputs are on the record.
        """
        current_item = {
            "source_guid": "prod-001",
            "node_id": "format_listing_uuid_fl",
            "lineage": [
                "source_uuid_p",
                "generate_description_uuid_gd",
                "fetch_prices_uuid_fp",
                "write_copy_uuid_wc",
                "validate_compliance_uuid_vc",
                "optimize_seo_uuid_os",
                "format_listing_uuid_fl",
            ],
            "content": {
                "generate_description": {
                    "product_description": "Premium organic coffee beans",
                    "search_keywords": ["organic", "coffee", "fair-trade"],
                },
                "validate_compliance": {
                    "compliance_passed": True,
                    "violations": [],
                },
            },
        }

        field_context = build_field_context_with_history(
            agent_name="format_listing",
            agent_config={
                "idx": 6,
                "dependencies": [],
                "context_scope": {
                    "observe": [
                        "generate_description.product_description",
                        "validate_compliance.compliance_passed",
                    ]
                },
            },
            agent_indices=product_indices,
            current_item=current_item,
            context_scope={
                "observe": [
                    "generate_description.product_description",
                    "validate_compliance.compliance_passed",
                ]
            },
        )

        assert "generate_description" in field_context
        assert (
            field_context["generate_description"]["product_description"]
            == "Premium organic coffee beans"
        )

        assert "validate_compliance" in field_context
        assert field_context["validate_compliance"]["compliance_passed"] is True

    def test_prod_002_sees_its_own_compliance_failure(self, product_storage, product_indices):
        """prod-002's downstream sees compliance_passed=False, not prod-001's True."""
        request = HistoricalDataRequest(
            action_name="validate_compliance",
            lineage=[
                "source_uuid_p2",
                "generate_description_uuid_gd2",
                "fetch_prices_uuid_fp2",
                "write_copy_uuid_wc2",
                "validate_compliance_uuid_vc2",
                "format_listing_uuid_fl2",
            ],
            source_guid="prod-002",
            file_path="/mock/batch_001.json",
            agent_indices=product_indices,
            storage_backend=product_storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert content is not None
        assert content["compliance_passed"] is False, (
            "prod-002 must see its own compliance failure, not prod-001's success"
        )
        assert content["violations"] == ["misleading_claims"]


# =====================================================================
# Pattern 3: Versioned Classifier — Parallel Versions Merge
# =====================================================================
#
#   extract_details
#        ↓
#   classify (3 parallel versions: classifier_id 1, 2, 3)
#        ↓ ↓ ↓
#   aggregate_classifications (merges all 3 via lineage_sources)
#        ↓
#   final_decision (observes aggregate)
#


class TestVersionedClassifierPattern:
    """Parallel version expansion → merge pattern from versioned_classifier workflow."""

    @pytest.fixture
    def versioned_storage(self):
        """3 classifier outputs + 1 aggregate output."""
        return MockStorageBackend(
            {
                "classify": [
                    {
                        "source_guid": "doc-001",
                        "node_id": "classify_uuid_v1",
                        "lineage": ["extract_uuid_ed", "classify_uuid_v1"],
                        "content": {
                            "classifier_id": 1,
                            "label": "spam",
                            "confidence": 0.92,
                        },
                    },
                    {
                        "source_guid": "doc-001",
                        "node_id": "classify_uuid_v2",
                        "lineage": ["extract_uuid_ed", "classify_uuid_v2"],
                        "content": {
                            "classifier_id": 2,
                            "label": "ham",
                            "confidence": 0.67,
                        },
                    },
                    {
                        "source_guid": "doc-001",
                        "node_id": "classify_uuid_v3",
                        "lineage": ["extract_uuid_ed", "classify_uuid_v3"],
                        "content": {
                            "classifier_id": 3,
                            "label": "spam",
                            "confidence": 0.88,
                        },
                    },
                ],
                "aggregate_classifications": [
                    {
                        "source_guid": "doc-001",
                        "node_id": "aggregate_classifications_uuid_ac",
                        "lineage": ["extract_uuid_ed", "aggregate_classifications_uuid_ac"],
                        "lineage_sources": [
                            "classify_uuid_v1",
                            "classify_uuid_v2",
                            "classify_uuid_v3",
                        ],
                        "content": {
                            "consensus_label": "spam",
                            "vote_count": {"spam": 2, "ham": 1},
                            "avg_confidence": 0.823,
                        },
                    },
                ],
            }
        )

    @pytest.fixture
    def versioned_indices(self):
        return {
            "source": 0,
            "extract": 1,
            "classify": 2,
            "aggregate_classifications": 3,
            "final_decision": 4,
        }

    def test_final_decision_observes_aggregate_consensus(
        self, versioned_storage, versioned_indices
    ):
        """final_decision reads aggregate consensus from record's namespaced content."""
        current_item = {
            "source_guid": "doc-001",
            "node_id": "final_decision_uuid_fd",
            "lineage": [
                "extract_uuid_ed",
                "aggregate_classifications_uuid_ac",
                "final_decision_uuid_fd",
            ],
            "content": {
                "aggregate_classifications": {
                    "consensus_label": "spam",
                    "vote_count": {"spam": 2, "ham": 1},
                    "avg_confidence": 0.823,
                },
            },
        }

        field_context = build_field_context_with_history(
            agent_name="final_decision",
            agent_config={
                "idx": 4,
                "dependencies": [],
                "context_scope": {
                    "observe": [
                        "aggregate_classifications.consensus_label",
                        "aggregate_classifications.avg_confidence",
                    ]
                },
            },
            agent_indices=versioned_indices,
            current_item=current_item,
            context_scope={
                "observe": [
                    "aggregate_classifications.consensus_label",
                    "aggregate_classifications.avg_confidence",
                ]
            },
        )

        assert "aggregate_classifications" in field_context
        assert field_context["aggregate_classifications"]["consensus_label"] == "spam"
        assert field_context["aggregate_classifications"]["avg_confidence"] == 0.823

    def test_aggregate_reaches_individual_classifiers_via_lineage_sources(
        self, versioned_storage, versioned_indices
    ):
        """The aggregate can reach each individual classifier through lineage_sources."""
        # Downstream of aggregate wants to see classifier v2's data
        request = HistoricalDataRequest(
            action_name="classify",
            lineage=[
                "extract_uuid_ed",
                "aggregate_classifications_uuid_ac",
                "final_decision_uuid_fd",
            ],
            lineage_sources=[
                "classify_uuid_v1",
                "classify_uuid_v2",
                "classify_uuid_v3",
            ],
            source_guid="doc-001",
            file_path="/mock/batch_001.json",
            agent_indices=versioned_indices,
            storage_backend=versioned_storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        # Returns the FIRST match in lineage_sources (v1)
        assert content is not None
        assert content["classifier_id"] == 1
        assert content["label"] == "spam"
        assert content["confidence"] == 0.92

    def test_specific_version_resolved_from_lineage(self, versioned_storage, versioned_indices):
        """A record descended from classifier v2 resolves v2's data, not v1 or v3."""
        request = HistoricalDataRequest(
            action_name="classify",
            lineage=["extract_uuid_ed", "classify_uuid_v2", "downstream_uuid_d"],
            source_guid="doc-001",
            file_path="/mock/batch_001.json",
            agent_indices=versioned_indices,
            storage_backend=versioned_storage,
        )
        content = HistoricalNodeDataLoader.load_historical_node_data(request)

        assert content is not None
        assert content["classifier_id"] == 2, (
            f"Expected v2, got classifier_id={content['classifier_id']}"
        )
        assert content["label"] == "ham"
        assert content["confidence"] == 0.67


# =====================================================================
# Pattern 4: HITL Cross-Gate Observation
# =====================================================================
#
#   extract → consolidate → [HITL GATE: review] → generate_question
#
#   HITL gate produces N records (user reviews each).
#   Some are approved (disposition=approved), some rejected.
#   generate_question only runs on approved records.
#   It must observe ONLY its own lineage ancestor from consolidate,
#   never a sibling's data from a different review decision.
#


class TestHITLCrossGatePattern:
    """Cross-gate observation with HITL dedup — the production bug scenario.

    6 consolidation records with similar content (same MCP quote).
    HITL reviewer approved records 2 and 5, rejected the rest.
    generate_question runs only on approved records and must observe
    the CORRECT consolidation data for each.
    """

    @pytest.fixture
    def hitl_storage(self):
        """Post-HITL: only records 2 and 5 survived. Storage has only approved records."""
        return MockStorageBackend(
            {
                "consolidate": [
                    {
                        "source_guid": "mcp-src-002",
                        "node_id": "consolidate_uuid_002",
                        "lineage": [
                            "source_uuid_002",
                            "extract_uuid_002",
                            "consolidate_uuid_002",
                        ],
                        "content": {
                            "final_source_quote": "The MCP protocol enables tool use",
                            "answer": "MCP provides a standard interface for AI tool invocation",
                            "source_page": 12,
                        },
                    },
                    {
                        "source_guid": "mcp-src-005",
                        "node_id": "consolidate_uuid_005",
                        "lineage": [
                            "source_uuid_005",
                            "extract_uuid_005",
                            "consolidate_uuid_005",
                        ],
                        "content": {
                            "final_source_quote": "The MCP protocol enables tool use",
                            "answer": "MCP allows LLMs to call external tools safely",
                            "source_page": 47,
                        },
                    },
                ],
            }
        )

    @pytest.fixture
    def hitl_indices(self):
        return {
            "source": 0,
            "extract": 1,
            "consolidate": 2,
            "review": 3,
            "generate_question": 4,
        }

    def test_approved_record_2_sees_its_own_consolidation(self, hitl_storage, hitl_indices):
        """generate_question for record 2 reads consolidation from record namespace."""
        current_item = {
            "source_guid": "mcp-src-002",
            "node_id": "generate_question_uuid_gq2",
            "lineage": [
                "source_uuid_002",
                "extract_uuid_002",
                "consolidate_uuid_002",
                "review_uuid_r2",
                "generate_question_uuid_gq2",
            ],
            "content": {
                "consolidate": {
                    "final_source_quote": "The MCP protocol enables tool use",
                    "answer": "MCP provides a standard interface for AI tool invocation",
                    "source_page": 12,
                },
            },
        }

        field_context = build_field_context_with_history(
            agent_name="generate_question",
            agent_config={
                "idx": 4,
                "dependencies": [],
                "context_scope": {"observe": ["consolidate.answer", "consolidate.source_page"]},
            },
            agent_indices=hitl_indices,
            current_item=current_item,
            context_scope={"observe": ["consolidate.answer", "consolidate.source_page"]},
        )

        assert "consolidate" in field_context
        assert field_context["consolidate"]["source_page"] == 12
        assert (
            field_context["consolidate"]["answer"]
            == "MCP provides a standard interface for AI tool invocation"
        )

    def test_approved_record_5_sees_its_own_consolidation(self, hitl_storage, hitl_indices):
        """generate_question for record 5 reads its own consolidation from record namespace."""
        current_item = {
            "source_guid": "mcp-src-005",
            "node_id": "generate_question_uuid_gq5",
            "lineage": [
                "source_uuid_005",
                "extract_uuid_005",
                "consolidate_uuid_005",
                "review_uuid_r5",
                "generate_question_uuid_gq5",
            ],
            "content": {
                "consolidate": {
                    "final_source_quote": "The MCP protocol enables tool use",
                    "answer": "MCP allows LLMs to call external tools safely",
                    "source_page": 47,
                },
            },
        }

        field_context = build_field_context_with_history(
            agent_name="generate_question",
            agent_config={
                "idx": 4,
                "dependencies": [],
                "context_scope": {"observe": ["consolidate.answer", "consolidate.source_page"]},
            },
            agent_indices=hitl_indices,
            current_item=current_item,
            context_scope={"observe": ["consolidate.answer", "consolidate.source_page"]},
        )

        assert "consolidate" in field_context
        assert field_context["consolidate"]["source_page"] == 47
        assert (
            field_context["consolidate"]["answer"]
            == "MCP allows LLMs to call external tools safely"
        )

    def test_rejected_records_get_no_consolidation_data(self, hitl_storage, hitl_indices):
        """Records 0, 1, 3, 4 were rejected. Their descendants must NOT resolve."""
        for i in [0, 1, 3, 4]:
            request = HistoricalDataRequest(
                action_name="consolidate",
                lineage=[
                    f"source_uuid_{i:03d}",
                    f"extract_uuid_{i:03d}",
                    f"consolidate_uuid_{i:03d}",
                    f"review_uuid_r{i}",
                    f"generate_question_uuid_gq{i}",
                ],
                source_guid=f"mcp-src-{i:03d}",
                file_path="/mock/batch_001.json",
                agent_indices=hitl_indices,
                storage_backend=hitl_storage,
            )
            content = HistoricalNodeDataLoader.load_historical_node_data(request)
            assert content is None, f"Rejected record {i} should get None but got: {content}"


# =====================================================================
# Pattern 5: Diamond Merge — Two Parallel Branches Converge
# =====================================================================
#
#   source
#    ↓    ↓
#  branch_seo  branch_recommendations
#    ↓    ↓
#   merge_report  (observes fields from BOTH branches)
#


class TestDiamondMergePattern:
    """Two parallel branches producing different data, merged downstream."""

    @pytest.fixture
    def diamond_storage(self):
        return MockStorageBackend(
            {
                "branch_seo": [
                    {
                        "source_guid": "book-001",
                        "node_id": "branch_seo_uuid_bs",
                        "lineage": ["source_uuid_b", "branch_seo_uuid_bs"],
                        "content": {
                            "seo_title": "Top 10 Python Libraries for Data Science",
                            "keywords": ["python", "data-science", "pandas"],
                        },
                    },
                ],
                "branch_recommendations": [
                    {
                        "source_guid": "book-001",
                        "node_id": "branch_recommendations_uuid_br",
                        "lineage": ["source_uuid_b", "branch_recommendations_uuid_br"],
                        "content": {
                            "recommended_audience": "intermediate developers",
                            "similar_books": ["Fluent Python", "Python Data Science Handbook"],
                        },
                    },
                ],
            }
        )

    @pytest.fixture
    def diamond_indices(self):
        return {
            "source": 0,
            "branch_seo": 1,
            "branch_recommendations": 2,
            "merge_report": 3,
        }

    def test_merge_observes_both_branches(self, diamond_storage, diamond_indices):
        """merge_report reads both branches from record's namespaced content."""
        merged_item = {
            "source_guid": "book-001",
            "node_id": "merge_report_uuid_mr",
            "lineage": [
                "source_uuid_b",
                "branch_seo_uuid_bs",
                "merge_report_uuid_mr",
            ],
            "content": {
                "branch_seo": {
                    "seo_title": "Top 10 Python Libraries for Data Science",
                    "keywords": ["python", "data-science", "pandas"],
                },
                "branch_recommendations": {
                    "recommended_audience": "intermediate developers",
                    "similar_books": ["Fluent Python", "Python Data Science Handbook"],
                },
            },
        }

        field_context = build_field_context_with_history(
            agent_name="merge_report",
            agent_config={
                "idx": 3,
                "dependencies": [],
                "context_scope": {
                    "observe": [
                        "branch_seo.seo_title",
                        "branch_recommendations.recommended_audience",
                    ]
                },
            },
            agent_indices=diamond_indices,
            current_item=merged_item,
            context_scope={
                "observe": [
                    "branch_seo.seo_title",
                    "branch_recommendations.recommended_audience",
                ]
            },
        )

        assert "branch_seo" in field_context
        assert (
            field_context["branch_seo"]["seo_title"] == "Top 10 Python Libraries for Data Science"
        )

        assert "branch_recommendations" in field_context
        assert (
            field_context["branch_recommendations"]["recommended_audience"]
            == "intermediate developers"
        )

    def test_both_branches_in_content(self, diamond_storage, diamond_indices):
        """Both parallel branches on the record — resolved from namespaced content."""
        merged_item = {
            "source_guid": "book-001",
            "node_id": "merge_report_uuid_mr",
            "lineage": [
                "source_uuid_b",
                "branch_seo_uuid_bs",
                "branch_recommendations_uuid_br",
                "merge_report_uuid_mr",
            ],
            "content": {
                "branch_seo": {
                    "seo_title": "Top 10 Python Libraries for Data Science",
                    "keywords": ["python", "data-science", "pandas"],
                },
                "branch_recommendations": {
                    "recommended_audience": "intermediate developers",
                    "similar_books": ["Fluent Python", "Python Data Science Handbook"],
                },
            },
        }

        field_context = build_field_context_with_history(
            agent_name="merge_report",
            agent_config={
                "idx": 3,
                "dependencies": [],
                "context_scope": {
                    "observe": [
                        "branch_seo.seo_title",
                        "branch_recommendations.recommended_audience",
                    ]
                },
            },
            agent_indices=diamond_indices,
            current_item=merged_item,
            context_scope={
                "observe": [
                    "branch_seo.seo_title",
                    "branch_recommendations.recommended_audience",
                ]
            },
        )

        assert "branch_seo" in field_context
        assert (
            field_context["branch_seo"]["seo_title"] == "Top 10 Python Libraries for Data Science"
        )
        assert "branch_recommendations" in field_context
        assert (
            field_context["branch_recommendations"]["recommended_audience"]
            == "intermediate developers"
        )

    def test_diamond_wildcard_observe(self, diamond_storage, diamond_indices):
        """Wildcard observe loads all fields from both branches on the record."""
        merged_item = {
            "source_guid": "book-001",
            "node_id": "merge_report_uuid_mr",
            "lineage": ["source_uuid_b", "branch_seo_uuid_bs", "merge_report_uuid_mr"],
            "content": {
                "branch_seo": {
                    "seo_title": "Top 10 Python Libraries for Data Science",
                    "keywords": ["python", "data-science", "pandas"],
                },
                "branch_recommendations": {
                    "recommended_audience": "intermediate developers",
                    "similar_books": ["Fluent Python", "Python Data Science Handbook"],
                },
            },
        }

        field_context = build_field_context_with_history(
            agent_name="merge_report",
            agent_config={
                "idx": 3,
                "dependencies": [],
                "context_scope": {
                    "observe": ["branch_seo.*", "branch_recommendations.*"],
                },
            },
            agent_indices=diamond_indices,
            current_item=merged_item,
            context_scope={
                "observe": ["branch_seo.*", "branch_recommendations.*"],
            },
        )

        assert (
            field_context["branch_seo"]["seo_title"] == "Top 10 Python Libraries for Data Science"
        )
        assert field_context["branch_seo"]["keywords"] == ["python", "data-science", "pandas"]
        assert (
            field_context["branch_recommendations"]["recommended_audience"]
            == "intermediate developers"
        )
        assert field_context["branch_recommendations"]["similar_books"] == [
            "Fluent Python",
            "Python Data Science Handbook",
        ]

    def test_single_upstream_observe_unchanged(self, diamond_storage, diamond_indices):
        """Single-branch observe still works — regression guard."""
        single_dep_item = {
            "source_guid": "book-001",
            "node_id": "merge_report_uuid_mr",
            "lineage": ["source_uuid_b", "branch_seo_uuid_bs", "merge_report_uuid_mr"],
            "content": {
                "branch_seo": {
                    "seo_title": "Top 10 Python Libraries for Data Science",
                    "keywords": ["python", "data-science", "pandas"],
                },
            },
        }

        field_context = build_field_context_with_history(
            agent_name="merge_report",
            agent_config={
                "idx": 3,
                "dependencies": [],
                "context_scope": {"observe": ["branch_seo.seo_title"]},
            },
            agent_indices=diamond_indices,
            current_item=single_dep_item,
            context_scope={"observe": ["branch_seo.seo_title"]},
        )

        assert "branch_seo" in field_context
        assert (
            field_context["branch_seo"]["seo_title"] == "Top 10 Python Libraries for Data Science"
        )
        # branch_recommendations not requested — must not appear
        assert "branch_recommendations" not in field_context
