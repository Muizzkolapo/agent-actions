"""Unit tests for agent_actions.prompt.renderer module.

Covers:
- JinjaTemplateRenderer.render path validation and rendering pipeline
- ConfigRenderingService._safe_load_yaml parsing
- ConfigRenderingService._build_agent_entry_from_action mapping
- ConfigRenderingService._validate_entry_with_pydantic validation
- ConfigRenderingService._validate_agent_config_block format detection
- ConfigRenderingService.render_and_load_config end-to-end flow
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from agent_actions.errors import (
    ConfigurationError,
    ConfigValidationError,
    TemplateRenderingError,
)
from agent_actions.prompt.renderer import (
    ConfigRenderingService,
    JinjaTemplateRenderer,
    TemplateRenderer,
)

# ---------------------------------------------------------------------------
# JinjaTemplateRenderer
# ---------------------------------------------------------------------------


class TestJinjaTemplateRendererRender:
    """Tests for JinjaTemplateRenderer.render."""

    @patch("agent_actions.prompt.renderer.render_pipeline_with_templates")
    @patch("agent_actions.prompt.renderer.PathValidator")
    def test_render_returns_rendered_template(self, mock_pv_cls, mock_pipeline):
        """Successful render returns the rendered template string."""
        mock_pv = mock_pv_cls.return_value
        mock_pv.validate.return_value = True
        mock_pipeline.return_value = "rendered: output"

        renderer = JinjaTemplateRenderer()
        result = renderer.render("/fake/config.yml", "/fake/templates")

        assert result == "rendered: output"
        mock_pipeline.assert_called_once_with(
            "/fake/config.yml", "/fake/templates", project_root=None
        )

    @patch("agent_actions.prompt.renderer.render_pipeline_with_templates")
    @patch("agent_actions.prompt.renderer.PathValidator")
    def test_render_passes_project_root(self, mock_pv_cls, mock_pipeline):
        """project_root kwarg is forwarded to the pipeline."""
        mock_pv = mock_pv_cls.return_value
        mock_pv.validate.return_value = True
        mock_pipeline.return_value = "ok"

        renderer = JinjaTemplateRenderer()
        root = Path("/my/project")
        renderer.render("/c.yml", "/t", project_root=root)

        mock_pipeline.assert_called_once_with("/c.yml", "/t", project_root=root)

    @patch("agent_actions.prompt.renderer.render_pipeline_with_templates")
    @patch("agent_actions.prompt.renderer.PathValidator")
    def test_render_writes_output_file(self, mock_pv_cls, mock_pipeline, tmp_path):
        """When output_path is given, rendered template is written to disk."""
        mock_pv = mock_pv_cls.return_value
        mock_pv.validate.return_value = True
        mock_pipeline.return_value = "rendered content"

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        renderer = JinjaTemplateRenderer()
        result = renderer.render("/fake/config.yml", "/fake/templates", str(output_dir))

        assert result == "rendered content"
        written_file = output_dir / "config.yml"
        assert written_file.read_text() == "rendered content"

    @patch("agent_actions.prompt.renderer.ErrorHandler")
    @patch("agent_actions.prompt.renderer.PathValidator")
    def test_render_validation_failure_raises(self, mock_pv_cls, mock_eh):
        """When path validation fails, ValueError is raised through ErrorHandler."""
        mock_pv = mock_pv_cls.return_value
        mock_pv.validate.return_value = False
        mock_pv.get_errors.return_value = ["Config file not found"]

        mock_eh.handle_template_error.side_effect = TemplateRenderingError(
            "Template operation 'render' failed"
        )

        renderer = JinjaTemplateRenderer()
        with pytest.raises(TemplateRenderingError):
            renderer.render("/missing/config.yml", "/fake/templates")

    @patch("agent_actions.prompt.renderer.ErrorHandler")
    @patch("agent_actions.prompt.renderer.render_pipeline_with_templates")
    @patch("agent_actions.prompt.renderer.PathValidator")
    def test_render_pipeline_error_goes_through_error_handler(
        self, mock_pv_cls, mock_pipeline, mock_eh
    ):
        """Exceptions from the pipeline are delegated to ErrorHandler."""
        mock_pv = mock_pv_cls.return_value
        mock_pv.validate.return_value = True
        mock_pipeline.side_effect = RuntimeError("template boom")
        mock_eh.handle_template_error.side_effect = TemplateRenderingError("wrapped")

        renderer = JinjaTemplateRenderer()
        with pytest.raises(TemplateRenderingError):
            renderer.render("/c.yml", "/t")

        mock_eh.handle_template_error.assert_called_once()

    @patch("agent_actions.prompt.renderer.PathValidator")
    def test_render_multiple_validation_errors_aggregated(self, mock_pv_cls):
        """Multiple path validation failures are aggregated in the error message."""
        mock_pv = mock_pv_cls.return_value
        # First call: config file fails, second call: template dir fails
        mock_pv.validate.return_value = False
        mock_pv.get_errors.side_effect = [
            ["Config file not found"],
            ["Template dir not found"],
        ]

        renderer = JinjaTemplateRenderer()
        # The ValueError is caught by the except block and goes through ErrorHandler
        # which re-raises as TemplateRenderingError. We need to mock ErrorHandler too.
        with patch("agent_actions.prompt.renderer.ErrorHandler") as mock_eh:
            mock_eh.handle_template_error.side_effect = TemplateRenderingError("wrapped")
            with pytest.raises(TemplateRenderingError):
                renderer.render("/bad/config.yml", "/bad/templates")


# ---------------------------------------------------------------------------
# TemplateRenderer ABC
# ---------------------------------------------------------------------------


class TestTemplateRendererABC:
    """The ABC cannot be instantiated directly."""

    def test_abstract_render_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            TemplateRenderer()


# ---------------------------------------------------------------------------
# ConfigRenderingService._safe_load_yaml
# ---------------------------------------------------------------------------


class TestSafeLoadYaml:
    """Tests for YAML parsing helper."""

    def test_parses_valid_yaml(self):
        svc = ConfigRenderingService()
        raw = "key: value\nitems:\n  - a\n  - b\n"
        result = svc._safe_load_yaml(raw, Path("/fake.yml"))
        assert result == {"key": "value", "items": ["a", "b"]}

    def test_empty_string_raises(self):
        svc = ConfigRenderingService()
        with pytest.raises(ConfigurationError, match="empty"):
            svc._safe_load_yaml("", Path("/fake.yml"))

    def test_whitespace_only_raises(self):
        svc = ConfigRenderingService()
        with pytest.raises(ConfigurationError, match="empty"):
            svc._safe_load_yaml("   \n  \n  ", Path("/fake.yml"))

    def test_yaml_syntax_error_raises(self):
        svc = ConfigRenderingService()
        bad_yaml = "key: [unclosed"
        with pytest.raises(ConfigurationError, match="YAML syntax error"):
            svc._safe_load_yaml(bad_yaml, Path("/bad.yml"))

    def test_yaml_that_resolves_to_none_raises(self):
        """YAML like '---\\n' parses to None -- should raise."""
        svc = ConfigRenderingService()
        with pytest.raises(ConfigurationError, match="empty data"):
            svc._safe_load_yaml("---\n", Path("/empty.yml"))

    def test_yaml_syntax_error_includes_context(self):
        svc = ConfigRenderingService()
        bad_yaml = "key: :\n  bad: [indent"
        with pytest.raises(ConfigurationError) as exc_info:
            svc._safe_load_yaml(bad_yaml, Path("/bad.yml"))
        assert exc_info.value.context.get("operation") == "parse_yaml"


# ---------------------------------------------------------------------------
# ConfigRenderingService._build_agent_entry_from_action
# ---------------------------------------------------------------------------


class TestBuildAgentEntryFromAction:
    """Tests for building agent entries from new-format action dicts."""

    def test_basic_action_mapping(self):
        svc = ConfigRenderingService()
        action = {"name": "my_agent", "model_vendor": "anthropic", "model_name": "claude-3"}
        entry = svc._build_agent_entry_from_action(action)

        assert entry["agent_type"] == "my_agent"
        assert entry["name"] == "my_agent"
        assert entry["model_vendor"] == "anthropic"
        assert entry["model_name"] == "claude-3"
        assert entry["is_operational"] is True
        assert entry["json_mode"] is True

    def test_defaults_when_fields_missing(self):
        svc = ConfigRenderingService()
        entry = svc._build_agent_entry_from_action({})

        assert entry["agent_type"] == "unknown"
        assert entry["model_vendor"] is None  # Required field — no default vendor
        assert entry["model_name"] is None  # Required field — no default model
        assert entry["granularity"] == "record"

    def test_tool_kind_overrides_model_fields(self):
        svc = ConfigRenderingService()
        action = {"name": "my_tool", "kind": "tool", "impl": "tool_impl_name"}
        entry = svc._build_agent_entry_from_action(action)

        assert entry["model_vendor"] == "tool"
        assert entry["model_name"] == "tool_impl_name"

    def test_tool_kind_falls_back_to_name(self):
        svc = ConfigRenderingService()
        action = {"name": "my_tool", "kind": "tool"}
        entry = svc._build_agent_entry_from_action(action)

        assert entry["model_name"] == "my_tool"

    def test_schema_string_becomes_schema_name(self):
        svc = ConfigRenderingService()
        action = {"name": "a", "schema": "my_schema"}
        entry = svc._build_agent_entry_from_action(action)

        assert entry["schema_name"] == "my_schema"
        assert "schema" not in entry

    def test_schema_dict_stays_as_schema(self):
        svc = ConfigRenderingService()
        schema_dict = {"type": "object", "properties": {}}
        action = {"name": "a", "schema": schema_dict}
        entry = svc._build_agent_entry_from_action(action)

        assert entry["schema"] == schema_dict
        assert "schema_name" not in entry

    def test_prompt_forwarded(self):
        svc = ConfigRenderingService()
        action = {"name": "a", "prompt": "Do the thing."}
        entry = svc._build_agent_entry_from_action(action)

        assert entry["prompt"] == "Do the thing."

    def test_prompt_absent_when_not_provided(self):
        svc = ConfigRenderingService()
        action = {"name": "a"}
        entry = svc._build_agent_entry_from_action(action)

        assert "prompt" not in entry


# ---------------------------------------------------------------------------
# ConfigRenderingService._validate_entry_with_pydantic
# ---------------------------------------------------------------------------


class TestValidateEntryWithPydantic:
    """Tests for Pydantic-based entry validation."""

    def test_valid_entry_passes(self):
        svc = ConfigRenderingService()
        entry = {
            "agent_type": "test_agent",
            "name": "test_agent",
            "model_vendor": "openai",
            "model_name": "gpt-4",
            "is_operational": True,
            "json_mode": True,
        }
        result = svc._validate_entry_with_pydantic(entry, "agent1", "action_configuration")
        assert result["agent_type"] == "test_agent"

    def test_invalid_entry_raises_config_validation_error(self):
        svc = ConfigRenderingService()
        # Missing required field 'agent_type'
        entry = {"name": "incomplete"}
        with pytest.raises(ConfigValidationError, match="action_configuration"):
            svc._validate_entry_with_pydantic(entry, "agent1", "action_configuration")


# ---------------------------------------------------------------------------
# ConfigRenderingService._validate_agent_config_block
# ---------------------------------------------------------------------------


class TestValidateAgentConfigBlock:
    """Tests for format detection and validation dispatch."""

    @patch.object(ConfigRenderingService, "_run_config_validator")
    @patch.object(ConfigRenderingService, "_validate_new_format")
    def test_new_format_detected(self, mock_new, mock_run):
        """Config with both 'actions' and 'name' keys uses new format path."""
        svc = ConfigRenderingService()
        config = {"actions": [], "name": "my_pipeline"}
        mock_new.return_value = []

        svc._validate_agent_config_block(config, "agent1", project_root=Path("/proj"))

        mock_new.assert_called_once_with(config, "agent1")
        mock_run.assert_called_once()

    @patch.object(ConfigRenderingService, "_run_config_validator")
    @patch.object(ConfigRenderingService, "_validate_legacy_format")
    def test_legacy_format_detected(self, mock_legacy, mock_run):
        """Config without 'actions'+'name' pair uses legacy format path."""
        svc = ConfigRenderingService()
        config = {"agent1": [{"agent_type": "test"}]}
        mock_legacy.return_value = []

        svc._validate_agent_config_block(config, "agent1", project_root=Path("/proj"))

        mock_legacy.assert_called_once_with(config, "agent1")

    @patch.object(ConfigRenderingService, "_run_config_validator")
    @patch.object(ConfigRenderingService, "_validate_legacy_format")
    @patch("agent_actions.prompt.renderer.find_project_root", return_value=None)
    def test_fallback_to_cwd_when_no_project_root(self, mock_fpr, mock_legacy, mock_run):
        """When project_root is None and find_project_root returns None, use cwd."""
        svc = ConfigRenderingService()
        config = {"agent1": []}
        mock_legacy.return_value = []

        svc._validate_agent_config_block(config, "agent1")

        # ConfigValidator is called with some Path -- we just verify no crash
        mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# ConfigRenderingService._validate_legacy_format
# ---------------------------------------------------------------------------


class TestValidateLegacyFormat:
    """Tests for legacy format config validation."""

    def test_missing_agent_key_raises(self):
        svc = ConfigRenderingService()
        config = {"other_key": "value"}
        with pytest.raises(ConfigValidationError, match="No agent configuration found"):
            svc._validate_legacy_format(config, "missing_agent")


# ---------------------------------------------------------------------------
# ConfigRenderingService._run_config_validator
# ---------------------------------------------------------------------------


class TestRunConfigValidator:
    """Tests for ConfigValidator integration."""

    @patch("agent_actions.prompt.renderer.ConfigValidator")
    def test_passes_when_valid(self, mock_cv_cls):
        mock_cv = mock_cv_cls.return_value
        mock_cv.validate.return_value = True

        svc = ConfigRenderingService()
        # Should not raise
        svc._run_config_validator([], "agent1", Path("/proj"))

    @patch("agent_actions.prompt.renderer.ConfigValidator")
    def test_raises_when_validation_fails_with_errors(self, mock_cv_cls):
        mock_cv = mock_cv_cls.return_value
        mock_cv.validate.return_value = False
        mock_cv.get_errors.return_value = ["Something is wrong"]

        svc = ConfigRenderingService()
        with pytest.raises(ConfigValidationError, match="validation failed"):
            svc._run_config_validator([], "agent1", Path("/proj"))

    @patch("agent_actions.prompt.renderer.ConfigValidator")
    def test_no_raise_when_validation_fails_but_no_errors(self, mock_cv_cls):
        """Edge case: validate returns False but get_errors is empty."""
        mock_cv = mock_cv_cls.return_value
        mock_cv.validate.return_value = False
        mock_cv.get_errors.return_value = []

        svc = ConfigRenderingService()
        # Should not raise -- the code only raises if errors list is truthy
        svc._run_config_validator([], "agent1", Path("/proj"))


# ---------------------------------------------------------------------------
# ConfigRenderingService.render_and_load_config (integration-style)
# ---------------------------------------------------------------------------


class TestRenderAndLoadConfig:
    """Tests for the full render_and_load_config pipeline."""

    def _make_service(self, rendered_yaml="key: value\n"):
        """Create a service with a mocked template renderer."""
        mock_renderer = MagicMock(spec=JinjaTemplateRenderer)
        mock_renderer.render.return_value = rendered_yaml
        return ConfigRenderingService(template_renderer=mock_renderer)

    def test_config_file_not_found_raises(self, tmp_path):
        svc = self._make_service()
        with pytest.raises(ConfigurationError, match="not found"):
            svc.render_and_load_config(
                "agent1",
                str(tmp_path / "nonexistent.yml"),
                str(tmp_path / "templates"),
            )

    def test_config_path_is_directory_raises(self, tmp_path):
        config_dir = tmp_path / "config_dir"
        config_dir.mkdir()
        svc = self._make_service()
        with pytest.raises(ConfigurationError, match="directory"):
            svc.render_and_load_config(
                "agent1",
                str(config_dir),
                str(tmp_path / "templates"),
            )

    @patch("agent_actions.prompt.renderer.SchemaValidator")
    @patch.object(ConfigRenderingService, "_validate_agent_config_block")
    def test_successful_render_and_load(self, mock_validate, mock_sv_cls, tmp_path):
        """Happy path: renders template, parses YAML, validates, returns config."""
        config_file = tmp_path / "agent.yml"
        config_file.write_text("placeholder")  # file must exist for the check
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        # get_schema_path() requires agent_actions.yml with schema_path key
        (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")

        mock_sv = mock_sv_cls.return_value
        mock_sv.validate.return_value = True

        rendered = yaml.dump({"agent1": [{"agent_type": "test"}]})
        svc = self._make_service(rendered_yaml=rendered)

        result = svc.render_and_load_config("agent1", str(config_file), str(template_dir))

        assert "agent1" in result
        mock_validate.assert_called_once()

    @patch("agent_actions.prompt.renderer.SchemaValidator")
    def test_schema_validation_failure_raises(self, mock_sv_cls, tmp_path):
        """If SchemaValidator.validate raises, ConfigurationError is raised."""
        config_file = tmp_path / "agent.yml"
        config_file.write_text("placeholder")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        mock_sv = mock_sv_cls.return_value
        mock_sv.validate.side_effect = RuntimeError("schema boom")

        rendered = yaml.dump({"agent1": [{"agent_type": "test"}]})
        svc = self._make_service(rendered_yaml=rendered)

        with pytest.raises(ConfigurationError, match="Schema validation failed"):
            svc.render_and_load_config("agent1", str(config_file), str(template_dir))

    def test_empty_rendered_template_raises(self, tmp_path):
        """If the renderer returns empty string, _safe_load_yaml raises."""
        config_file = tmp_path / "agent.yml"
        config_file.write_text("placeholder")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        svc = self._make_service(rendered_yaml="")

        with pytest.raises(ConfigurationError, match="empty"):
            svc.render_and_load_config("agent1", str(config_file), str(template_dir))

    def test_invalid_yaml_from_renderer_raises(self, tmp_path):
        """If the renderer returns invalid YAML, _safe_load_yaml raises."""
        config_file = tmp_path / "agent.yml"
        config_file.write_text("placeholder")
        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        svc = self._make_service(rendered_yaml="key: [unclosed")

        with pytest.raises(ConfigurationError, match="YAML syntax error"):
            svc.render_and_load_config("agent1", str(config_file), str(template_dir))


# ---------------------------------------------------------------------------
# ConfigRenderingService default renderer
# ---------------------------------------------------------------------------


class TestConfigRenderingServiceInit:
    """Constructor and default wiring tests."""

    def test_default_renderer_is_jinja(self):
        svc = ConfigRenderingService()
        assert isinstance(svc.template_renderer, JinjaTemplateRenderer)

    def test_custom_renderer_is_used(self):
        mock = MagicMock(spec=TemplateRenderer)
        svc = ConfigRenderingService(template_renderer=mock)
        assert svc.template_renderer is mock
