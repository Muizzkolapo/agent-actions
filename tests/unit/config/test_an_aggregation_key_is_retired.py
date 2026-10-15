"""`reduce_key` validated, was echoed by the docs tooling, and never grouped anything.

The four-surface refusal comes free from `_RETIRED_CONFIG_KEYS`, which
`TestTheSharedTableCoversEverySurface` is parametrised over. What that cannot see is the
declaration and the docs echo, which are what made the key look real.
"""

import subprocess
from pathlib import Path

from agent_actions.config.schema import _RETIRED_CONFIG_KEYS, ActionConfig

REPO = Path(__file__).resolve().parents[3]

# What a reader who wrote the key was actually asking for, and where it still lives.
REPLACEMENT = "granularity: File"


def _tracked_configs() -> list[str]:
    """Every tracked YAML path, from git rather than a glob.

    A glob has to name each directory and suffix, and missed `.yaml` and
    `tests/fixtures/workflows/` — both of which hold loadable workflow configs.
    """
    out = subprocess.run(
        ["git", "ls-files", "*.yml", "*.yaml"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


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
        scope inference branched on it — all of them for a key nothing could deliver.

        `config/schema.py` is where it is refused, so that one names it on purpose.
        """
        refuses_it = REPO / "agent_actions/config/schema.py"
        offenders = sorted(
            str(path.relative_to(REPO))
            for path in (REPO / "agent_actions").rglob("*.py")
            if path != refuses_it and "reduce_key" in path.read_text()
        )

        assert offenders == [], offenders


class TestNoProjectInThisRepoStillWritesIt:
    """Retiring it breaks any config that writes it, so none may be left behind."""

    def test_no_shipped_project_fixture_or_example_declares_it(self):
        """Every tracked config, both suffixes: a workflow fixture writing a refused key
        fails at load, and `.yaml` and `tests/fixtures/` both hold such configs."""
        files = [
            REPO / path for path in _tracked_configs() if path.startswith(("examples/", "tests/"))
        ]
        assert files, "no project files found"

        offenders = [
            str(path.relative_to(REPO))
            for path in files
            if path.exists() and "reduce_key" in path.read_text()
        ]

        assert offenders == [], offenders
