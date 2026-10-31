"""Tests for LSP action hover card rendering."""

import ast
from pathlib import Path

import agent_actions.tooling.lsp
from agent_actions.config.schema import VersionConfig
from agent_actions.tooling.lsp.completions import build_versions_completions
from agent_actions.tooling.lsp.handlers import _build_action_hover
from agent_actions.tooling.lsp.indexer import _populate_versions_summary
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


class TestTheVersionsSummaryTheIndexerBuilds:
    """Hover and code lens read this string, so a retired key shown here is advice."""

    def _summary(self, versions):
        meta = ActionMetadata(name="a1", location=Location(file_path="workflow.yml", line=1))
        _populate_versions_summary(meta, {"versions": versions})
        return meta.versions_summary

    def test_it_describes_the_param_and_range(self):
        assert self._summary({"param": "round", "range": [1, 3]}) == "param `round`, range `[1, 3]`"

    def test_it_does_not_describe_a_retired_key(self):
        summary = self._summary({"param": "round", "range": [1, 3], "mode": "sequential"})

        assert "mode" not in summary
        assert "sequential" not in summary


class TestNoHandWrittenVersionsKeyList:
    """The keys offered for a `versions:` block come from the model, not a literal.

    Scanned rather than driven: the completion handler needs an initialised language
    server, and the list it replaced had outlived three keys — one of which now
    aborts a config load, so an editor still offering it is worse than no suggestion.
    """

    def test_no_lsp_module_spells_the_versions_keys_out(self):
        lsp_dir = Path(agent_actions.tooling.lsp.__file__).parent
        offenders = []
        for path in sorted(lsp_dir.glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Tuple | ast.List):
                    continue
                literals = {
                    e.value
                    for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }
                if {"param", "range"} <= literals:
                    offenders.append(f"{path.name}:{node.lineno} {sorted(literals)}")

        assert not offenders, (
            "a versions-key list is written out by hand, so it can drift from what the "
            f"loader accepts: {offenders}"
        )
