"""A first-stage guard can read the staging row it is judging.

`get_existing_content` synthesizes a `source` namespace from a first-stage row, and its
docstring calls itself "the SINGLE function for content extraction -- batch and online paths
both use this". The online prefilter called it without `is_first_stage`, so it got `{}`: every
clause failed as a missing field with "Available top-level fields:" empty, and the guard
discarded every record whatever its value.
"""

from __future__ import annotations

from agent_actions.workflow.pipeline_file_mode import prefilter_by_guard

_OBSERVE = {"observe": ["source.text"]}


def _online(clause: str, priority: str) -> tuple[int, int]:
    config = {
        "name": "triage",
        "prompt": "p",
        "context_scope": _OBSERVE,
        "guard": {"clause": clause, "behavior": "filter"},
    }
    row = {"priority": priority, "text": "t"}
    passing, _skipped, _originals, filtered = prefilter_by_guard(
        [dict(row)], config, "triage", is_first_stage=True
    )
    return len(passing), len(filtered)


class TestTheRowIsReadableAsSource:
    """`source.field` is the spelling, and it must answer both ways round."""

    def test_a_matching_row_passes(self):
        assert _online("source.priority == 'high'", "high") == (1, 0)

    def test_a_non_matching_row_is_filtered(self):
        """Value-sensitive, so the clause resolved rather than erroring alike."""
        assert _online("source.priority == 'high'", "low") == (0, 1)


class TestABareNameIsStillRefused:
    """The row is a namespace, not a set of top-level keys.

    Kept deliberately: `get_existing_content` nests the row under `source` rather than
    flattening it, which is the framework's namespaced direction, and the evaluator suggests
    the dotted spelling. The batch preparer does flatten, so a bare name resolves there --
    a divergence this change does not close, recorded in #1164.
    """

    def test_a_bare_name_does_not_resolve(self):
        assert _online("priority == 'high'", "high") == (0, 1)
