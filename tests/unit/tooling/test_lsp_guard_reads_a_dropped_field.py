"""The editor must not warn about a guard clause the runtime answers.

A guard runs before the action, which is why it reads the record as stored rather than the
view ``context_scope`` shaped for the prompt. A field the action ``drop``s therefore still
answers a clause, so flagging it as unavailable is a false positive.

The bare-name case is the opposite and stays: the observe pass used to flatten an observed
field to a top-level key at FILE granularity, and nothing resolves that spelling now, so
the warning and its dotted-form suggestion are the useful half.
"""

from pathlib import Path

from agent_actions.tooling.lsp.diagnostics import (
    collect_available_guard_variables,
    collect_diagnostics,
)
from agent_actions.tooling.lsp.models import ActionMetadata, Location, ProjectIndex

WORKFLOW = Path("/proj/agent_config/w.yml")


def _index(*, guard, variables, observe=(), drop=(), passthrough=()):
    index = ProjectIndex(root=Path("/proj"))
    index.file_actions[WORKFLOW] = {
        "a2": ActionMetadata(
            name="a2",
            location=Location(file_path=WORKFLOW, line=1, column=0),
            dependencies=["a1"],
            context_observe=list(observe),
            context_drop=list(drop),
            context_passthrough=list(passthrough),
            guard_condition=guard,
            guard_line=7,
            guard_variables=list(variables),
        )
    }
    return index


def _guard_messages(index):
    return [
        d.message for d in collect_diagnostics(WORKFLOW, index) if "Guard condition" in d.message
    ]


class TestADroppedFieldIsNotFlagged:
    def test_a_clause_on_a_dropped_field_produces_no_warning(self):
        index = _index(
            guard='a1.tier == "secret"',
            variables=["a1.tier"],
            observe=["a1.n"],
            drop=["a1.tier"],
        )

        assert _guard_messages(index) == []

    def test_a_field_neither_observed_nor_dropped_is_still_flagged(self):
        """The other half: the check still does something, so the row above is not passing
        because guard diagnostics stopped being emitted."""
        index = _index(
            guard='a1.absent == "secret"',
            variables=["a1.absent"],
            observe=["a1.n"],
            drop=["a1.tier"],
        )

        messages = _guard_messages(index)

        assert len(messages) == 1
        assert "a1.absent" in messages[0]


class TestABareNameIsStillFlagged:
    """The spelling that stopped resolving anywhere. Worth keeping loud."""

    def test_a_bare_name_warns_and_suggests_the_dotted_form(self):
        index = _index(guard="n == 1", variables=["n"], observe=["a1.n"])

        messages = _guard_messages(index)

        assert len(messages) == 1
        assert "`a1.n`" in messages[0]

    def test_a_bare_name_of_a_dropped_field_is_suggested_too(self):
        """Dropped fields are readable, so the suggestion should reach them: the runtime
        answers ``a1.tier`` and the bare ``tier`` resolves nowhere."""
        index = _index(guard='tier == "secret"', variables=["tier"], drop=["a1.tier"])

        messages = _guard_messages(index)

        assert len(messages) == 1
        assert "`a1.tier`" in messages[0]


class TestTheDiscoveryListOffersItToo:
    """Completions and signature help read ``collect_available_guard_variables``. A field a
    guard can read belongs in the list it is offered from, or the editor suggests a narrower
    set than the runtime accepts."""

    def test_a_dropped_field_is_offered_as_a_guard_variable(self):
        index = _index(
            guard='a1.tier == "secret"',
            variables=["a1.tier"],
            observe=["a1.n"],
            drop=["a1.tier"],
        )

        offered = collect_available_guard_variables(WORKFLOW, index)

        assert "a1.tier" in offered
        assert "a1.n" in offered
