"""Audit of the expectations repair loop, driven through the real CLI.

Every test here scaffolds an actual agac project on disk and runs `agac run`
against it. The only thing mocked is the provider call itself, so the config
loader, the action expander, preflight, the invocation strategy, the loop, the
record envelope and the SQLite store all run for real.

That matters: the two genuine bugs this subsystem shipped with (a response
arriving as a length-1 list rather than a dict, and `expect:` never being
forwarded through the expander) were both invisible to service-level tests that
mocked the generation seam directly, and both were caught by a run like these.
"""

import json
import os
import sqlite3
import textwrap
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from agent_actions.input.preprocessing.filtering.guard_filter import (
    reset_global_guard_filter,
)
from agent_actions.utils.path_utils import reset_path_manager

WF = "repair_audit"

PROJECT_CONFIG = """\
default_agent_config:
  api_key: OPENAI_API_KEY
  model_name: gpt-4o-mini
  model_vendor: openai
  ephemeral: false
schema_path: schema
tool_path: ["tools"]
required_by_default: true
"""

WORKFLOW_HEADER = f"""\
name: {WF}
description: repair loop audit
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_name: gpt-4o-mini
  model_vendor: openai
  api_key: OPENAI_API_KEY
actions:
"""

# One action producing `ideas`, with a rule that needs at least three of them.
BRAINSTORM = """\
  - name: brainstorm
    intent: generate ideas
    kind: llm
    prompt: "List ideas."
    context_scope:
      observe: ["source.*"]
    schema:
      fields:
        - id: ideas
          type: array
          required: true
    expect:
{expect_body}
"""


def _expect(body: str) -> str:
    return textwrap.indent(textwrap.dedent(body).rstrip("\n"), "      ")


ENOUGH_IDEAS = """\
expectations:
  - id: enough_ideas
    type: item_count
    field: ideas
    min: 3
    hint: list at least three distinct ideas
"""

# The same action carrying reprompt instead of expect, for parity comparison.
REPROMPT_ONLY = """\
  - name: brainstorm
    intent: generate ideas
    kind: llm
    prompt: "List ideas."
    context_scope:
      observe: ["source.*"]
    schema:
      fields:
        - id: ideas
          type: array
          required: true
    reprompt:
      max_attempts: 2
      on_schema_mismatch: reprompt
"""


@pytest.fixture()
def project(tmp_path):
    """A real agac project on disk; `write_actions` swaps the action block.

    A completed `agac run` shuts down the process-global guard filter's thread
    pool, so it is reset around every test — otherwise the next test anywhere in
    the session hits "cannot schedule new futures after shutdown".
    """
    reset_path_manager()
    root = tmp_path / "proj"
    for sub in (
        "prompt_store",
        "templates",
        "tools",
        "schema",
        f"{WF}/agent_config",
        f"{WF}/agent_io/staging",
    ):
        (root / sub).mkdir(parents=True, exist_ok=True)
    (root / "agent_actions.yml").write_text(PROJECT_CONFIG)
    (root / "prompt_store" / f"{WF}.md").write_text("List ideas about {{ topic }}.\n")
    (root / WF / "agent_io" / "staging" / "input.json").write_text(
        json.dumps([{"topic": "renewable energy"}])
    )
    cfg = root / WF / "agent_config" / f"{WF}.yml"

    class Project:
        path = root
        config_path = cfg

        def write_actions(self, actions: str) -> None:
            cfg.write_text(WORKFLOW_HEADER + actions)

        def write_tool(self, name: str, source: str) -> None:
            tools = root / "tools" / WF
            tools.mkdir(parents=True, exist_ok=True)
            (tools / f"{name}.py").write_text(textwrap.dedent(source))

    p = Project()
    p.write_actions(BRAINSTORM.format(expect_body=_expect(ENOUGH_IDEAS)))
    yield p
    reset_path_manager()
    reset_global_guard_filter()


@contextmanager
def _cwd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


class Run:
    """What one `agac run` produced."""

    def __init__(self, result, prompts, root):
        self.result = result
        self.prompts = prompts
        self._root = root

    @property
    def exit_code(self):
        return self.result.exit_code

    @property
    def calls(self):
        return len(self.prompts)

    def _stored(self):
        """Every JSON body the run persisted, from SQLite and target files."""
        bodies = []
        io_dir = self._root / WF / "agent_io"
        for db in io_dir.rglob("*.db"):
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                tables = [
                    r[0] for r in con.execute("select name from sqlite_master where type='table'")
                ]
                for table in tables:
                    cols = [r[1] for r in con.execute(f"pragma table_info({table})")]
                    payloads = [c for c in cols if c in ("content", "data", "record", "payload")]
                    for row in (
                        con.execute(f"select {', '.join(payloads)} from {table}")
                        if payloads
                        else []
                    ):
                        for cell in row:
                            if isinstance(cell, (str, bytes)):
                                try:
                                    bodies.append(json.loads(cell))
                                except ValueError:
                                    pass
            finally:
                con.close()
        for path in io_dir.rglob("*.json"):
            if "staging" in path.parts or path.name.startswith("."):
                continue
            try:
                bodies.append(json.loads(path.read_text()))
            except ValueError:
                pass
        return bodies

    def find(self, predicate):
        """Every nested dict in the persisted output satisfying *predicate*."""
        hits = []

        def walk(node):
            if isinstance(node, dict):
                if predicate(node):
                    hits.append(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        for body in self._stored():
            walk(body)
        return hits

    def verdicts(self):
        return self.find(lambda d: isinstance(d.get("expect"), dict))

    def tombstones(self):
        return self.find(lambda d: d.get("_tombstone") is True)


def run_workflow(project, responses, *, by_action=None):
    """Run the workflow with a scripted provider.

    *responses* is consumed in order for every call; *by_action* maps an action
    name to its own list, for multi-action workflows.
    """
    from agent_actions.cli.main import cli

    prompts = []
    per_action_counts = {}

    def fake_invoke(
        model_vendor,
        agent_config,
        prompt_config,
        context_data,
        schema,
        granularity,
        tool_args=None,
        source_content=None,
        action_name=None,
    ):
        prompts.append(prompt_config)
        name = action_name or agent_config.get("name")
        if by_action and name in by_action:
            scripted = by_action[name]
            index = per_action_counts.get(name, 0)
            per_action_counts[name] = index + 1
            return [scripted[min(index, len(scripted) - 1)]]
        index = len(prompts) - 1
        return [responses[min(index, len(responses) - 1)]]

    with (
        _cwd(project.path),
        patch(
            "agent_actions.llm.realtime.services.invocation.ClientInvocationService.invoke_client",
            side_effect=fake_invoke,
        ),
    ):
        os.environ.setdefault("OPENAI_API_KEY", "sk-audit-not-used")
        result = CliRunner().invoke(cli, ["run", "-a", WF], catch_exceptions=False)
    return Run(result, prompts, project.path)


# ---------------------------------------------------------------------------
# Repair succeeds
# ---------------------------------------------------------------------------


class TestRepairSucceeds:
    def test_auto_repair_ships_the_regenerated_record(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect("repair: auto\nmax_iterations: 3\n" + ENOUGH_IDEAS)
            )
        )
        run = run_workflow(
            project,
            [
                {"ideas": ["only one"]},
                {"ideas": ["alpha", "beta", "gamma"]},
            ],
        )
        assert run.exit_code == 0
        assert run.calls == 2
        verdicts = run.verdicts()
        assert verdicts, "no record with a verdict was persisted"
        assert any(
            v["ideas"] == ["alpha", "beta", "gamma"] and v["expect"]["overall_pass"] is True
            for v in verdicts
        )

    def test_a_first_attempt_that_passes_costs_one_call(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect("repair: auto\nmax_iterations: 3\n" + ENOUGH_IDEAS)
            )
        )
        run = run_workflow(project, [{"ideas": ["a", "b", "c"]}])
        assert run.exit_code == 0
        assert run.calls == 1

    def test_auto_repair_sends_the_failure_and_hint_to_the_model(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect("repair: auto\nmax_iterations: 3\n" + ENOUGH_IDEAS)
            )
        )
        run = run_workflow(
            project,
            [
                {"ideas": ["only one"]},
                {"ideas": ["alpha", "beta", "gamma"]},
            ],
        )
        second = run.prompts[1]
        assert "enough_ideas" in second
        assert "list at least three distinct ideas" in second
        assert "only one" in second, "the failed output must be quoted back"

    def test_retry_repair_resends_the_original_prompt(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect("repair: retry\nmax_iterations: 3\n" + ENOUGH_IDEAS)
            )
        )
        run = run_workflow(
            project,
            [
                {"ideas": ["only one"]},
                {"ideas": ["alpha", "beta", "gamma"]},
            ],
        )
        assert run.calls == 2
        assert run.prompts[0] == run.prompts[1]


# ---------------------------------------------------------------------------
# The structural gate
# ---------------------------------------------------------------------------


class TestStructuralGate:
    def test_a_schema_violating_record_is_repaired(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect("repair: auto\nmax_iterations: 3\n" + ENOUGH_IDEAS)
            )
        )
        run = run_workflow(
            project,
            [
                {"wrong_key": "not the schema"},
                {"ideas": ["alpha", "beta", "gamma"]},
            ],
        )
        assert run.exit_code == 0
        assert run.calls == 2
        assert any(v["expect"]["overall_pass"] is True for v in run.verdicts())

    def test_the_structural_failure_reaches_the_repair_prompt(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect("repair: auto\nmax_iterations: 3\n" + ENOUGH_IDEAS)
            )
        )
        run = run_workflow(
            project,
            [
                {"wrong_key": "not the schema"},
                {"ideas": ["alpha", "beta", "gamma"]},
            ],
        )
        assert "_structural" in run.prompts[1]

    def test_observe_mode_never_applies_the_structural_gate(self, project):
        project.write_actions(
            BRAINSTORM.format(expect_body=_expect("repair: none\n" + ENOUGH_IDEAS))
        )
        run = run_workflow(project, [{"wrong_key": "not the schema"}])
        assert run.calls == 1
        assert not any(
            o.get("id") == "_structural"
            for v in run.verdicts()
            for o in v["expect"].get("outcomes", [])
        )


# ---------------------------------------------------------------------------
# Exhaustion
# ---------------------------------------------------------------------------


class TestExhaustion:
    def test_return_last_ships_the_annotated_record(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect(
                    "repair: retry\nmax_iterations: 2\non_exhausted: return_last\n" + ENOUGH_IDEAS
                )
            )
        )
        run = run_workflow(project, [{"ideas": ["never enough"]}])
        assert run.calls == 2
        verdicts = run.verdicts()
        assert verdicts, "return_last must still ship the record"
        assert all(v["expect"]["overall_pass"] is False for v in verdicts)
        assert any("enough_ideas" in v["expect"]["failed"] for v in verdicts)

    def test_fail_refuses_to_ship_the_failing_record(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect(
                    "repair: retry\nmax_iterations: 2\non_exhausted: fail\n" + ENOUGH_IDEAS
                )
            )
        )
        run = run_workflow(project, [{"ideas": ["never enough"]}])
        assert run.calls == 2
        assert not run.verdicts(), "fail mode must not ship the failing record"
        assert run.exit_code != 0

    def test_fail_matches_reprompt_exhaustion_exactly(self, project):
        """The expectations arm must not invent its own exhaustion shape.

        Neither layer persists its tombstone when a single-record file exhausts:
        the file-processing layer counts the file as unprocessed and errors the
        action. That is pre-existing behaviour of the EXHAUSTED path shared by
        every recovery layer, not something the expectations arm introduced, and
        this test is what will notice if the two ever diverge.
        """
        expectations_actions = BRAINSTORM.format(
            expect_body=_expect(
                "repair: retry\nmax_iterations: 2\non_exhausted: fail\n" + ENOUGH_IDEAS
            )
        )
        project.write_actions(expectations_actions)
        expectations_run = run_workflow(project, [{"ideas": ["never enough"]}])

        project.write_actions(REPROMPT_ONLY)
        reprompt_run = run_workflow(project, [{"wrong_key": "never conforms"}])

        assert expectations_run.exit_code == reprompt_run.exit_code
        assert expectations_run.tombstones() == reprompt_run.tombstones()
        assert not expectations_run.verdicts()

    def test_raise_halts_the_run(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect(
                    "repair: retry\nmax_iterations: 2\non_exhausted: raise\n" + ENOUGH_IDEAS
                )
            )
        )
        run = run_workflow(project, [{"ideas": ["never enough"]}])
        assert run.exit_code != 0
        assert not run.verdicts(), "a halted run must not ship the failing record"

    def test_max_iterations_counts_the_first_generation(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect(
                    "repair: retry\nmax_iterations: 4\non_exhausted: return_last\n" + ENOUGH_IDEAS
                )
            )
        )
        run = run_workflow(project, [{"ideas": ["never enough"]}])
        assert run.calls == 4


# ---------------------------------------------------------------------------
# Observe mode is untouched
# ---------------------------------------------------------------------------


class TestObserveMode:
    def test_observe_calls_once_and_attaches_a_failing_verdict(self, project):
        project.write_actions(
            BRAINSTORM.format(expect_body=_expect("repair: none\n" + ENOUGH_IDEAS))
        )
        run = run_workflow(project, [{"ideas": ["only one"]}])
        assert run.exit_code == 0
        assert run.calls == 1
        verdicts = run.verdicts()
        assert verdicts
        assert all(v["expect"]["overall_pass"] is False for v in verdicts)
        assert all(v["ideas"] == ["only one"] for v in verdicts)

    def test_observe_records_a_passing_verdict(self, project):
        project.write_actions(
            BRAINSTORM.format(expect_body=_expect("repair: none\n" + ENOUGH_IDEAS))
        )
        run = run_workflow(project, [{"ideas": ["a", "b", "c"]}])
        assert run.calls == 1
        assert all(v["expect"]["overall_pass"] is True for v in run.verdicts())


# ---------------------------------------------------------------------------
# The verdict as a downstream gate
# ---------------------------------------------------------------------------


PUBLISH_GUARDED = """\
  - name: publish
    intent: publish approved ideas
    kind: llm
    prompt: "Publish."
    dependencies: ["brainstorm"]
    guard:
      condition: 'brainstorm.expect.overall_pass == true'
      on_false: filter
    context_scope:
      observe: ["brainstorm.*"]
    schema:
      fields:
        - id: headline
          type: string
          required: true
"""


class TestVerdictAsAGate:
    def test_a_repaired_record_passes_the_downstream_guard(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect("repair: auto\nmax_iterations: 3\n" + ENOUGH_IDEAS)
            )
            + PUBLISH_GUARDED
        )
        run = run_workflow(
            project,
            [],
            by_action={
                "brainstorm": [{"ideas": ["only one"]}, {"ideas": ["alpha", "beta", "gamma"]}],
                "publish": [{"headline": "Three ideas"}],
            },
        )
        assert run.exit_code == 0
        assert run.find(lambda d: d.get("headline") == "Three ideas"), (
            "the repaired record should have satisfied the guard and reached publish"
        )

    def test_an_unrepaired_record_is_filtered_by_the_guard(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect(
                    "repair: retry\nmax_iterations: 2\non_exhausted: return_last\n" + ENOUGH_IDEAS
                )
            )
            + PUBLISH_GUARDED
        )
        run = run_workflow(
            project,
            [],
            by_action={
                "brainstorm": [{"ideas": ["never enough"]}],
                "publish": [{"headline": "should never be generated"}],
            },
        )
        assert not run.find(lambda d: d.get("headline") == "should never be generated"), (
            "a failing verdict must stop the record at the guard"
        )


# ---------------------------------------------------------------------------
# Project-defined rules drive the loop too
# ---------------------------------------------------------------------------


class TestExtensionPointsDriveRepair:
    def test_a_projects_own_check_drives_regeneration(self, project):
        project.write_tool(
            "quality",
            """
            from agent_actions import expectation_check

            @expectation_check("all_ideas_distinct")
            def all_ideas_distinct(value, params):
                items = list(value or [])
                if len(items) == len(set(items)):
                    return True, ""
                return False, f"{len(items) - len(set(items))} duplicate idea(s)"
        """,
        )
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect("""\
            repair: auto
            max_iterations: 3
            expectations:
              - id: distinct
                type: all_ideas_distinct
                field: ideas
            """)
            )
        )
        run = run_workflow(
            project,
            [
                {"ideas": ["same", "same"]},
                {"ideas": ["alpha", "beta"]},
            ],
        )
        assert run.exit_code == 0
        assert run.calls == 2
        assert "duplicate idea" in run.prompts[1]
        assert any(v["expect"]["overall_pass"] is True for v in run.verdicts())

    def test_an_expression_rule_drives_regeneration(self, project):
        project.write_actions(
            BRAINSTORM.format(
                expect_body=_expect("""\
            repair: auto
            max_iterations: 3
            expectations:
              - id: has_ideas
                type: expression
                condition: 'ideas != null'
            """)
            )
        )
        run = run_workflow(
            project,
            [
                {"ideas": None},
                {"ideas": ["alpha"]},
            ],
        )
        assert run.calls == 2
        assert any(v["expect"]["overall_pass"] is True for v in run.verdicts())


# ---------------------------------------------------------------------------
# Preflight refuses shapes the loop cannot serve
# ---------------------------------------------------------------------------


class TestPreflightRefusals:
    @pytest.mark.parametrize(
        "mutation, expected",
        [
            ("    granularity: File\n", "granularity"),
            ("    run_mode: batch\n", "batch"),
        ],
    )
    def test_repair_is_refused_on_shapes_it_cannot_serve(self, project, mutation, expected):
        actions = BRAINSTORM.format(
            expect_body=_expect("repair: auto\nmax_iterations: 3\n" + ENOUGH_IDEAS)
        ).replace("    intent: generate ideas\n", "    intent: generate ideas\n" + mutation)
        project.write_actions(actions)
        run = run_workflow(project, [{"ideas": ["a", "b", "c"]}])
        assert run.exit_code != 0
        assert run.calls == 0, "preflight must refuse before any provider call"
        assert expected in run.result.output.lower()

    # The tool-action refusal and the observe-at-file-granularity allowance are
    # covered in tests/unit/validation/test_expectations_validator.py: a valid
    # tool action needs a UDF implementation and the FILE path needs a different
    # record shape, so asserting either here would exercise the fixture rather
    # than the guard.
