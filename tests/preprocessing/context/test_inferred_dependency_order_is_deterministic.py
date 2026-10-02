"""An action's inferred dependency list must not depend on the hash seed.

`context_sources` is built by iterating a set, so its order varies per process, and it
reaches `catalog.json` through `parser.py`'s `input_sources + context_sources`. These tests
run the inference in subprocesses under fixed, differing `PYTHONHASHSEED`s -- within one
process the order is simply whatever that seed produced, so only across seeds does the
disagreement show, and only that makes the failure deterministic rather than flaky.
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


def _run_probe(source: str, seed: str) -> dict[str, list[str]]:
    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


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
        """Sorted is the chosen order for the auto-inferred tail.

        Declaration order is recoverable for the refs that came from `context_scope` --
        `all_field_refs` holds them -- but not for those inferred from the prompt template,
        which arrive from a set. One rule for the whole tail beats a hybrid, and nothing is
        lost: this order was hash-random before.
        """
        context = _infer_under_seed("0")["context"]
        assert context == sorted(context), context
        assert len(context) == 6, f"expected the six non-dependency sources, got {context}"


class TestTheOrderBearingHalvesAreNotSorted:
    """The tail is sorted; the two halves that carry meaning are not.

    A single-dependency probe never reaches either of them, and an implementation that
    sorted them too passed the tests above while changing 68 of 518 catalog actions.
    """

    def test_a_fan_in_tail_keeps_its_declared_order(self):
        """Non-primary dependencies of a fan-in are context sources in YAML order."""
        probe = textwrap.dedent("""
            import json
            from agent_actions.prompt.context.scope_inference import infer_dependencies
            config = {
                "dependencies": ["zebra", "alpha", "middle"],
                "primary_dependency": "zebra",
                "context_scope": {"observe": ["zebra.a", "alpha.b", "middle.c"]},
            }
            names = ["zebra", "alpha", "middle"]
            i, c = infer_dependencies(config, names, "probe", validate=False)
            print(json.dumps({"inputs": i, "context": c}))
        """)
        result = _run_probe(probe, "0")

        assert result["inputs"] == ["zebra"], result
        # Declared zebra, alpha, middle -- so the fan-in tail is alpha, middle, NOT sorted
        # into alpha, middle by luck. Reversing the config would catch a sort; see below.
        assert result["context"] == ["alpha", "middle"], result

    def test_a_fan_in_tail_is_not_alphabetised(self):
        """The discriminating case: declared out of alphabetical order."""
        probe = textwrap.dedent("""
            import json
            from agent_actions.prompt.context.scope_inference import infer_dependencies
            config = {
                "dependencies": ["alpha", "zebra", "middle"],
                "primary_dependency": "alpha",
                "context_scope": {"observe": ["alpha.a", "zebra.b", "middle.c"]},
            }
            names = ["alpha", "zebra", "middle"]
            i, c = infer_dependencies(config, names, "probe", validate=False)
            print(json.dumps({"inputs": i, "context": c}))
        """)
        result = _run_probe(probe, "0")

        assert result["inputs"] == ["alpha"], result
        assert result["context"] == ["zebra", "middle"], (
            "the fan-in tail was alphabetised; it must keep declaration order"
        )

    def test_version_variants_are_expanded_after_the_sort_not_before(self):
        """Sorting after expansion gives x_1, x_10, x_2 -- lexical, not numeric."""
        variants = [f"voter_{n}" for n in range(1, 13)]
        probe = textwrap.dedent(f"""
            import json
            from agent_actions.prompt.context.scope_inference import infer_dependencies
            config = {{
                "dependencies": ["seed_action"],
                "context_scope": {{"observe": ["voter.verdict", "seed_action.x"]}},
            }}
            names = ["seed_action"] + {variants!r}
            i, c = infer_dependencies(config, names, "probe", validate=False)
            print(json.dumps({{"inputs": i, "context": c}}))
        """)
        result = _run_probe(probe, "0")

        assert result["context"] == variants, (
            "variants must come out in numeric order, which only holds if the sort runs "
            "on the base name before expansion"
        )
