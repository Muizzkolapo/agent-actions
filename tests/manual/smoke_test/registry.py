from __future__ import annotations

from tests.manual.smoke_test.checks.output_structure import OutputStructure
from tests.manual.smoke_test.checks.pipeline import PipelineCompleted
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
]
