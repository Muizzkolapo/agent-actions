"""The seed directive: declared under context_scope.seed, loaded under the seed namespace.

The old directive keys (seed_path, static_data) are removed and must fail loud.
"""

import json

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.input.context.normalizer import normalize_context_scope
from agent_actions.prompt.service import PromptPreparationService


def _workflow_with_seed_file(tmp_path, filename="refs.json", content=None):
    """Build a workflow tree with a seed_data/ folder holding one file; return the config path."""
    workflow = tmp_path / "workflow"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "seed_data").mkdir()
    (workflow / "seed_data" / filename).write_text(
        json.dumps(content if content is not None else {"a": 1})
    )
    return str(workflow / "agent_config" / "wf.yml")


class TestSeedDirectiveLoads:
    def test_seed_directive_loads_under_seed_namespace(self, tmp_path):
        """context_scope.seed maps alias -> file; the file loads under that alias."""
        config_path = _workflow_with_seed_file(tmp_path, content={"exam_name": "Q"})
        agent_config = {"workflow_config_path": config_path}
        context_scope = {"seed": {"exam_syllabus": "$file:refs.json"}}

        loaded = PromptPreparationService._load_seed_data(agent_config, context_scope, "act")

        assert loaded == {"exam_syllabus": {"exam_name": "Q"}}

    def test_no_seed_directive_loads_nothing(self, tmp_path):
        """No seed directive -> empty dict, no error."""
        config_path = _workflow_with_seed_file(tmp_path)
        agent_config = {"workflow_config_path": config_path}

        assert PromptPreparationService._load_seed_data(agent_config, {"observe": []}, "act") == {}


class TestRemovedDirectivesFailLoud:
    def test_seed_path_directive_is_rejected(self):
        """The renamed-away seed_path key must fail loud, not silently load nothing."""
        with pytest.raises(ConfigurationError) as excinfo:
            normalize_context_scope({"seed_path": {"exam_syllabus": "$file:refs.json"}}, {})
        assert "seed" in str(excinfo.value)

    def test_static_data_directive_is_rejected(self):
        """The retired static_data key must fail loud."""
        with pytest.raises(ConfigurationError) as excinfo:
            normalize_context_scope({"static_data": {"x": "$file:refs.json"}}, {})
        assert "seed" in str(excinfo.value)

    def test_seed_directive_is_accepted_and_preserved(self):
        """The new seed key normalizes without error and is preserved verbatim (dict directive)."""
        scope = {"seed": {"exam_syllabus": "$file:refs.json"}, "observe": ["source.x"]}

        normalized = normalize_context_scope(scope, {})

        assert normalized["seed"] == {"exam_syllabus": "$file:refs.json"}
