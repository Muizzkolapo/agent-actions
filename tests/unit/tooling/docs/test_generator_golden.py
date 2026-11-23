"""Golden-output pins for the docs catalog generator.

The workflow parser and schema service are stubbed so these files pin what
``generator.py`` itself assembles and prints, not what its collaborators resolve.
Regenerate with ``UPDATE_GENERATOR_GOLDEN=1`` only for an intended output change.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_actions.models.action_schema import FieldInfo, FieldSource
from agent_actions.tooling.docs import generator
from agent_actions.tooling.docs.generator import CatalogGenerator, generate_docs
from agent_actions.tooling.docs.parser import WorkflowParser
from agent_actions.tooling.docs.scanner import ReadmeData
from agent_actions.workflow.schema_service import WorkflowSchemaService

GOLDEN_DIR = Path(__file__).parent / "golden"


def _assert_golden(name: str, actual: str) -> None:
    path = GOLDEN_DIR / name
    if os.environ.get("UPDATE_GENERATOR_GOLDEN"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert actual == path.read_text(encoding="utf-8")


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 2, 3, 4, 5)


def _field(name, *, dropped=False, field_type="string"):
    return FieldInfo(
        name=name,
        source=FieldSource.SCHEMA,
        is_required=False,
        is_dropped=dropped,
        field_type=field_type,
        description=f"{name} field",
    )


_ACTION_SCHEMAS = {
    "extract": SimpleNamespace(
        output_fields=[_field("title"), _field("body"), _field("secret", dropped=True)]
    ),
    "score": SimpleNamespace(output_fields=[]),
    "solo_step": SimpleNamespace(output_fields=[_field("answer", field_type="number")]),
}


class _FakeSchemaService:
    def get_action_schema(self, action_name):
        return _ACTION_SCHEMAS.get(action_name)


def _workflows() -> dict[str, dict]:
    review_actions = {
        "extract": {
            "name": "extract",
            "intent": "extract",
            "type": "llm",
            "prompt": "review.extract",
            "schema": "extract_schema",
        },
        "summarize": {
            "name": "summarize",
            "intent": "summarize",
            "type": "llm",
            "schema": {"summary": "string", "score": {"type": "number"}},
            "context_scope": {
                "observe": ["extract.title", "extract.body"],
                "drop": ["extract.body", "extract.a.*.c", "extract.body", "nodot", "extract.*"],
            },
        },
        "score": {
            "name": "score",
            "type": "tool",
            "kind": "tool",
            "implementation": "score_fn",
            "schema": "unknown_schema",
            "context_scope": "not-a-mapping",
        },
        "scribe": {"name": "scribe", "kind": "llm", "intent": "write"},
        "lookup": {
            "name": "lookup",
            "type": "tool",
            "kind": "tool",
            "implementation": "missing_fn",
            "prompt": "not.a.known.prompt",
            "context_scope": {"observe": ["extract.title"]},
        },
    }
    return {
        "review.yml": {
            "name": "review",
            "description": "Review flow",
            "path": "agent_config/review.yml",
            "version": "2.0.0",
            "defaults": {"model_vendor": "openai"},
            "actions": review_actions,
        },
        "empty.yml": {
            "name": "empty",
            "description": "",
            "path": "agent_config/empty.yml",
            "version": "1.0.0",
            "actions": {},
        },
        "solo.rendered.yml": {
            "name": "solo",
            "description": "Solo",
            "path": "agent_config/solo.rendered.yml",
            "version": "1.0.0",
            "defaults": {},
            "actions": {
                "solo_step": {
                    "name": "solo_step",
                    "type": "llm",
                    "prompt": "solo.step",
                    "schema": "solo_schema",
                }
            },
        },
    }


_WORKFLOWS_DATA = {
    "review": {"rendered": None, "original": "review.yml"},
    "broken": {"rendered": None, "original": "broken.yml"},
    "empty": {"rendered": None, "original": "empty.yml"},
    "solo": {"rendered": "solo.rendered.yml", "original": "solo.yml"},
}


@pytest.fixture
def stubbed(monkeypatch):
    """Stub the parser and schema service; record each parse call."""
    calls: list[tuple] = []
    workflows = _workflows()

    def fake_parse(yaml_path, project_root=None, *, rendered=False):
        calls.append((yaml_path, rendered))
        return workflows.get(yaml_path)

    monkeypatch.setattr(WorkflowParser, "parse_workflow", staticmethod(fake_parse))
    monkeypatch.setattr(
        WorkflowSchemaService,
        "from_action_configs",
        classmethod(lambda cls, *a, **k: _FakeSchemaService()),
    )
    monkeypatch.setattr(generator, "datetime", _FixedDatetime)
    return calls


def _events(source: str, levels: list[str], minute: int) -> list[dict]:
    return [
        {
            "seq": i,
            "level": level,
            "event_type": "LogEvent",
            "message": f"{source} {level} {i}",
            "meta": {"timestamp": f"2026-01-01T00:{minute:02d}:{i:02d}"},
        }
        for i, level in enumerate(levels)
    ]


def _inputs(readme_dir: Path) -> dict:
    (readme_dir / "logo.png").write_bytes(b"\x89PNG")
    return dict(
        prompts_data={
            "review.extract": {"content": "Extract", "workflow": "review"},
            "solo.step": {"content": "Step", "workflow": "solo"},
            "orphan": {"content": "Unused"},
        },
        schemas_data={
            "extract_schema": {"fields": ["title", "body"]},
            "solo_schema": {"fields": ["answer"]},
        },
        tool_functions_data={
            "score_fn": {"name": "score_fn", "file": "tools/review/score.py"},
            "other_fn": {"name": "other_fn"},
        },
        runs_data={
            "review": {
                "action_metrics": {"extract": {"calls": 3}, "ghost": {"calls": 1}},
                "latest_run": {"id": "run_1", "status": "SUCCESS"},
                "manifest": {"actions": ["extract"]},
                "runtime_warnings": [
                    {"action_name": "extract", "message": "slow", "timestamp": "t1"},
                    {"event_type": "BatchEvent", "level": "error", "message": "boom"},
                    {"level": "warn"},
                ],
                "events": _events("review", ["info", "error", "warn", "debug"], 1),
                "level_counts": {"info": 10, "error": 1, "warn": 1},
                "is_workflow": True,
                "total_runs": 4,
            },
            "stray": {
                "events": _events("stray", ["info", "error"], 2),
                "level_counts": {"info": 1, "error": 1},
                "is_workflow": False,
            },
            "logs": {
                "events": _events("logs", ["warn"], 3),
                "level_counts": {"warn": 1},
                "is_workflow": False,
            },
        },
        logs_data={
            "events_path": "agent_io/logs/events.json",
            "recent_invocations": [{"id": "inv_1"}],
            "validation_errors": [{"message": "e1"}, {"message": "e2"}],
            "validation_warnings": [{"message": "w1"}],
            "events": _events("project", ["info", "error", "info"], 0),
            "level_counts": {"info": 5, "error": 1},
            "is_workflow": False,
        },
        vendors_data={"openai": {"name": "OpenAI"}, "anthropic": {"name": "Anthropic"}},
        error_types_data={"config": {"error_count": 3}, "runtime": {"error_count": 2}, "x": {}},
        event_types_data={"workflow": {"event_count": 4}, "action": {}},
        examples_data={"ex1": {}, "ex2": {}},
        data_loaders_data={"json": {}, "csv": {}},
        processing_states_data={"Status": {}, "Kind": {}},
        workflow_data={"review": {"nodes": {"a": {}, "b": {}}}, "solo": {}},
        readmes_data={
            "review": ReadmeData(
                content="# Review\n![logo](logo.png) ![gone](missing.png) "
                '<img src="https://example.com/x.png">\n',
                source_dir=readme_dir,
            ),
            "solo": ReadmeData(content="# Solo\n", source_dir=readme_dir),
        },
        executions_data=[
            {
                "id": "run_1",
                "status": "FAILED",
                "workflow_name": "review",
                "error_message": "it broke",
                "ended_at": "e1",
                "actions": {"extract": {"status": "failed", "error": "bad", "ended_at": "e2"}},
            },
            {"id": "run_2", "status": "failed", "workflow_id": "wf_2", "started_at": "s2"},
            {"status": "failed", "actions": None},
            {
                "id": "run_4",
                "status": "COMPLETED",
                "started_at": "s4",
                "actions": {
                    "a": {"status": "FAILED"},
                    "b": {"status": "COMPLETED"},
                    "c": {"status": None},
                },
            },
            {"id": "run_5", "status": None},
        ],
    )


def _dump(catalog: dict) -> str:
    return json.dumps(catalog, indent=2, default=str) + "\n"


class TestGenerateGolden:
    def test_the_catalog_matches_the_golden_file(self, stubbed, tmp_path):
        artefact = tmp_path / "artefact"
        gen = CatalogGenerator(dict(_WORKFLOWS_DATA), project_path="/projects/demo")
        catalog = gen.generate(**_inputs(tmp_path), artefact_dir=artefact)

        _assert_golden("catalog_generate.json", _dump(catalog))
        assert (artefact / "images" / "review" / "logo.png").read_bytes() == b"\x89PNG"
        assert stubbed == [
            ("review.yml", False),
            ("broken.yml", False),
            ("empty.yml", False),
            ("solo.rendered.yml", True),
        ]

    def test_without_an_artefact_dir_the_readme_is_left_as_written(self, stubbed, tmp_path):
        inputs = _inputs(tmp_path)
        catalog = CatalogGenerator(dict(_WORKFLOWS_DATA)).generate(**inputs)

        readme = catalog["workflows"]["review"]["readme"]
        assert readme == inputs["readmes_data"]["review"].content
        assert catalog["workflows"]["review"]["readme"] is not None
        assert not (tmp_path / "images").exists()

    def test_no_inputs_yields_the_golden_empty_catalog(self, stubbed):
        catalog = CatalogGenerator({}, project_path=None).generate()

        _assert_golden("catalog_empty.json", _dump(catalog))

    def test_a_workflow_with_no_runs_and_no_readme(self, stubbed):
        catalog = CatalogGenerator({"solo": _WORKFLOWS_DATA["solo"]}).generate(runs_data={})

        entry = catalog["workflows"]["solo"]
        assert (entry["latest_run"], entry["manifest"], entry["readme"]) == (None, None, None)
        assert "metrics" not in entry["actions"]["solo_step"]


def _patch_scanners(monkeypatch, inputs: dict, workflows_data: dict) -> list:
    seen: list = []

    def scanned(value, name):
        def scan(*args):
            seen.append((name, args))
            return value

        return scan

    scans = {
        "scan_workflows": workflows_data,
        "scan_tool_functions": inputs["tool_functions_data"],
        "scan_prompts": inputs["prompts_data"],
        "scan_schemas": inputs["schemas_data"],
        "scan_runs": inputs["runs_data"],
        "scan_logs": inputs["logs_data"],
        "scan_vendors": inputs["vendors_data"],
        "scan_error_types": inputs["error_types_data"],
        "scan_event_types": inputs["event_types_data"],
        "scan_examples": inputs["examples_data"],
        "scan_data_loaders": inputs["data_loaders_data"],
        "scan_processing_states": inputs["processing_states_data"],
        "scan_workflow_data": inputs["workflow_data"],
        "scan_readmes": inputs["readmes_data"],
    }
    for name, value in scans.items():
        monkeypatch.setattr(generator.scanner, name, scanned(value, name))
    monkeypatch.setattr(generator, "get_tool_dirs", lambda root: ["tools"])
    return seen


def _singular_inputs(readme_dir: Path) -> dict:
    inputs = _inputs(readme_dir)
    inputs.update(
        prompts_data={"review.extract": {}},
        schemas_data={"extract_schema": {}},
        tool_functions_data={"score_fn": {}},
        logs_data={"validation_errors": [{}], "validation_warnings": [{}]},
        vendors_data={"openai": {}},
        error_types_data={"config": {"error_count": 1}},
        event_types_data={"workflow": {"event_count": 1}},
        examples_data={"ex1": {}},
        data_loaders_data={"json": {}},
        processing_states_data={"Status": {}},
        workflow_data={"review": {"nodes": {"a": {}}}},
        runs_data={
            "review": {"runtime_warnings": [{"message": "w"}, {"level": "error", "message": "e"}]}
        },
        readmes_data={},
    )
    return inputs


def _quiet_inputs(readme_dir: Path) -> dict:
    inputs = _inputs(readme_dir)
    inputs.update(
        prompts_data={},
        schemas_data={},
        tool_functions_data={},
        runs_data={},
        logs_data={},
        vendors_data={},
        error_types_data={},
        event_types_data={},
        examples_data={},
        data_loaders_data={},
        processing_states_data={},
        workflow_data={},
        readmes_data={},
    )
    return inputs


class TestGenerateDocsGolden:
    @pytest.fixture
    def project(self, tmp_path, monkeypatch):
        project = tmp_path / "proj"
        project.mkdir()
        monkeypatch.chdir(tmp_path)
        return project

    def _run(self, monkeypatch, capsys, project, inputs, workflows_data):
        seen = _patch_scanners(monkeypatch, inputs, workflows_data)
        out = project.parent / "artefact"
        result = generate_docs(str(project), out)
        return result, out, capsys.readouterr().out, seen

    def test_a_plural_project_with_prior_runs(self, stubbed, project, monkeypatch, capsys):
        inputs = _inputs(project)
        out = project.parent / "artefact"
        out.mkdir()
        runs_json = json.dumps({"executions": inputs["executions_data"], "kept": True})
        (out / "runs.json").write_text(runs_json)

        result, out, stdout, seen = self._run(
            monkeypatch, capsys, project, inputs, dict(_WORKFLOWS_DATA)
        )

        assert result is True
        _assert_golden("generate_docs_plural.txt", stdout)
        _assert_golden("generate_docs_plural.json", (out / "catalog.json").read_text())
        assert (out / "runs.json").read_text() == runs_json
        root = project.resolve()
        assert seen[0] == ("scan_workflows", (root,))
        assert ("scan_tool_functions", (root, ["tools"])) in seen
        assert ("scan_error_types", ()) in seen

    def test_a_singular_project_with_one_prior_run(self, stubbed, project, monkeypatch, capsys):
        out = project.parent / "artefact"
        out.mkdir()
        (out / "runs.json").write_text(json.dumps({"executions": [{"id": "r", "status": "OK"}]}))

        result, out, stdout, _ = self._run(
            monkeypatch,
            capsys,
            project,
            _singular_inputs(project),
            {"review": _WORKFLOWS_DATA["review"]},
        )

        assert result is True
        _assert_golden("generate_docs_singular.txt", stdout)
        assert json.loads((out / "catalog.json").read_text())["stats"]["total_runs"] == 1

    def test_a_quiet_project_without_runs_json(self, stubbed, project, monkeypatch, capsys):
        result, out, stdout, _ = self._run(
            monkeypatch,
            capsys,
            project,
            _quiet_inputs(project),
            {"empty": _WORKFLOWS_DATA["empty"]},
        )

        assert result is True
        _assert_golden("generate_docs_quiet.txt", stdout)
        runs = json.loads((out / "runs.json").read_text())
        assert runs["executions"] == []
        assert runs["metadata"]["total_runs"] == 0
        assert runs.keys() == generator._empty_runs_data().keys()

    def test_an_unreadable_runs_json_is_ignored(
        self, stubbed, project, monkeypatch, capsys, caplog
    ):
        out = project.parent / "artefact"
        out.mkdir()
        (out / "runs.json").write_text("{not json")

        with caplog.at_level(logging.DEBUG, logger=generator.__name__):
            result, out, _, _ = self._run(
                monkeypatch,
                capsys,
                project,
                _quiet_inputs(project),
                {"empty": _WORKFLOWS_DATA["empty"]},
            )

        assert result is True
        assert (out / "runs.json").read_text() == "{not json"
        assert any(
            r.levelno == logging.DEBUG
            and r.getMessage().startswith("Failed to load runs.json for execution data:")
            for r in caplog.records
        )
        assert json.loads((out / "catalog.json").read_text())["stats"]["total_runs"] == 0

    def test_no_workflows_writes_nothing(self, stubbed, project, monkeypatch, capsys, caplog):
        with caplog.at_level(logging.WARNING, logger=generator.__name__):
            result, out, stdout, seen = self._run(
                monkeypatch, capsys, project, _quiet_inputs(project), {}
            )

        assert result is False
        assert stdout == "No workflows found in project!\n"
        assert [r.getMessage() for r in caplog.records] == [f"No workflows found in {project}"]
        assert not out.exists()
        assert [name for name, _ in seen] == ["scan_workflows"]

    def test_the_summary_is_logged(self, stubbed, project, monkeypatch, capsys, caplog):
        with caplog.at_level(logging.INFO, logger=generator.__name__):
            self._run(
                monkeypatch,
                capsys,
                project,
                _inputs(project),
                {"review": _WORKFLOWS_DATA["review"]},
            )

        assert [r.getMessage() for r in caplog.records if r.levelno == logging.INFO] == [
            "Documentation catalog generated: 1 workflows, 5 actions"
        ]

    def test_an_output_dir_outside_the_cwd_is_shown_absolute(
        self, stubbed, project, monkeypatch, capsys, tmp_path_factory
    ):
        elsewhere = tmp_path_factory.mktemp("elsewhere") / "out"
        _patch_scanners(monkeypatch, _quiet_inputs(project), {"empty": _WORKFLOWS_DATA["empty"]})

        assert generate_docs(str(project), elsewhere) is True
        assert capsys.readouterr().out.endswith(f"\nDone. Documentation compiled to {elsewhere}/\n")


def test_colliding_log_names_get_suffixes_by_run_name_not_insertion_order():
    from agent_actions.tooling.docs.generator import _event_sources

    a = {"is_workflow": False, "events": [{"id": "a"}]}
    b = {"is_workflow": False, "events": [{"id": "b"}]}
    logs = {"events": [{"id": "cli"}]}

    forward = _event_sources(logs, {"logs": a, "x_logs": b})
    backward = _event_sources(logs, {"x_logs": b, "logs": a})

    assert forward == backward
    assert [name for name, _ in forward] == ["project:logs", "project:logs~2", "project:x_logs"]
