"""`agac run --sandbox` follows a scenario: the mock fails, bends and delays calls on purpose.

The scenario is `sandbox.yml` at the project root, a preset or a file `--scenario` names.
Each fault goes through the path a real vendor's fault takes, so retry, repair and the
failure hint run as they would. The decisions are per record, so a parallel run fails the
records a serial run fails. A bad scenario stops the run before any call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._support.agac_cli import run_agac

WORKFLOW = "scripted"
ROWS = [
    {"page_id": f"p{n}", "text": text}
    for n, text in enumerate(
        ["calm sea", "high wind", "low tide", "grey sky", "warm rain", "cold dawn"], start=1
    )
]
ENV = {"OPENAI_API_KEY": ""}

CONFIG = """name: scripted
description: "Two LLM actions read each page"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: {run_mode}
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
  retry: {{ max_attempts: 3, base_delay: 0.01, max_delay: 0.01 }}
actions:
  - name: extract
    intent: "Extract"
    schema: extract_output
    prompt: $scripted.Extract
    context_scope: {{ observe: [source.page_id, source.text] }}
    expect:
      repair: {repair}
      expectations:
        - id: code_shape
          type: matches_regex
          field: code
          params: {{pattern: "^[A-Z]{{3}}-[0-9]{{2}}$"}}
        - id: tone_is_known
          type: accepted_values
          field: tone
          params: {{values: [calm, stormy]}}
  - name: classify
    intent: "Classify"
    schema: classify_output
    prompt: $scripted.Classify
    context_scope: {{ observe: [source.page_id, source.text] }}
"""

PROMPTS = """# scripted - prompt store

{prompt Extract}
Extract a code and the tone of this text.
{{ source.text }}
{end_prompt}

{prompt Classify}
Label this text.
{{ source.text }}
{end_prompt}
"""

SCHEMAS = {
    "extract_output": (
        "name: extract_output\nfields:\n  - id: page_id\n    type: string\n"
        "  - id: code\n    type: string\n  - id: tone\n    type: string\n"
    ),
    "classify_output": (
        "name: classify_output\nfields:\n  - id: page_id\n    type: string\n"
        "  - id: label\n    type: string\n"
    ),
}


def _project(base: Path, scenario: str | None = None, *, run_mode="online", repair="auto") -> Path:
    root = base / "project"
    workflow_dir = root / "agent_workflow" / WORKFLOW
    (workflow_dir / "agent_config").mkdir(parents=True)
    (workflow_dir / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\nschema_path: schema\n"
    )
    (workflow_dir / "agent_config" / f"{WORKFLOW}.yml").write_text(
        CONFIG.format(run_mode=run_mode, repair=repair)
    )
    (workflow_dir / "agent_io" / "staging" / "pages.json").write_text(json.dumps(ROWS))
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPTS)
    for name, text in SCHEMAS.items():
        (root / "schema" / WORKFLOW / f"{name}.yml").write_text(text)
    if scenario is not None:
        (root / "sandbox.yml").write_text(scenario)
    return root


def _io(root: Path) -> Path:
    return root / "agent_workflow" / WORKFLOW / "agent_io"


def _run(root: Path, *args: str, command: str = "run"):
    return run_agac(root, command, "-w", WORKFLOW, "--sandbox", *args, env=ENV)


def _said(result) -> str:
    return " ".join((result.stdout + result.stderr).split())


def _ok(result):
    assert result.returncode == 0, _said(result)
    return result


def _stored(root: Path, action: str) -> list[dict]:
    """The answers the action stored; a failed record keeps the parse error it got instead."""
    shown = _ok(run_agac(root, "records", "-w", WORKFLOW, "-A", action, "--sandbox", env=ENV))
    answers = [record["content"][action] for record in json.loads(shown.stdout)]
    return [answer for answer in answers if "_parse_error" not in answer]


def _pages(root: Path, action: str) -> set[str]:
    return {record["page_id"] for record in _stored(root, action)}


def _failed(root: Path, action: str) -> int:
    shown = _ok(run_agac(root, "dispositions", "-w", WORKFLOW, "--sandbox", "--json", env=ENV))
    counts = next(e for e in json.loads(shown.stdout)["actions"] if e["name"] == action)["counts"]
    return counts.get("failed", 0) + counts.get("exhausted", 0)


ALL_PAGES = {row["page_id"] for row in ROWS}


@pytest.mark.parametrize(
    "kind",
    ["rate_limit", "timeout", "server_error", "refusal", "truncated", "empty", "invalid_json"],
)
def test_each_error_kind_recovers_on_the_attempt_it_heals_at(tmp_path, kind):
    root = _project(
        tmp_path,
        f"actions:\n  extract:\n    errors: {{rate: 1.0, kinds: [{kind}], heal_on_attempt: 2}}\n",
    )

    result = _ok(_run(root))

    assert _pages(root, "extract") == ALL_PAGES
    assert "SANDBOX scenario sandbox.yml: 6 errors, 0 rules broken, 0 batch results dropped" in (
        _said(result)
    )


MATCHED = """records:
  - match: {source.page_id: p3}
    actions: {extract: {error: refusal}}
"""


def test_a_record_that_fails_every_attempt_is_a_failure_the_hint_names(tmp_path):
    root = _project(tmp_path, MATCHED)

    result = _run(root)

    assert result.returncode == 3, _said(result)
    said = _said(result)
    assert "Workflow finished with failed or exhausted records in: extract" in said, said
    assert f"repair them with agac retry -w {WORKFLOW} --sandbox." in said, said
    assert _failed(root, "extract") == 1
    assert _pages(root, "extract") == ALL_PAGES - {"p3"}
    assert _pages(root, "classify") == ALL_PAGES


def test_the_hint_names_the_scenario_given_and_a_retry_with_another_repairs(tmp_path):
    root = _project(tmp_path)
    (root / "faults.yml").write_text(MATCHED)

    result = _run(root, "--scenario", "faults.yml")

    assert result.returncode == 3, _said(result)
    assert f"agac retry -w {WORKFLOW} --sandbox --scenario faults.yml." in _said(result)
    assert "SANDBOX scenario faults.yml: 3 errors" in _said(result)

    repaired = _ok(_run(root, "--scenario", "happy", command="retry"))

    assert _failed(root, "extract") == 0
    assert _pages(root, "extract") == ALL_PAGES
    assert "SANDBOX scenario happy: 0 errors, 0 rules broken" in _said(repaired)


BROKEN = "actions:\n  extract:\n    break_rules: {rules: [matches_regex], rate: 1.0%s}\n"


def test_a_broken_rule_is_repaired_on_the_attempt_it_heals_at(tmp_path):
    root = _project(tmp_path, BROKEN % ", heal_on_attempt: 2")

    result = _ok(_run(root))

    assert "6 rules broken" in _said(result)
    codes = [record["code"] for record in _stored(root, "extract")]
    assert len(codes) == 6
    assert all(len(code) == 6 and code[3] == "-" for code in codes), codes


def test_a_broken_rule_fails_the_real_check(tmp_path):
    root = _project(tmp_path, BROKEN % "", repair="none")

    _ok(_run(root))

    stored = _stored(root, "extract")
    assert len(stored) == 6
    for record in stored:
        code = record["code"]
        assert not (isinstance(code, str) and len(code) == 6 and code[3] == "-"), code
        assert record["tone"] in ("calm", "stormy")


def test_a_pinned_field_holds_its_value(tmp_path):
    root = _project(tmp_path, "actions:\n  classify:\n    pin: {label: urgent}\n")

    _ok(_run(root))

    assert {record["label"] for record in _stored(root, "classify")} == {"urgent"}


def test_a_matched_record_takes_its_own_pin(tmp_path):
    root = _project(
        tmp_path,
        "actions:\n  classify:\n    pin: {label: routine}\n"
        "records:\n  - match: {source.page_id: p2}\n    actions: {classify: {pin: {label: urgent}}}\n",
    )

    _ok(_run(root))

    labels = {record["page_id"]: record["label"] for record in _stored(root, "classify")}
    assert labels == {page: "urgent" if page == "p2" else "routine" for page in ALL_PAGES}


HALF = "seed: 11\ndefaults:\n  errors: {rate: 0.5, kinds: [refusal]}\n"


def test_a_parallel_run_fails_the_records_a_serial_run_fails(tmp_path):
    serial = _project(tmp_path / "serial", HALF)
    parallel = _project(tmp_path / "parallel", HALF)

    first = _run(serial, "--execution-mode", "sequential")
    second = _run(parallel, "--execution-mode", "parallel", "--concurrency-limit", "4")

    assert first.returncode == second.returncode == 3, _said(first) + _said(second)
    assert "sequential" in _said(first) and "parallel" in _said(second)
    for action in ("extract", "classify"):
        kept = _pages(serial, action)
        assert kept == _pages(parallel, action)
        assert set() < kept < ALL_PAGES, (action, kept)


def test_the_chaos_preset_completes_a_workflow_with_retry_and_repair(tmp_path):
    root = _project(tmp_path)

    result = _ok(_run(root, "--scenario", "chaos"))

    assert "SANDBOX scenario chaos:" in _said(result)
    assert _pages(root, "extract") == ALL_PAGES
    assert _pages(root, "classify") == ALL_PAGES


@pytest.mark.parametrize(
    ("scenario", "named"),
    [
        ("actions:\n  extract:\n    errors: {kinds: [explode]}\n", "actions.extract.errors.kinds"),
        ("actions:\n  summarise: {latency_ms: 1}\n", "actions.summarise"),
        ("defaults:\n  latency_ms: [9, 1]\n", "defaults.latency_ms"),
        ("batch:\n  drops: 0.5\n", "batch.drops"),
    ],
)
def test_a_bad_scenario_stops_the_run_before_any_call(tmp_path, scenario, named):
    root = _project(tmp_path, scenario)

    result = _run(root)

    assert result.returncode != 0
    said = _said(result)
    assert "sandbox.yml" in said and named in said, said
    assert not (_io(root) / "store" / f"{WORKFLOW}.sandbox.db").exists()
    assert not (_io(root) / "sandbox" / "target").exists()


def test_a_scenario_without_the_sandbox_is_a_usage_error(tmp_path):
    root = _project(tmp_path)

    result = run_agac(root, "run", "-w", WORKFLOW, "--scenario", "chaos", env=ENV)

    assert result.returncode == 2
    assert "--scenario needs --sandbox" in result.stderr


def test_a_batch_result_dropped_comes_back_in_the_retry_batch(tmp_path):
    root = _project(tmp_path, "batch: {drop_rate: 1.0}\n", run_mode="batch")

    result = _ok(_run(root, "--wait", "--poll", "1"))

    assert "12 batch results dropped" in _said(result)
    assert _pages(root, "extract") == ALL_PAGES
    assert _pages(root, "classify") == ALL_PAGES


def test_a_batch_error_entry_is_retried_until_it_heals(tmp_path):
    root = _project(
        tmp_path,
        "actions:\n  extract:\n    errors: {rate: 1.0, kinds: [server_error], heal_on_attempt: 2}\n",
        run_mode="batch",
    )

    result = _ok(_run(root, "--wait", "--poll", "1"))

    assert "6 errors" in _said(result)
    assert _pages(root, "extract") == ALL_PAGES


def test_a_batch_the_scenario_fails_fails_its_action(tmp_path):
    root = _project(tmp_path, "batch: {fail: [classify]}\n", run_mode="batch")

    result = _run(root, "--wait", "--poll", "1")

    assert result.returncode == 1, _said(result)
    said = _said(result)
    assert "the provider reports it failed, not completed" in said, said
    assert "✗ classify" in said, said
    assert _pages(root, "extract") == ALL_PAGES


def test_a_batch_waits_the_status_checks_the_scenario_asks_for(tmp_path):
    root = _project(
        tmp_path,
        "batch: {polls_until_complete: 2, complete_after_seconds: 999}\n",
        run_mode="batch",
    )

    submitted = _run(root)
    checked_once = _run(root)
    collected = _run(root)

    assert submitted.returncode == checked_once.returncode == 4, _said(checked_once)
    assert _ok(collected)
    assert _pages(root, "extract") == ALL_PAGES
