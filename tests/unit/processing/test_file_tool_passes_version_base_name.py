"""The FILE tool strategy hands the reconciler the action's version base name.

``reconcile_outputs`` derives a minted row's correlation id from the base name and
falls back to ``action_name`` when given none. That fallback is right for a plain
action and wrong for a versioned one, whose ``action_name`` is ``summarize_1`` —
so the strategy has to read ``version_base_name`` off the config and pass it. A
mutant that stops doing so is invisible to tests that call the reconciler directly.
"""

from unittest.mock import patch

from agent_actions.processing.strategies.file_tool import FileToolStrategy
from agent_actions.processing.types import ProcessingContext
from agent_actions.utils.udf_management.registry import FileUDFResult

UPSTREAM = [{"source_guid": "G0", "version_correlation_id": "corr_abc", "content": {"u": {"x": 1}}}]


def invoke(agent_name, agent_config, count=2):
    """One FILE tool inventing *count* rows, driven through the real strategy."""
    context = ProcessingContext(
        agent_config={"kind": "tool", "granularity": "file", **agent_config},
        agent_name=agent_name,
    )
    context.source_data = UPSTREAM
    raw = FileUDFResult([{"source_index": None, "data": {"o": i}} for i in range(count)])
    with patch(
        "agent_actions.processing.strategies.file_tool.run_dynamic_agent",
        return_value=(raw, True),
    ):
        results = FileToolStrategy().invoke(UPSTREAM, context)
    return [row.get("version_correlation_id") for r in results for row in (r.data or [])]


VERSIONED = {"is_versioned_agent": True, "version_base_name": "summarize"}


class TestAVersionedActionUsesItsBaseName:
    def test_the_branch_number_stays_out_of_the_id(self):
        assert invoke("summarize_1", VERSIONED) == ["corr_abc#summarize#0", "corr_abc#summarize#1"]

    def test_two_branches_of_one_action_mint_matching_ids(self):
        assert invoke("summarize_1", VERSIONED) == invoke("summarize_2", VERSIONED)


class TestAPlainActionUsesItsOwnName:
    def test_its_name_reaches_the_id(self):
        assert invoke("agg_by_region", {}) == [
            "corr_abc#agg_by_region#0",
            "corr_abc#agg_by_region#1",
        ]

    def test_two_sibling_actions_do_not_mint_matching_ids(self):
        assert not set(invoke("agg_by_region", {})) & set(invoke("agg_by_category", {}))
