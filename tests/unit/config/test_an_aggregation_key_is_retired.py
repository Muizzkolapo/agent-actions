"""`reduce_key` validated, was echoed by the docs tooling, and never grouped anything.

It was declared on `ActionConfig` and documented as the aggregation pattern, so a project
writing it loaded clean. Two layers stopped it working. The expander copies only the
fields it knows, and this was not one, so the key never reached the runtime config at
all — a run behaved exactly as if it were absent. Delivered the one way that does reach
the merge, under `default_agent_config:`, the lookup then searched the record top level
and the top of `content`, where no stored record keeps a user field: every field sits a
level lower, under `content["<action>"]`. Every record fell back to its own identity, so
the action still ran once per record. Had a record been keyed, the group merge kept one
member's value per namespace and dropped the rest.

The four-surface refusal comes free from `_RETIRED_CONFIG_KEYS`, which
`TestTheSharedTableCoversEverySurface` is parametrised over. What that cannot see is the
declaration and the docs echo, which are what made the key look real.
"""

from pathlib import Path

from agent_actions.config.schema import _RETIRED_CONFIG_KEYS, ActionConfig

REPO = Path(__file__).resolve().parents[3]

# What a reader who wrote the key was actually asking for, and where it still lives.
REPLACEMENT = "granularity: File"


class TestTheKeyIsRetiredRatherThanDeclared:
    def test_it_is_in_the_retired_table(self):
        """So the shared four-surface test refuses it without new test code."""
        assert "reduce_key" in _RETIRED_CONFIG_KEYS

    def test_it_names_file_granularity_as_the_replacement(self):
        """Grouping is still reachable, so "remove it" alone costs the reader the
        behaviour they asked for."""
        assert REPLACEMENT in _RETIRED_CONFIG_KEYS["reduce_key"]

    def test_it_is_no_longer_a_declared_field(self):
        """Declared, it validated and read as supported."""
        assert "reduce_key" not in ActionConfig.model_fields


class TestNothingStillAdvertisesIt:
    def test_the_docs_parser_no_longer_echoes_it(self):
        """The echo put it in generated docs, which is how a project learned to write it."""
        parser = REPO / "agent_actions/tooling/docs/parser.py"

        assert "reduce_key" not in parser.read_text()

    def test_the_troubleshooting_guide_no_longer_teaches_it(self):
        """It was the only page that documented the key, as a dependency pattern and
        again as what determines an action's execution count."""
        guide = REPO / "docs.agent-actions/docs/guides/troubleshooting.md"
        if not guide.exists():
            import pytest

            pytest.skip("docs not present")

        assert "reduce_key" not in guide.read_text()

    def test_no_runtime_module_still_reads_it(self):
        """The merge and the two fan-in readers took it from the action config, and the
        scope inference branched on it — all of them for a key nothing could deliver."""
        offenders = sorted(
            str(path.relative_to(REPO))
            for path in (REPO / "agent_actions").rglob("*.py")
            if "reduce_key" in path.read_text()
        )

        assert offenders == [], offenders


class TestNoProjectInThisRepoStillWritesIt:
    """Retiring it breaks any config that writes it, so none may be left behind."""

    def test_no_shipped_project_fixture_or_example_declares_it(self):
        files = sorted((REPO / "examples").rglob("*.yml"))
        files += sorted((REPO / "tests/integration/fixtures").rglob("*.yml"))
        assert files, "no project files found"

        offenders = [
            str(path.relative_to(REPO)) for path in files if "reduce_key" in path.read_text()
        ]

        assert offenders == [], offenders
