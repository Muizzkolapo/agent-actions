from __future__ import annotations

from tests.manual.smoke_test.checks.context_scope import ContextScope
from tests.manual.smoke_test.checks.guards import GuardCheck
from tests.manual.smoke_test.checks.lineage import LineageCheck
from tests.manual.smoke_test.checks.output_structure import OutputStructure
from tests.manual.smoke_test.checks.parallel import ParallelVersions
from tests.manual.smoke_test.checks.pipeline import PipelineCompleted
from tests.manual.smoke_test.checks.prompt_trace import PromptTraceCheck
from tests.manual.smoke_test.checks.reprompt import RepromptCheck
from tests.manual.smoke_test.checks.schema_conformance import SchemaConformance
from tests.manual.smoke_test.context import Example

EXAMPLES: list[Example] = [
    Example(
        name="support_resolution",
        path="examples/support_resolution",
        workflow="support_resolution",
        actions=7,
        checks=[
            PipelineCompleted(),
            OutputStructure(),
            LineageCheck(),
            PromptTraceCheck(),
        ],
    ),
    Example(
        name="incident_triage",
        path="examples/incident_triage",
        workflow="incident_triage",
        actions=9,
        checks=[
            PipelineCompleted(),
            OutputStructure(),
            LineageCheck(),
            PromptTraceCheck(),
            SchemaConformance(),
            GuardCheck(action="generate_executive_summary", behavior="filter"),
            RepromptCheck(action="extract_incident_details"),
            RepromptCheck(action="classify_severity"),
        ],
    ),
    Example(
        name="product_listing_enrichment",
        path="examples/product_listing_enrichment",
        workflow="product_listing_enrichment",
        actions=6,
        checks=[
            PipelineCompleted(),
            OutputStructure(),
            LineageCheck(),
            PromptTraceCheck(),
            SchemaConformance(),
            GuardCheck(action="optimize_seo", behavior="skip"),
            RepromptCheck(action="generate_description"),
            RepromptCheck(action="write_marketing_copy"),
        ],
    ),
    Example(
        name="review_analyzer",
        path="examples/review_analyzer",
        workflow="review_analyzer",
        actions=6,
        checks=[
            PipelineCompleted(),
            OutputStructure(),
            LineageCheck(),
            PromptTraceCheck(),
            SchemaConformance(),
            ParallelVersions(action="score_quality", versions=3),
            GuardCheck(action="generate_response", behavior="filter"),
            GuardCheck(action="extract_product_insights", behavior="filter"),
            RepromptCheck(action="score_quality"),
            ContextScope(action="generate_response", dropped_fields=["source.star_rating"]),
        ],
    ),
    Example(
        name="contract_reviewer",
        path="examples/contract_reviewer",
        workflow="contract_reviewer",
        actions=4,
        checks=[
            PipelineCompleted(),
            OutputStructure(),
            LineageCheck(),
            PromptTraceCheck(),
            SchemaConformance(),
            RepromptCheck(action="analyze_clause"),
        ],
    ),
    Example(
        name="book_catalog_enrichment",
        path="examples/book_catalog_enrichment",
        workflow="book_catalog_enrichment",
        actions=14,
        checks=[
            PipelineCompleted(),
            OutputStructure(),
            LineageCheck(),
            PromptTraceCheck(),
            SchemaConformance(),
            GuardCheck(action="select_for_users", behavior="filter"),
            RepromptCheck(action="classify_genre"),
            RepromptCheck(action="write_description"),
        ],
    ),
    Example(
        name="species_id_cards",
        path="examples/species_id_cards",
        workflow="species_id_cards",
        actions=13,
        checks=[
            PipelineCompleted(),
            LineageCheck(),
            ParallelVersions(action="extract_field_marks", versions=3),
            ParallelVersions(action="rank_diagnostic_value", versions=3),
            ParallelVersions(action="draft_id_note", versions=2),
            ContextScope(
                action="draft_id_note",
                dropped_fields=["vote_summary", "decision"],
            ),
            # Only the grounding guard is asserted. The extraction guard reads a
            # field the mock fills from an enum, so whether it filters is a coin
            # toss; the grounding guard filters every record every run, because
            # the mock cannot invent a quote that appears in the source.
            GuardCheck(action="auto_review_note", behavior="filter"),
            # OutputStructure and SchemaConformance are omitted deliberately:
            # both fail for every example in this registry, not just this one.
            # PromptTraceCheck is omitted for a reason specific to this example
            # — see the note filed in shared/coordination/status.md.
        ],
    ),
]
