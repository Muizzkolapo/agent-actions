"""Regression tests for chunking defaults pinning.

``docs/reference/data-io/chunking.md`` documents the framework's default
``chunk_size`` and ``overlap``. The values must match the canonical defaults
in ``agent_actions/output/response/config_fields.py``. If a future refactor
moves the defaults without updating the doc table, these tests fail loudly.

These constants are also surfaced via ``get_default(...)`` and consumed by
``agent_actions/input/preprocessing/staging/initial_pipeline.py`` and the
project-init template at ``agent_actions/config/init.py``.
"""

from __future__ import annotations

from agent_actions.output.response.config_fields import SIMPLE_CONFIG_FIELDS, get_default


def test_chunk_size_default_pinned_at_300() -> None:
    """``chunk_size=300`` is the documented default in chunking.md."""
    assert SIMPLE_CONFIG_FIELDS["chunk_size"] == 300
    assert get_default("chunk_size") == 300


def test_chunk_overlap_default_pinned_at_10() -> None:
    """``overlap=10`` is the documented default in chunking.md.

    Note the field rename at the boundary: user YAML uses ``overlap`` (inside
    ``chunk_config``), but the framework's internal config field is
    ``chunk_overlap`` — both names route to the same value via the loader
    in ``initial_pipeline.py:336``.
    """
    assert SIMPLE_CONFIG_FIELDS["chunk_overlap"] == 10
    assert get_default("chunk_overlap") == 10
