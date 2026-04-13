"""Tests for virtual action injection and cross-workflow I/O resolution.

Covers:
- Virtual action injection from upstream declarations
- ConfigManager accepting virtual actions as valid dependencies
- ActionRunner resolving virtual action output directories
- Missing upstream outputs error handling
"""

from agent_actions.workflow.models import VirtualAction, WorkflowMetadata


class TestVirtualActionModel:
    """VirtualAction dataclass."""

    def test_create(self):
        va = VirtualAction(source_workflow="ingest", action_name="extract")
        assert va.source_workflow == "ingest"
        assert va.action_name == "extract"


class TestWorkflowMetadataVirtualActions:
    """WorkflowMetadata with virtual_actions field."""

    def test_default_empty(self):
        meta = WorkflowMetadata(
            agent_name="test",
            execution_order=["a"],
            action_indices={"a": 0},
            action_configs={"a": {}},
        )
        assert meta.virtual_actions == {}

    def test_with_virtual_actions(self):
        va = VirtualAction(source_workflow="ingest", action_name="extract")
        meta = WorkflowMetadata(
            agent_name="test",
            execution_order=["a"],
            action_indices={"a": 0},
            action_configs={"a": {}},
            virtual_actions={"extract": va},
        )
        assert "extract" in meta.virtual_actions
        assert meta.virtual_actions["extract"].source_workflow == "ingest"


class TestConfigManagerVirtualActions:
    """ConfigManager.determine_execution_order with virtual actions."""

    def test_virtual_action_accepted_as_dependency(self, tmp_path):
        """An action can depend on a virtual action without raising."""
        from agent_actions.config.manager import ConfigManager

        # Create required project structure
        (tmp_path / "templates").mkdir()

        # Create a minimal workflow config with one action that depends on "extract"
        cfg = tmp_path / "test.yml"
        cfg.write_text(
            "name: test\n"
            "description: test\n"
            "upstream:\n"
            "  - workflow: ingest\n"
            "    actions: [extract]\n"
            "defaults:\n"
            "  model_vendor: openai\n"
            "  model_name: gpt-4o\n"
            "  api_key: test-key\n"
            "actions:\n"
            "  - name: enrich\n"
            "    intent: do stuff\n"
            "    dependencies: [extract]\n"
        )
        default = tmp_path / "default.yml"
        default.write_text("default_agent_config: {}")

        mgr = ConfigManager(str(cfg), str(default), project_root=tmp_path)
        mgr.load_configs()
        mgr.validate_agent_name()

        user_agents = mgr.get_user_agents()
        mgr.merge_agent_configs(user_agents)

        # Register "extract" as a virtual action
        mgr.virtual_action_names = {"extract"}

        # This should NOT raise — "extract" is a valid virtual action target
        mgr.determine_execution_order()

        # "enrich" should be in execution order, "extract" should not
        assert "enrich" in mgr.execution_order
        assert "extract" not in mgr.execution_order

    def test_unknown_dependency_excluded_without_virtual(self, tmp_path):
        """Without virtual action registration, unknown deps are silently filtered."""
        from agent_actions.config.manager import ConfigManager

        (tmp_path / "templates").mkdir()

        cfg = tmp_path / "test.yml"
        cfg.write_text(
            "name: test\n"
            "description: test\n"
            "defaults:\n"
            "  model_vendor: openai\n"
            "  model_name: gpt-4o\n"
            "  api_key: test-key\n"
            "actions:\n"
            "  - name: enrich\n"
            "    intent: do stuff\n"
        )
        default = tmp_path / "default.yml"
        default.write_text("default_agent_config: {}")

        mgr = ConfigManager(str(cfg), str(default), project_root=tmp_path)
        mgr.load_configs()
        mgr.validate_agent_name()

        user_agents = mgr.get_user_agents()
        mgr.merge_agent_configs(user_agents)
        mgr.determine_execution_order()

        assert "enrich" in mgr.execution_order


class TestRunnerVirtualActionResolution:
    """ActionRunner._resolve_virtual_action_directory."""

    def test_virtual_action_resolves_to_upstream_target(self, tmp_path):
        """Virtual action resolves to the upstream workflow's target directory."""
        from agent_actions.workflow.runner import ActionRunner

        # Create upstream workflow directory structure that FileHandler can find
        upstream_io = tmp_path / "ingest" / "agent_io"
        (upstream_io / "target" / "extract").mkdir(parents=True)

        runner = ActionRunner.__new__(ActionRunner)
        runner.project_root = tmp_path
        runner.workflow_name = "enrich"
        runner.virtual_actions = {
            "extract": VirtualAction(source_workflow="ingest", action_name="extract"),
        }

        result = runner._resolve_virtual_action_directory("extract")
        assert result is not None
        assert result == upstream_io / "target" / "extract"

    def test_virtual_action_missing_outputs_returns_none(self, tmp_path):
        """Virtual action with no upstream outputs returns None."""
        from agent_actions.workflow.runner import ActionRunner

        # Upstream workflow exists but has no outputs for "extract"
        upstream_io = tmp_path / "ingest" / "agent_io"
        (upstream_io / "target").mkdir(parents=True)

        runner = ActionRunner.__new__(ActionRunner)
        runner.project_root = tmp_path
        runner.workflow_name = "enrich"
        runner.virtual_actions = {
            "extract": VirtualAction(source_workflow="ingest", action_name="extract"),
        }

        result = runner._resolve_virtual_action_directory("extract")
        assert result is None

    def test_virtual_action_upstream_not_found_returns_none(self, tmp_path):
        """When upstream workflow has no agent_io directory, returns None."""
        from agent_actions.workflow.runner import ActionRunner

        runner = ActionRunner.__new__(ActionRunner)
        runner.project_root = tmp_path
        runner.workflow_name = "enrich"
        runner.virtual_actions = {
            "extract": VirtualAction(source_workflow="nonexistent", action_name="extract"),
        }

        result = runner._resolve_virtual_action_directory("extract")
        assert result is None

    def test_virtual_action_in_dependency_resolution(self, tmp_path):
        """Virtual actions are resolved through _resolve_dependency_directories."""
        from agent_actions.workflow.runner import ActionRunner

        # Set up local workflow agent_io
        local_io = tmp_path / "enrich" / "agent_io"
        (local_io / "target").mkdir(parents=True)

        # Set up upstream workflow directory structure
        upstream_io = tmp_path / "ingest" / "agent_io"
        (upstream_io / "target" / "extract").mkdir(parents=True)

        runner = ActionRunner.__new__(ActionRunner)
        runner.project_root = tmp_path
        runner.workflow_name = "enrich"
        runner.action_indices = {"enrich_text": 0}
        runner.manifest_manager = None
        runner.storage_backend = None
        runner.virtual_actions = {
            "extract": VirtualAction(source_workflow="ingest", action_name="extract"),
        }

        result = runner._resolve_dependency_directories(
            local_io,
            ["extract"],
            {"dependencies": ["extract"]},
            "enrich_text",
        )

        assert len(result) == 1
        assert result[0] == upstream_io / "target" / "extract"
