"""FILE-mode observe refs that collide on a bare field name must warn loudly.

When two namespaces share a field name, flat injected keys become
namespace-qualified (``ns.field``). A tool reading the bare key gets nothing,
so the qualification must be announced, not silent.
"""

import logging

import pytest

from agent_actions.prompt.context.scope_application import (
    apply_context_scope_for_records,
)


@pytest.fixture()
def _enable_log_propagation():
    """Ensure the agent_actions logger propagates to root so caplog captures records."""
    aa_logger = logging.getLogger("agent_actions")
    original = aa_logger.propagate
    aa_logger.propagate = True
    yield
    aa_logger.propagate = original


def _records():
    return [
        {
            "source_guid": "g1",
            "content": {"ns1": {"answer": "a", "score": 1}, "ns2": {"answer": "b"}},
        }
    ]


@pytest.mark.usefixtures("_enable_log_propagation")
class TestCollisionQualificationWarning:
    def test_collision_emits_warning_naming_qualified_keys(self, caplog):
        with caplog.at_level(logging.WARNING):
            apply_context_scope_for_records(
                _records(),
                {"observe": ["ns1.answer", "ns2.answer"]},
                action_name="merge_answers",
            )

        messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "ns1.answer" in m and "ns2.answer" in m and "merge_answers" in m for m in messages
        )

    def test_no_collision_emits_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            apply_context_scope_for_records(
                _records(),
                {"observe": ["ns1.answer", "ns2.answer"]},
                action_name="merge_answers",
            )
        baseline = [r.getMessage() for r in caplog.records]
        caplog.clear()

        with caplog.at_level(logging.WARNING):
            apply_context_scope_for_records(
                _records(),
                {"observe": ["ns1.answer", "ns1.score"]},
                action_name="merge_answers",
            )

        messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert baseline, "collision case must produce a warning to compare against"
        assert not any("qualified" in m or "collision" in m for m in messages)

    def test_enriched_records_still_carry_qualified_keys(self, caplog):
        """The warning is advisory — qualified delivery itself must not change."""
        with caplog.at_level(logging.WARNING):
            enriched, skipped = apply_context_scope_for_records(
                _records(),
                {"observe": ["ns1.answer", "ns2.answer"]},
                action_name="merge_answers",
            )

        assert skipped == []
        content = enriched[0]["content"]
        assert content.get("ns1.answer") == "a"
        assert content.get("ns2.answer") == "b"
        assert "answer" not in content
