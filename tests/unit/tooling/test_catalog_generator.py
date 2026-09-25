"""I-6: Coverage of CatalogGenerator.generate() — happy path and empty input."""

from agent_actions.tooling.docs.generator import CatalogGenerator
from agent_actions.tooling.docs.scanner import EVENT_TAIL_LIMIT


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
        readmes_data={},
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
        assert isinstance(result, dict)
        assert "metadata" in result


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


def _wf_events(workflow: str, seqs: list[int], hour: int = 10) -> dict:
    return {
        "workflow_name": workflow,
        "latest_run": None,
        "action_metrics": {},
        "runtime_warnings": [],
        "events": [
            {
                "seq": s,
                "event_type": "ActionCompleteEvent",
                "code": "A002",
                "level": "info",
                "category": "action",
                "diagnostic": False,
                "message": f"{workflow} step {s}",
                "meta": {
                    "timestamp": f"2026-09-22T{hour:02d}:00:00.{s:06d}Z",
                    "invocation_id": "inv1",
                    "workflow_name": workflow,
                },
                "data": {"action_name": f"step_{s}"},
            }
            for s in seqs
        ],
        "manifest": None,
    }


class TestCatalogGeneratorEventStream:
    """The Log Explorer reads catalog["logs"]["events"]."""

    def test_events_key_exists_for_empty_input(self):
        gen = _make_generator()
        result = gen.generate(**_empty_inputs())
        assert result["logs"]["events"] == []
        assert result["stats"]["total_events"] == 0

    def test_events_are_merged_newest_first_across_workflows(self):
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["runs_data"] = {
            "alpha": _wf_events("alpha", [0, 1], hour=10),
            "beta": _wf_events("beta", [0], hour=11),
        }
        result = gen.generate(**inputs)

        messages = [e["message"] for e in result["logs"]["events"]]
        assert messages == ["beta step 0", "alpha step 1", "alpha step 0"]
        assert result["stats"]["total_events"] == 3

    def test_event_id_is_namespaced_by_workflow(self):
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["runs_data"] = {"alpha": _wf_events("alpha", [7])}
        result = gen.generate(**inputs)

        assert result["logs"]["events"][0]["id"] == "alpha:7"

    def test_a_busy_log_does_not_crowd_out_a_quiet_one(self):
        """One workflow logging far more — and more recently — must not take the
        whole window, or its neighbours become undiagnosable."""
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["runs_data"] = {
            "alpha": _wf_events("alpha", list(range(EVENT_TAIL_LIMIT)), hour=11),
            "beta": _wf_events("beta", [0, 1], hour=9),
        }
        result = gen.generate(**inputs)

        events = result["logs"]["events"]
        assert len(events) == EVENT_TAIL_LIMIT
        sources = {e["id"].split(":")[0] for e in events}
        assert sources == {"alpha", "beta"}

    def test_the_project_log_shares_the_window_with_workflows(self):
        gen = _make_generator()
        inputs = _empty_inputs()
        inputs["logs_data"] = {
            **inputs["logs_data"],
            "events": _wf_events("logs", list(range(EVENT_TAIL_LIMIT)), hour=12)["events"],
        }
        inputs["runs_data"] = {"alpha": _wf_events("alpha", [0, 1], hour=9)}
        result = gen.generate(**inputs)

        sources = {e["id"].split(":")[0] for e in result["logs"]["events"]}
        assert sources == {"logs", "alpha"}
