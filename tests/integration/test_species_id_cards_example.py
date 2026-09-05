"""The species_id_cards example runs end to end against the mock provider.

Guards the stage combinations the example exists for: three version fan-outs and
their merges, a 1->N expansion, a FILE-granularity reduce, and a guard reading a
tool's boolean. A regression in any of them shows up as a different action
tally, so the counts are asserted rather than described.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "species_id_cards"
WORKFLOW = "species_id_cards"


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> str:
    """Run the example offline in a copy, and hand back the CLI output."""
    project = tmp_path_factory.mktemp("species") / WORKFLOW
    shutil.copytree(EXAMPLE, project)

    config = project / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    config.write_text(
        config.read_text().replace("model_vendor: openai", "model_vendor: agac-provider")
    )
    (project / ".env").write_text("OPENAI_API_KEY=sk-not-used\n")

    result = subprocess.run(
        [
            str(Path(sys.executable).parent / "agac"),
            "run",
            "-a",
            WORKFLOW,
            "-u",
            "tools",
            "--fresh",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"run failed:\n{output[-3000:]}"
    return output


def test_every_action_either_completes_or_is_guard_filtered(run):
    assert "16 completed, 2 skipped" in run, (
        "the action tally moved: a stage stopped producing, or a guard stopped firing"
    )


@pytest.mark.parametrize(
    "action",
    [
        "extract_field_marks_1",
        "extract_field_marks_2",
        "extract_field_marks_3",
        "rank_diagnostic_value_1",
        "rank_diagnostic_value_2",
        "rank_diagnostic_value_3",
        "draft_id_note_1",
        "draft_id_note_2",
    ],
)
def test_each_version_fans_out_under_its_own_name(run, action):
    assert action in run, f"{action} never ran — the version fan-out did not expand"


@pytest.mark.parametrize("action", ["canonicalize_marks", "aggregate_votes", "consolidate_id_note"])
def test_each_merge_consumer_runs(run, action):
    assert re.search(rf"✓ {action}\b", run), f"{action} did not complete — its version merge failed"


def test_the_file_granularity_reduce_runs(run):
    assert re.search(r"✓ dedupe_across_guides\b", run)


def test_the_grounding_guard_filters_what_the_mock_could_not_ground(run):
    """The mock invents a quote, so no passage is ever located — both consumers filter."""
    for action in ("auto_review_note", "describe_confusion_risk"):
        assert re.search(rf"SKIP {action} \(All records guard-filtered", run), (
            f"{action} was not guard-filtered; the grounding guard stopped being load-bearing"
        )


def test_the_example_declares_the_tally_its_readme_promises():
    readme = (EXAMPLE / "README.md").read_text()
    assert "16 completed, 2 skipped" in readme, "the README's stated tally drifted from the test"


def test_every_named_schema_is_referenced_by_the_workflow():
    config = (
        EXAMPLE / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    ).read_text()
    for schema in (EXAMPLE / "schema" / WORKFLOW).glob("*.yml"):
        assert f"schema: {schema.stem}" in config, f"{schema.name} is not used by any action"


def test_the_staged_entries_parse_and_carry_the_fields_the_prompts_read():
    entries = json.loads(
        (
            EXAMPLE / "agent_workflow" / WORKFLOW / "agent_io" / "staging" / "entries.json"
        ).read_text()
    )
    assert entries, "no staged entries"
    for entry in entries:
        assert entry.get("entry_text"), "an entry has no entry_text for the prompts to read"
        assert entry.get("guide"), "an entry has no guide"
