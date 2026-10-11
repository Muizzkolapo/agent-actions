"""Execution order must not depend on the hash seed.

`topological_sort` collected its nodes into a set, so the initial queue -- and therefore the
tie-break between actions at the same dependency level -- came from Python's per-process
string hash randomisation. `determine_execution_order` feeds this graph straight to the
executor, so a workflow could run its actions in a different order run to run with no config
or code change.

The probes run in subprocesses under fixed, differing `PYTHONHASHSEED`s: within one process
the order is simply whatever that seed produced, so only across seeds does the disagreement
show.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

_SEEDS = ("0", "1", "2", "3", "4")


def _sort_under_seed(graph_literal: str, seed: str) -> list[str]:
    source = textwrap.dedent(f"""
        import json
        from agent_actions.utils.graph_utils import topological_sort
        print(json.dumps(topological_sort({graph_literal})))
    """)
    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


class TestOrderIsStableAcrossProcesses:
    def test_independent_nodes_keep_one_order(self):
        """Six actions at the same level produced five different orders across five seeds."""
        graph = "{'alpha': [], 'zebra': [], 'middle': [], 'omega': [], 'delta': [], 'kappa': []}"
        orders = {seed: _sort_under_seed(graph, seed) for seed in _SEEDS}

        distinct = {tuple(o) for o in orders.values()}
        assert len(distinct) == 1, (
            f"{len(distinct)} orders across {len(_SEEDS)} seeds:\n"
            + "\n".join(f"  seed={s}: {o}" for s, o in orders.items())
        )

    def test_a_graph_with_edges_keeps_one_order(self):
        graph = (
            "{'writer': ['reviewer', 'auditor'], 'reviewer': ['publisher'], "
            "'auditor': ['publisher'], 'publisher': []}"
        )
        orders = {seed: _sort_under_seed(graph, seed) for seed in _SEEDS}

        assert len({tuple(o) for o in orders.values()}) == 1, orders


class TestTheTieBreakComesFromDeclarationOrder:
    """Sorting would also be deterministic; the caller's own order says more to a reader.

    It is available here -- unlike the seam in #1105, where the names arrive from a set
    several calls earlier -- because the caller hands this function an ordered mapping.
    Note the function returns `sorted_nodes[::-1]`, a pre-existing convention this change
    does not touch, so independent nodes emerge in reverse declaration order. What matters
    is that the order is derived from the caller's, not from the hash seed.
    """

    def test_independent_nodes_follow_the_declared_order_reversed(self):
        graph = "{'zebra': [], 'alpha': [], 'middle': []}"
        assert _sort_under_seed(graph, "0") == ["middle", "alpha", "zebra"]

    def test_renaming_a_node_does_not_move_it(self):
        """Alphabetical sorting would place `aaa` first; declaration order does not."""
        graph = "{'zebra': [], 'aaa': [], 'middle': []}"
        assert _sort_under_seed(graph, "0") == ["middle", "aaa", "zebra"]

    def test_edges_still_decide_before_the_tie_break(self):
        """Declaration order is the tie-break, not an override: dependencies still win."""
        graph = "{'zebra': ['alpha'], 'alpha': []}"
        assert _sort_under_seed(graph, "0") == ["alpha", "zebra"]
