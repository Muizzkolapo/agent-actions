"""An action's inferred dependency list must not depend on the hash seed.

`infer_dependencies` returns `(input_sources, context_sources)`. The first comes from the
`dependencies:` key and is a list, so it keeps declaration order. The second is built by
iterating `potential_context_sources`, which is a **set** -- `referenced_actions` comes from
`extract_action_names_from_context_scope`, whose return type is `set`. Python randomises
`str` hashing per process, so that iteration order varies from run to run.

The order reaches `catalog.json`: `tooling/docs/parser.py` builds each action's
`dependencies` as `input_sources + context_sources`. Generating the catalog twice from
identical code produced a different order for 42 of 515 actions, and `dependencies` was the
only key that differed. The edge *set* is stable, so the rendered DAG is not wrong -- but any
diff of two catalogs is noisy, anything content-addressing one sees churn, and a test
asserting on that order would be flaky at a rate set by the hash seed.

These tests run the inference in subprocesses with fixed, differing `PYTHONHASHSEED`s. That
is what makes the RED deterministic rather than flaky: within one process the order is
whatever that process's seed produced, and only across seeds does the disagreement show.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

# Six context sources, none of them an explicit dependency, so all six go through the set.
# Fewer than about four rarely reorders -- a small set often iterates in insertion order by
# luck, which would make this pass on the unfixed code.
_PROBE = textwrap.dedent("""
    import json
    from agent_actions.prompt.context.scope_inference import infer_dependencies

    config = {
        "dependencies": ["aggregate_flashcard"],
        "context_scope": {
            "observe": [
                "generate_flashcard_front.a",
                "generate_flashcard_back.b",
                "source.c",
                "author.d",
                "reviewer.e",
                "scorer.f",
            ]
        },
    }
    names = [
        "aggregate_flashcard",
        "generate_flashcard_front",
        "generate_flashcard_back",
        "author",
        "reviewer",
        "scorer",
    ]
    inputs, context = infer_dependencies(config, names, "probe", validate=False)
    print(json.dumps({"inputs": inputs, "context": context}))
""")

_SEEDS = ("0", "1", "2", "3", "4")


def _infer_under_seed(seed: str) -> dict[str, list[str]]:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


class TestInferredDependencyOrderIsStableAcrossProcesses:
    def test_every_hash_seed_infers_the_same_order(self):
        """The property that matters. Five seeds produced five different orders."""
        results = {seed: _infer_under_seed(seed) for seed in _SEEDS}

        orders = {seed: r["inputs"] + r["context"] for seed, r in results.items()}
        distinct = {tuple(order) for order in orders.values()}
        assert len(distinct) == 1, (
            f"{len(distinct)} different orders across {len(_SEEDS)} hash seeds:\n"
            + "\n".join(f"  seed={s}: {o}" for s, o in orders.items())
        )

    def test_the_explicit_dependency_stays_first_and_in_declaration_order(self):
        """The half that was never broken must not be sorted along with the other."""
        for seed in _SEEDS:
            result = _infer_under_seed(seed)
            assert result["inputs"] == ["aggregate_flashcard"], (
                f"seed={seed}: input sources come from the dependencies: key and keep "
                f"declaration order, but got {result['inputs']}"
            )

    def test_the_auto_inferred_tail_is_sorted(self):
        """Declaration order is unrecoverable here, so sorted is the chosen order.

        `extract_action_names_from_context_scope` returns a `set`, so by the time
        `infer_dependencies` sees these names the order they were written in is already
        gone. Recovering it means changing that helper's return type, which has five
        production callers and tests asserting `== set()`. Sorting the tail is what makes
        the output reproducible without touching any of them.
        """
        context = _infer_under_seed("0")["context"]
        assert context == sorted(context), context
        assert len(context) == 6, f"expected the six non-dependency sources, got {context}"
