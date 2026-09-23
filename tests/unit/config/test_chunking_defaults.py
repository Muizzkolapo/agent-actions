"""The chunking defaults the reference table documents, pinned to their source.

A refactor that moves a default without updating the doc table fails here.
"""

from __future__ import annotations

from agent_actions.output.response.config_fields import SIMPLE_CONFIG_FIELDS, get_default


def test_chunk_size_default_pinned_at_300() -> None:
    """``chunk_size=300`` is the documented default in chunking.md."""
    assert SIMPLE_CONFIG_FIELDS["chunk_size"] == 300
    assert get_default("chunk_size") == 300


def test_chunk_overlap_default_pinned_at_10() -> None:
    """``chunk_overlap=10`` is the documented default in chunking.md."""
    assert SIMPLE_CONFIG_FIELDS["chunk_overlap"] == 10
    assert get_default("chunk_overlap") == 10
