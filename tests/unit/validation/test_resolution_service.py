"""Tests for WorkflowResolutionService pre-flight checks."""

from agent_actions.validation.preflight.resolution_service import (
    WorkflowResolutionService,
)


class TestApiKeyChecks:
    """Tests for _check_api_keys() via resolve_all()."""

    def test_missing_api_key_env_var_detected(self, monkeypatch):
        """Missing API key env var produces an error with the correct message."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        svc = WorkflowResolutionService(
            action_configs={
                "summarizer": {"model_vendor": "openai"},
            },
        )
        result = svc.resolve_all()

        assert not result.is_valid
        assert len(result.errors) == 1
        err = result.errors[0]
        assert "OPENAI_API_KEY" in err.message
        assert "summarizer" in err.message

    def test_present_api_key_passes(self, monkeypatch):
        """When the API key env var is set, no error is produced."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        svc = WorkflowResolutionService(
            action_configs={
                "summarizer": {"model_vendor": "openai"},
            },
        )
        result = svc.resolve_all()

        api_key_errors = [
            e
            for e in result.errors
            if "api_key" in e.location.config_field.lower() or "API key" in e.message
        ]
        assert len(api_key_errors) == 0

    def test_tool_vendor_skipped(self, monkeypatch):
        """Tool vendor actions are skipped (NO_KEY_REQUIRED sentinel)."""
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        svc = WorkflowResolutionService(
            action_configs={
                "my_tool": {"model_vendor": "tool"},
            },
        )
        result = svc.resolve_all()

        api_key_errors = [e for e in result.errors if "API key" in e.message]
        assert len(api_key_errors) == 0

    def test_hitl_vendor_skipped(self, monkeypatch):
        """HITL vendor actions are skipped (NO_KEY_REQUIRED sentinel)."""
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        svc = WorkflowResolutionService(
            action_configs={
                "review": {"model_vendor": "hitl"},
            },
        )
        result = svc.resolve_all()

        api_key_errors = [e for e in result.errors if "API key" in e.message]
        assert len(api_key_errors) == 0

    def test_unknown_vendor_skipped(self, monkeypatch):
        """Unknown vendor produces no api-key error (no config to check against)."""
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        svc = WorkflowResolutionService(
            action_configs={
                "custom": {"model_vendor": "totally_unknown_vendor"},
            },
        )
        result = svc.resolve_all()

        api_key_errors = [e for e in result.errors if "API key" in e.message]
        assert len(api_key_errors) == 0

    def test_custom_api_key_dollar_resolved_as_env_var(self, monkeypatch):
        """Custom api_key starting with $ is resolved as an env var name."""
        monkeypatch.delenv("MY_CUSTOM_KEY", raising=False)
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        svc = WorkflowResolutionService(
            action_configs={
                "my_action": {"model_vendor": "openai", "api_key": "$MY_CUSTOM_KEY"},
            },
        )
        result = svc.resolve_all()

        api_key_errors = [e for e in result.errors if "API key" in e.message]
        assert len(api_key_errors) == 1
        assert "MY_CUSTOM_KEY" in api_key_errors[0].message

    def test_skip_env_validation_flag(self, monkeypatch):
        """AA_SKIP_ENV_VALIDATION=1 skips all env checks."""
        monkeypatch.setenv("AA_SKIP_ENV_VALIDATION", "1")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        svc = WorkflowResolutionService(
            action_configs={
                "summarizer": {"model_vendor": "openai"},
            },
        )
        result = svc.resolve_all()

        api_key_errors = [e for e in result.errors if "API key" in e.message]
        assert len(api_key_errors) == 0

    def test_empty_string_env_var_treated_as_missing(self, monkeypatch):
        """Empty string env var is treated as missing."""
        monkeypatch.setenv("OPENAI_API_KEY", "")
        monkeypatch.delenv("AA_SKIP_ENV_VALIDATION", raising=False)

        svc = WorkflowResolutionService(
            action_configs={
                "summarizer": {"model_vendor": "openai"},
            },
        )
        result = svc.resolve_all()

        api_key_errors = [e for e in result.errors if "API key" in e.message]
        assert len(api_key_errors) == 1


class TestSeedFileChecks:
    """Tests for _check_seed_file_references()."""

    def test_missing_seed_file_detected(self, tmp_path):
        """Missing seed file is detected with available files in hint."""
        # Setup directory structure: project/agent_config/workflow.yml + project/seed_data/
        project = tmp_path / "project"
        agent_config = project / "agent_config"
        agent_config.mkdir(parents=True)
        seed_data = project / "seed_data"
        seed_data.mkdir()
        (seed_data / "existing.json").write_text("{}")

        workflow_path = str(agent_config / "workflow.yml")

        svc = WorkflowResolutionService(
            action_configs={
                "loader": {
                    "context_scope": {
                        "seed_path": {"field1": "$file:missing.json"},
                    },
                },
            },
            workflow_config_path=workflow_path,
        )
        result = svc.resolve_all()

        seed_errors = [e for e in result.errors if "Seed file not found" in e.message]
        assert len(seed_errors) == 1
        assert "existing.json" in seed_errors[0].hint

    def test_existing_seed_file_passes(self, tmp_path):
        """Existing seed file produces no error."""
        project = tmp_path / "project"
        agent_config = project / "agent_config"
        agent_config.mkdir(parents=True)
        seed_data = project / "seed_data"
        seed_data.mkdir()
        (seed_data / "data.json").write_text("{}")

        workflow_path = str(agent_config / "workflow.yml")

        svc = WorkflowResolutionService(
            action_configs={
                "loader": {
                    "context_scope": {
                        "seed_path": {"field1": "$file:data.json"},
                    },
                },
            },
            workflow_config_path=workflow_path,
        )
        result = svc.resolve_all()

        seed_errors = [e for e in result.errors if "seed" in e.message.lower()]
        assert len(seed_errors) == 0

    def test_path_traversal_caught(self, tmp_path):
        """Path traversal in seed file reference is caught."""
        project = tmp_path / "project"
        agent_config = project / "agent_config"
        agent_config.mkdir(parents=True)
        seed_data = project / "seed_data"
        seed_data.mkdir()

        workflow_path = str(agent_config / "workflow.yml")

        svc = WorkflowResolutionService(
            action_configs={
                "loader": {
                    "context_scope": {
                        "seed_path": {"field1": "$file:../../etc/passwd"},
                    },
                },
            },
            workflow_config_path=workflow_path,
        )
        result = svc.resolve_all()

        seed_errors = [e for e in result.errors if "escapes base directory" in e.message]
        assert len(seed_errors) == 1

    def test_no_seed_path_config_no_errors(self):
        """No seed_path in config produces no errors."""
        svc = WorkflowResolutionService(
            action_configs={
                "loader": {"context_scope": {}},
            },
        )
        result = svc.resolve_all()

        seed_errors = [e for e in result.errors if "seed" in e.message.lower()]
        assert len(seed_errors) == 0

    def test_seed_data_dir_missing_graceful_skip(self, tmp_path):
        """When seed_data directory doesn't exist, gracefully skip (no errors)."""
        project = tmp_path / "project"
        agent_config = project / "agent_config"
        agent_config.mkdir(parents=True)
        # Intentionally do NOT create seed_data directory

        workflow_path = str(agent_config / "workflow.yml")

        svc = WorkflowResolutionService(
            action_configs={
                "loader": {
                    "context_scope": {
                        "seed_path": {"field1": "$file:data.json"},
                    },
                },
            },
            workflow_config_path=workflow_path,
        )
        result = svc.resolve_all()

        seed_errors = [e for e in result.errors if "seed" in e.message.lower()]
        assert len(seed_errors) == 0


class TestVendorRunModeCompatibility:
    """Tests for _check_vendor_run_mode_compatibility()."""

    def test_batch_mode_with_non_batch_vendor_produces_error(self):
        """Batch mode with a non-batch vendor (e.g., cohere) produces error."""
        svc = WorkflowResolutionService(
            action_configs={
                "local_action": {"model_vendor": "cohere", "run_mode": "batch"},
            },
        )
        result = svc.resolve_all()

        batch_errors = [e for e in result.errors if "batch" in e.message.lower()]
        assert len(batch_errors) == 1
        assert "cohere" in batch_errors[0].message

    def test_online_mode_passes_for_any_vendor(self):
        """Online mode passes for any vendor (no batch mode check needed)."""
        svc = WorkflowResolutionService(
            action_configs={
                "my_action": {"model_vendor": "ollama", "run_mode": "online"},
            },
        )
        result = svc.resolve_all()

        batch_errors = [e for e in result.errors if "batch" in e.message.lower()]
        assert len(batch_errors) == 0

    def test_batch_mode_with_batch_capable_vendor_passes(self):
        """Batch mode with a batch-capable vendor passes."""
        svc = WorkflowResolutionService(
            action_configs={
                "my_action": {"model_vendor": "openai", "run_mode": "batch"},
            },
        )
        result = svc.resolve_all()

        batch_errors = [e for e in result.errors if "batch" in e.message.lower()]
        assert len(batch_errors) == 0
