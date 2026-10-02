"""`ephemeral` validated on both allow-surfaces and rode onto every agent unread.

`8bf148d59` removed the declaration from `ActionConfig` and `AgentConfig` as "never acted
upon at runtime" — but both models that carry agent settings are `extra="allow"`, so
removing a declaration refuses nothing there. The key kept loading, kept reaching every
agent, and kept doing nothing.

The four-surface refusal comes free from `_RETIRED_CONFIG_KEYS`, which
`TestTheSharedTableCoversEverySurface` is parametrised over. What that cannot see is that
the two allow-surfaces accepted it while the strict ones only ever said "unknown field" —
which is why the key survived a removal commit that thought it had deleted it.
"""

from agent_actions.config.schema import _RETIRED_CONFIG_KEYS, refuse_retired_keys


class TestTheKeyIsRefusedWhereItUsedToRide:
    def test_it_is_in_the_retired_table(self):
        assert "ephemeral" in _RETIRED_CONFIG_KEYS

    def test_it_carries_no_replacement_hint(self):
        """Nothing replaced it — the removal commit said it was never acted upon."""
        assert _RETIRED_CONFIG_KEYS["ephemeral"] == ""

    def test_the_allow_surfaces_refuse_it_by_name(self):
        """A bare `extra="allow"` model would have taken it silently."""
        import pytest

        for surface in ("default_agent_config", "agents"):
            # ValueError, not ConfigurationError: the pydantic validator that calls this
            # wraps it, so raising anything else here would change how it surfaces.
            with pytest.raises(ValueError, match="ephemeral"):
                refuse_retired_keys({"ephemeral": False}, surface)


class TestNoProjectInThisRepoStillWritesIt:
    """Retiring it breaks any config that writes it, so none may be left behind."""

    def test_no_shipped_project_or_fixture_declares_it(self):
        from pathlib import Path

        import yaml

        root = Path(__file__).resolve().parents[3]
        files = sorted(root.glob("examples/*/agent_actions.yml"))
        files += sorted(root.glob("tests/integration/fixtures/*/agent_actions.yml"))
        assert files, "no project files found"

        offenders = []
        for path in files:
            data = yaml.safe_load(path.read_text()) or {}
            if "ephemeral" in (data.get("default_agent_config") or {}):
                offenders.append(str(path.relative_to(root)))

        assert offenders == [], offenders
