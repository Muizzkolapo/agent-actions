"""Preflight seed checks must use the same directory resolution as the runtime."""

from agent_actions.validation.preflight.resolution_service import WorkflowResolutionService


def _make_service(workflow_path: str, seed_config: dict) -> WorkflowResolutionService:
    return WorkflowResolutionService(
        action_configs={
            "loader": {
                "context_scope": {"seed": seed_config},
            },
        },
        workflow_config_path=workflow_path,
    )


class TestProjectLevelSeedFallback:
    """The runtime falls back to the project-level seed dir; preflight must too."""

    def _project_layout(self, tmp_path, *, workflow_seed: bool, project_seed: bool):
        project = tmp_path / "proj"
        (project / "agent_workflow" / "wf" / "agent_config").mkdir(parents=True)
        (project / "agent_actions.yml").write_text("schema_path: schema\n")
        if project_seed:
            seed = project / "seed_data"
            seed.mkdir()
            (seed / "existing.json").write_text("{}")
        if workflow_seed:
            wf_seed = project / "agent_workflow" / "wf" / "seed_data"
            wf_seed.mkdir()
            (wf_seed / "data.json").write_text("{}")
        return str(project / "agent_workflow" / "wf" / "agent_config" / "wf.yml")

    def test_project_level_seed_dir_is_validated(self, tmp_path):
        """A missing ref is reported when seeds live only at the project level."""
        wf_path = self._project_layout(tmp_path, workflow_seed=False, project_seed=True)

        svc = _make_service(wf_path, {"field1": "$file:missing.json"})
        result = svc.resolve_all()

        seed_errors = [e for e in result.errors if "Seed file not found" in e.message]
        assert len(seed_errors) == 1
        assert "existing.json" in seed_errors[0].hint

    def test_project_level_seed_dir_valid_ref_passes(self, tmp_path):
        """A valid project-level ref passes instead of being skipped."""
        wf_path = self._project_layout(tmp_path, workflow_seed=False, project_seed=True)

        svc = _make_service(wf_path, {"field1": "$file:existing.json"})
        result = svc.resolve_all()

        seed_errors = [e for e in result.errors if "seed" in e.message.lower()]
        assert seed_errors == []

    def test_workflow_level_seed_dir_still_preferred(self, tmp_path):
        """When both levels exist, the workflow-level directory wins."""
        wf_path = self._project_layout(tmp_path, workflow_seed=True, project_seed=True)

        svc = _make_service(wf_path, {"field1": "$file:data.json"})
        result = svc.resolve_all()

        seed_errors = [e for e in result.errors if "seed" in e.message.lower()]
        assert seed_errors == []

    def test_seed_directives_with_no_seed_dir_anywhere_error(self, tmp_path):
        """Declared seed refs with no seed directory must error, not skip silently."""
        wf_path = self._project_layout(tmp_path, workflow_seed=False, project_seed=False)

        svc = _make_service(wf_path, {"field1": "$file:anything.json"})
        result = svc.resolve_all()

        dir_errors = [e for e in result.errors if "Seed data directory not found" in e.message]
        assert len(dir_errors) == 1

    def test_no_seed_directives_no_seed_dir_stays_silent(self, tmp_path):
        """Workflows that declare no seeds are unaffected by a missing directory."""
        project = tmp_path / "proj"
        (project / "agent_workflow" / "wf" / "agent_config").mkdir(parents=True)
        (project / "agent_actions.yml").write_text("schema_path: schema\n")
        wf_path = str(project / "agent_workflow" / "wf" / "agent_config" / "wf.yml")

        svc = WorkflowResolutionService(
            action_configs={"loader": {"context_scope": {}}},
            workflow_config_path=wf_path,
        )
        result = svc.resolve_all()

        seed_errors = [e for e in result.errors if "seed" in e.message.lower()]
        assert seed_errors == []
