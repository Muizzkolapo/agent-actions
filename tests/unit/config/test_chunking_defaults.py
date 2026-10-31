"""The chunking defaults the reference table documents, pinned to their source.

A refactor that moves a default without updating the doc table fails here.
"""

from __future__ import annotations

import pytest

from agent_actions.output.response.config_fields import SIMPLE_CONFIG_FIELDS, get_default


@pytest.mark.parametrize(
    ("name", "value"),
    [
        pytest.param("chunk_size", 300, id="chunk_size"),
        pytest.param("chunk_overlap", 10, id="chunk_overlap"),
    ],
)
def test_chunking_default_pinned(name: str, value: int) -> None:
    """The documented default in chunking.md."""
    assert SIMPLE_CONFIG_FIELDS[name] == value
    assert get_default(name) == value
