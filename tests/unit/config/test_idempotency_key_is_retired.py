"""`idempotency_key` validated, was echoed by the docs tooling, and did nothing.

It was declared on `ActionConfig` and documented as a real key, so a project writing it
loaded clean and saw it in the generated docs — while no runtime consumer existed
anywhere. Unlike the keys #1066 retired, nothing had been removed: it never worked.

The four-surface refusal comes free from `_RETIRED_CONFIG_KEYS`, which
`TestTheSharedTableCoversEverySurface` is parametrised over. What that cannot see is the
declaration and the docs echo, which are what made it look real.
"""

from agent_actions.config.schema import _RETIRED_CONFIG_KEYS, ActionConfig


class TestTheKeyIsRetiredRatherThanDeclared:
    def test_it_is_in_the_retired_table(self):
        """So the shared four-surface test refuses it without new test code."""
        assert "idempotency_key" in _RETIRED_CONFIG_KEYS

    def test_it_carries_no_replacement_hint(self):
        """Nothing replaced it — there is no behaviour to redirect the reader to."""
        assert _RETIRED_CONFIG_KEYS["idempotency_key"] == ""

    def test_it_is_no_longer_a_declared_field(self):
        """Declared, it validated and read as supported."""
        assert "idempotency_key" not in ActionConfig.model_fields


class TestNothingStillAdvertisesIt:
    def test_the_docs_parser_no_longer_echoes_it(self):
        """The echo put it in generated docs, which is how a project learned to write it."""
        from pathlib import Path

        parser = Path(__file__).resolve().parents[3] / "agent_actions/tooling/docs/parser.py"

        assert "idempotency_key" not in parser.read_text()

    def test_the_configuration_reference_no_longer_lists_it(self):
        from pathlib import Path

        reference = (
            Path(__file__).resolve().parents[3]
            / "docs.agent-actions/docs/reference/configuration/index.md"
        )
        if not reference.exists():
            import pytest

            pytest.skip("docs not present")

        assert "idempotency_key" not in reference.read_text()
