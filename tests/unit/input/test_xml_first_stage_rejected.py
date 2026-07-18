"""XML first-stage input is rejected with a clear error, not a broken record.

XmlLoader.process returns an ET.Element (the parse tree), not rows, so batch XML fell to a
{content: <ET.Element>} fallback (unwrapped, unstamped) and online XML emitted an element that
failed cryptically at the storage boundary. XML first-stage is unused and has no validated row
shape, so both branches fail loud with an actionable message instead of a broken record.
"""

from pathlib import Path

import pytest

# Pre-load the workflow package to break a pre-existing import-order cycle.
import agent_actions.workflow.coordinator  # noqa: F401
from agent_actions.errors import AgentActionsError
from agent_actions.input.preprocessing.staging.initial_pipeline import (
    DataPreparationContext,
    _prepare_batch_data,
    _prepare_online_data,
)


def _xml_ctx(tmp_path: Path) -> DataPreparationContext:
    p = tmp_path / "d.xml"
    p.write_text("<root><item>hello</item><item>world</item></root>", encoding="utf-8")
    return DataPreparationContext(
        content=None,
        file_type=".xml",
        agent_config={},
        file_path=str(p),
        agent_name="a",
    )


def test_batch_xml_is_rejected_with_clear_error(tmp_path):
    with pytest.raises(AgentActionsError, match="not supported"):
        _prepare_batch_data(_xml_ctx(tmp_path))


def test_online_xml_is_rejected_with_clear_error(tmp_path):
    with pytest.raises(AgentActionsError, match="not supported"):
        _prepare_online_data(_xml_ctx(tmp_path))
