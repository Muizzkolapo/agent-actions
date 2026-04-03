"""I-6: Coverage of CatalogGenerator.generate() — happy path and empty input."""

from agent_actions.tooling.docs.generator import CatalogGenerator


def _make_generator(workflows_data=None, project_path="/tmp"):
    return CatalogGenerator(workflows_data or {}, project_path)


def _empty_inputs():
    return dict(
        prompts_data={},
        schemas_data={},
        tool_functions_data={},
        runs_data={},
        logs_data={
            "events_path": None,
            "recent_invocations": [],
            "validation_errors": [],
            "validation_warnings": [],
        },
        vendors_data={},
        error_types_data=[],
        event_types_data=[],
        examples_data=[],
        data_loaders_data=[],
        processing_states_data=[],
        workflow_data={},
        readmes_data=[],
    )


class TestCatalogGeneratorEmptyInput:
    """CatalogGenerator.generate() with all-empty inputs returns valid catalog structure."""

    def test_returns_dict(self):
        gen = _make_generator()
        result = gen.generate(**_empty_inputs())
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        gen = _make_generator()
        result = gen.generate(**_empty_inputs())
        for key in ("metadata", "stats"):
            assert key in result, f"Missing key: {key}"

    def test_stats_are_zero_for_empty_input(self):
        gen = _make_generator()
        result = gen.generate(**_empty_inputs())
        stats = result["stats"]
        assert stats["total_workflows"] == 0
        assert stats["total_actions"] == 0

    def test_no_exception_on_empty_input(self):
        gen = _make_generator()
        result = gen.generate(**_empty_inputs())
        assert result is not None


class TestCatalogGeneratorHappyPath:
    """CatalogGenerator.generate() with minimal real-ish input."""

    def test_workflow_count_reflected_in_stats(self, tmp_path):
        import yaml

        wf_yml = tmp_path / "my_workflow.yml"
        wf_yml.write_text(
            yaml.dump(
                {
                    "name": "my_workflow",
                    "description": "A test workflow",
                    "actions": [
                        {"name": "step_one", "intent": "Does something"},
                    ],
                }
            )
        )
        # workflows_data maps name -> {"rendered": path_or_none, "original": path}
        workflows_data = {"my_workflow": {"rendered": None, "original": str(wf_yml)}}
        gen = _make_generator(workflows_data)
        result = gen.generate(**_empty_inputs())
        stats = result["stats"]
        assert stats["total_workflows"] == 1

    def test_metadata_contains_generator_info(self):
        gen = _make_generator()
        result = gen.generate(**_empty_inputs())
        assert "metadata" in result
        assert "generated_at" in result["metadata"]

    def test_metadata_contains_project_name(self):
        gen = _make_generator(project_path="/home/user/my_project")
        result = gen.generate(**_empty_inputs())
        assert result["metadata"]["project_name"] == "my_project"

    def test_metadata_project_name_none_without_path(self):
        gen = CatalogGenerator({}, project_path=None)
        result = gen.generate(**_empty_inputs())
        assert result["metadata"]["project_name"] is None

    def test_metadata_project_name_root_path(self):
        gen = _make_generator(project_path="/")
        result = gen.generate(**_empty_inputs())
        assert result["metadata"]["project_name"] == ""
