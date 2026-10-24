"""`agac retry --filter` keeps one failed record out of the workflow for good (1548).

A record that fails the same way on every retry — here alpha, whose page `extract`
cannot read — was re-targeted by every `agac retry`, and the only way to stop it was
writing a `filtered` disposition through the storage API by hand. That edit was also
undone by the next retry resuming an interrupted one, whose snapshot put the failure
back.

`--filter <action>:<record_id> --reason ...` records the exclusion and exits: alpha is
filtered at `extract` with the reason given, the actions below hold nothing for it, as
under a guard's `on_false: filter`, and a live retry manifest is changed to match. Every
other record is left as it was: gamma, failing while `FAIL_GAMMA` exists, is still
retried. Each run is its own `agac` process against local tools.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "integration" / "fixtures" / "expectation_authors"
WORKFLOW = "drop_one"
REASON = "page has no extractable content"

_CONFIG = """\
name: drop_one
description: "A record that always fails, one that fails for now, and one that never does"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  model_vendor: agac-provider
  model_name: gpt-oss:120b-cloud
  api_key: OLLAMA_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: extract
    kind: tool
    intent: "Extract"
    schema: tool_action_output
    impl: drop_one_extract
    context_scope: { observe: [source.page_content] }
    expect: { repair: none }
%(guard)s  - name: finalize
    kind: tool
    dependencies: [extract]
    intent: "Finalize"
    schema: tool_action_output
    impl: drop_one_finalize
    context_scope: { observe: [extract.summary] }
    expect: { repair: none }
"""

_GUARD = "    guard: { condition: 'source.page_content != \"Page alpha.\"', on_false: filter }\n"

# STOP stops the process at finalize.
_TOOLS = """\
from pathlib import Path
from typing import Any

from agent_actions import udf_tool

HERE = Path(__file__).resolve().parents[2]


def _find(data: Any, key: str):
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            hit = _find(value, key)
            if hit is not None:
                return hit
    return None


@udf_tool
def drop_one_extract(data: Any, *args) -> list[dict]:
    page = str(_find(data, "page_content"))
    if "alpha" in page:
        raise RuntimeError("alpha has no extractable content")
    if "gamma" in page and (HERE / "FAIL_GAMMA").exists():
        raise RuntimeError("gamma fails for now")
    return [{"summary": page, "exam_density": "low"}]


@udf_tool
def drop_one_finalize(data: Any, *args) -> list[dict]:
    summary = str(_find(data, "summary"))
    if (HERE / "STOP").exists():
        raise KeyboardInterrupt
    with (HERE / "handed.log").open("a") as log:
        log.write(summary + "\\n")
    return [{"summary": f"FINAL[{summary}]", "exam_density": "low"}]
"""


PAGES = ["Page alpha.", "Page beta.", "Page gamma."]


def _project(tmp_path: Path, *, guard: bool = False, pages: list[str] = PAGES) -> Path:
    root = tmp_path / ("guarded" if guard else "project")
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("logs"))
    workflow = root / "agent_workflow" / WORKFLOW
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(
        _CONFIG % {"guard": _GUARD if guard else ""}
    )
    staging = workflow / "agent_io" / "staging"
    staging.mkdir(parents=True)
    staging.joinpath("pages.json").write_text(json.dumps([{"page_content": p} for p in pages]))
    (root / "tools" / WORKFLOW).mkdir()
    (root / "tools" / WORKFLOW / "drop_one_tools.py").write_text(_TOOLS)
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    return root


def _agac(project: Path, *args: str, code: int = 0) -> str:
    result = run_agac(project, *args)
    output = result.stdout + result.stderr
    assert result.returncode == code, output
    return output


def _db(project: Path) -> Path:
    (db,) = (project / "agent_workflow" / WORKFLOW / "agent_io" / "store").glob("*.db")
    return db


def _dispositions(project: Path) -> dict[tuple[str, str], tuple[str, str | None, str | None]]:
    return {
        (action, record_id): (disposition, reason, detail)
        for action, record_id, disposition, reason, detail in stored_rows(
            _db(project),
            "select action_name, record_id, disposition, reason, detail from record_disposition",
        )
    }


def _target_guids(project: Path, action: str) -> list[str]:
    guids: list[str] = []
    for (blob,) in stored_rows(
        _db(project), "select data from target_data where action_name = ?", action
    ):
        loaded = json.loads(blob)
        guids.extend(row["source_guid"] for row in (loaded if isinstance(loaded, list) else []))
    return sorted(guids)


def _failed_at_extract(project: Path, page: str) -> str:
    (record_id,) = [
        record_id
        for (action, record_id), (disposition, reason, _) in _dispositions(project).items()
        if action == "extract"
        and record_id != "__node__"
        and disposition == "failed"
        and page in (reason or "")
    ]
    return record_id


def _succeeded_at_extract(project: Path) -> str:
    (record_id,) = [
        record_id
        for (action, record_id), (disposition, _, _) in _dispositions(project).items()
        if action == "extract" and disposition == "success"
    ]
    return record_id


def _failed(tmp_path: Path) -> tuple[Path, str, str]:
    """Run once: alpha and gamma fail at extract, beta goes through."""
    project = _project(tmp_path)
    (project / "FAIL_GAMMA").write_text("")
    _agac(project, "run", "-a", WORKFLOW, "--fresh")
    return project, _failed_at_extract(project, "alpha"), _failed_at_extract(project, "gamma")


def _filter(project: Path, *targets: str, code: int = 0, reason: str | None = REASON) -> str:
    args = ["retry", "-a", WORKFLOW]
    for target in targets:
        args += ["--filter", target]
    if reason is not None:
        args += ["--reason", reason]
    return _agac(project, *args, code=code)


def _handed(project: Path) -> list[str]:
    log = project / "handed.log"
    return sorted(log.read_text().split("\n")[:-1]) if log.exists() else []


class TestAFilteredRecord:
    def test_is_no_longer_retried_while_another_failed_record_still_is(self, tmp_path):
        project, alpha, gamma = _failed(tmp_path)

        output = _filter(project, f"extract:{alpha}")

        assert "Filtered 1 record(s)" in output, output
        plan = _agac(project, "retry", "-a", WORKFLOW, "--dry-run")
        assert "Records to retry: 1" in plan, plan
        assert gamma[:8] in plan, plan
        assert alpha[:8] not in plan, plan

    def test_stores_the_reason_given(self, tmp_path):
        project, alpha, _ = _failed(tmp_path)

        _filter(project, f"extract:{alpha}")

        disposition, reason, detail = _dispositions(project)[("extract", alpha)]
        assert (disposition, reason) == ("filtered", REASON)
        assert "agac retry --filter" in (detail or ""), detail

    def test_runs_nothing(self, tmp_path):
        project, alpha, _ = _failed(tmp_path)
        before = _handed(project)

        output = _filter(project, f"extract:{alpha}")

        assert "Re-running workflow" not in output, output
        assert _handed(project) == before

    def test_is_held_below_as_a_guard_filter_holds_it(self, tmp_path):
        project, alpha, _ = _failed(tmp_path)
        _filter(project, f"extract:{alpha}")
        (project / "FAIL_GAMMA").unlink()

        output = _agac(project, "retry", "-a", WORKFLOW)

        assert "cannot be attributed" not in output, output
        assert _handed(project) == ["Page beta.", "Page gamma."], output
        guarded = _project(tmp_path, guard=True)
        _agac(guarded, "run", "-a", WORKFLOW, "--fresh")
        assert _target_guids(project, "finalize") == _target_guids(guarded, "finalize")
        # Its tombstone stays where it failed: a run carrying it forward re-asks a
        # record it holds no row for, and here no guard would filter it again.
        assert _target_guids(project, "extract") == sorted(
            [alpha, *_target_guids(guarded, "extract")]
        )
        held = {key: value[0] for key, value in _dispositions(project).items()}
        assert held == {key: value[0] for key, value in _dispositions(guarded).items()}
        quarantined = _agac(project, "dispositions", "-a", WORKFLOW, "--quarantined")
        assert alpha[:8] not in quarantined, quarantined

    def test_survives_the_resume_of_an_interrupted_retry(self, tmp_path):
        project, alpha, gamma = _failed(tmp_path)
        (project / "FAIL_GAMMA").unlink()
        (project / "STOP").write_text("")
        _agac(project, "retry", "-a", WORKFLOW, code=130)
        (project / "STOP").unlink()
        manifest = project / "agent_workflow" / WORKFLOW / "agent_io" / "store" / WORKFLOW
        manifest = manifest / "_retry_manifest.json"
        assert manifest.exists()

        _filter(project, f"extract:{alpha}")

        kept = json.loads(manifest.read_text())["dispositions"]
        assert [
            (row["disposition"], row["reason"])
            for row in kept
            if (row["action_name"], row["record_id"]) == ("extract", alpha)
        ] == [("filtered", REASON)], kept
        assert not [
            row for row in kept if row["record_id"] == alpha and row["action_name"] != "extract"
        ]
        plan = _agac(project, "retry", "-a", WORKFLOW, "--dry-run")
        assert alpha[:8] not in plan, plan
        assert gamma[:8] in plan, plan
        output = _agac(project, "retry", "-a", WORKFLOW)
        assert _dispositions(project)[("extract", alpha)][:2] == ("filtered", REASON), output
        assert ("finalize", alpha) not in _dispositions(project), output
        assert "Page alpha." not in _handed(project), output


def test_a_record_whose_file_was_never_written_is_filtered_with_a_warning(tmp_path):
    project = _project(tmp_path, pages=["Page alpha."])
    _agac(project, "run", "-a", WORKFLOW, "--fresh", code=1)
    alpha = _failed_at_extract(project, "alpha")

    output = _filter(project, f"extract:{alpha}")

    assert _dispositions(project)[("extract", alpha)][:2] == ("filtered", REASON)
    assert "hold no stored row" in output and "agent_io/staging/" in output, output


class TestARefusedFilter:
    def test_an_unknown_action_is_named_with_the_actions_there_are(self, tmp_path):
        project, alpha, _ = _failed(tmp_path)

        output = _filter(project, f"extrakt:{alpha}", code=1)

        assert "extrakt" in output and "extract" in output and "finalize" in output, output
        assert _dispositions(project)[("extract", alpha)][0] == "failed"

    def test_an_unknown_record_names_where_to_find_record_ids(self, tmp_path):
        project, _, _ = _failed(tmp_path)

        output = _filter(project, "extract:no-such-record", code=1)

        assert "no-such-record" in output, output
        assert f"agac dispositions -a {WORKFLOW}" in output, output

    def test_a_record_that_did_not_fail_there_is_refused(self, tmp_path):
        project, _, _ = _failed(tmp_path)
        beta = _succeeded_at_extract(project)

        output = _filter(project, f"extract:{beta}", code=1)

        assert "success" in output and "failed or exhausted" in output, output
        assert _dispositions(project)[("extract", beta)][0] == "success"

    def test_one_bad_target_writes_none_of_them(self, tmp_path):
        project, alpha, gamma = _failed(tmp_path)

        _filter(project, f"extract:{alpha}", "extract:no-such-record", code=1)

        assert _dispositions(project)[("extract", alpha)][0] == "failed"
        assert _dispositions(project)[("extract", gamma)][0] == "failed"

    @pytest.mark.parametrize(
        ("args", "names"),
        [
            (["--filter", "extract:x"], "--reason"),
            (["--filter", "extract:x", "--reason", "  "], "--reason"),
            (["--filter", "extract", "--reason", REASON], "<action>:<record_id>"),
            (["--reason", REASON], "--filter"),
            (["--filter", "extract:x", "--reason", REASON, "--from", "extract"], "--from"),
            (["--filter", "extract:x", "--reason", REASON, "--record", "x"], "--record"),
        ],
    )
    def test_a_malformed_command_is_a_usage_error(self, tmp_path, args, names):
        project, alpha, _ = _failed(tmp_path)

        output = _agac(project, "retry", "-a", WORKFLOW, *args, code=2)

        assert names in output, output
        assert _dispositions(project)[("extract", alpha)][0] == "failed"

    def test_a_dry_run_writes_nothing(self, tmp_path):
        project, alpha, _ = _failed(tmp_path)

        output = _agac(
            project,
            "retry",
            "-a",
            WORKFLOW,
            "--filter",
            f"extract:{alpha}",
            "--reason",
            REASON,
            "--dry-run",
        )

        assert "would filter 1 record(s)" in output.lower(), output
        assert _dispositions(project)[("extract", alpha)][0] == "failed"
