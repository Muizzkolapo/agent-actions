"""Tests for LSP action hover card rendering."""

from agent_actions.config.schema import VersionConfig
from agent_actions.tooling.lsp.completions import build_versions_completions
from agent_actions.tooling.lsp.handlers import _build_action_hover
from agent_actions.tooling.lsp.models import ActionMetadata, Location


def _make_meta(**overrides):
    defaults = {
        "name": "classify_severity",
        "location": Location(file_path="workflow.yml", line=10),
    }
    defaults.update(overrides)
    return ActionMetadata(**defaults)


class TestBuildActionHover:
    def test_minimal_action(self):
        """Action with only name and location shows both."""
        result = _build_action_hover(_make_meta())
        assert "**Action**: `classify_severity`" in result
        assert "line 11" in result

    def test_shows_dependencies(self):
        result = _build_action_hover(_make_meta(dependencies=["extract", "transform"]))
        assert "`extract`" in result
        assert "`transform`" in result
        assert "**Dependencies**" in result

    def test_shows_versions_summary(self):
        result = _build_action_hover(_make_meta(versions_summary="param `round`, range `[1, 3]`"))
        assert "**Versions**" in result
        assert "param `round`, range `[1, 3]`" in result

    def test_shows_prompt_ref(self):
        result = _build_action_hover(_make_meta(prompt_ref="$incident_triage.Classify"))
        assert "**Prompt**: `$incident_triage.Classify`" in result

    def test_shows_impl_ref(self):
        result = _build_action_hover(_make_meta(impl_ref="aggregate_votes"))
        assert "**Tool**: `aggregate_votes`" in result

    def test_shows_schema_ref(self):
        result = _build_action_hover(_make_meta(schema_ref="severity_output"))
        assert "**Schema**: `severity_output`" in result

    def test_shows_guard_condition(self):
        result = _build_action_hover(_make_meta(guard_condition='status == "PASS"'))
        assert '**Guard**: `status == "PASS"`' in result

    def test_shows_observe(self):
        result = _build_action_hover(_make_meta(context_observe=["extract.*", "source.report"]))
        assert "**Observe**" in result
        assert "`extract.*`" in result
        assert "`source.report`" in result

    def test_shows_passthrough(self):
        result = _build_action_hover(_make_meta(context_passthrough=["upstream.*"]))
        assert "**Passthrough**" in result
        assert "`upstream.*`" in result

    def test_omits_empty_fields(self):
        """Fields that are None/empty are not shown."""
        result = _build_action_hover(_make_meta())
        assert "**Dependencies**" not in result
        assert "**Versions**" not in result
        assert "**Prompt**" not in result
        assert "**Guard**" not in result
        assert "**Reprompt**" not in result
        assert "**Observe**" not in result
        assert "**Passthrough**" not in result


class TestTheVersionsBlockCompletions:
    """The editor must not offer a key the loader refuses."""

    def test_it_offers_exactly_the_keys_the_block_declares(self):
        offered = [item.label for item in build_versions_completions()]

        assert offered == list(VersionConfig.model_fields)

    def test_every_key_it_offers_is_accepted_by_the_loader(self):
        """The suggestions used to include three keys, and `mode` now aborts a load."""
        defaults = VersionConfig().model_dump()

        for key in (item.label for item in build_versions_completions()):
            VersionConfig.model_validate({key: defaults[key]})
