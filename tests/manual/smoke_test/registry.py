from __future__ import annotations

from tests.manual.smoke_test.checks.guards import GuardCheck
from tests.manual.smoke_test.checks.output_structure import OutputStructure
from tests.manual.smoke_test.checks.pipeline import PipelineCompleted
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
            SchemaConformance(),
            GuardCheck(action="optimize_seo", behavior="skip"),
            RepromptCheck(action="generate_description"),
            RepromptCheck(action="write_marketing_copy"),
        ],
    ),
]
