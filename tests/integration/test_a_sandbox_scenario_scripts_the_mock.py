"""`agac run --sandbox` follows a scenario: the mock fails, bends and delays calls on purpose.

The scenario is `sandbox.yml` at the project root, a preset or a file `--scenario` names.
Each fault goes through the path a real vendor's fault takes, so retry, repair and the
failure hint run as they would. The decisions are per record and its input, so a parallel
run fails the records a serial run fails, and two fresh runs fail the same records, also
below an expansion. The attempts count on across runs in the sandbox store. A bad scenario
stops the run before any call.
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
    expect:
      repair: auto
      expectations:
        - id: label_is_set
          type: not_null
          field: label
"""

# Each prompt prints source.text, so the request's context block leaves it out.
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


def _project(
    base: Path,
    scenario: str | None = None,
    *,
    run_mode="online",
    repair="auto",
    rows: list[dict] = ROWS,
) -> Path:
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
    (workflow_dir / "agent_io" / "staging" / "pages.json").write_text(json.dumps(rows))
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(PROMPTS)
    for name, text in SCHEMAS.items():
        (root / "schema" / WORKFLOW / f"{name}.yml").write_text(text)
    if scenario is not None:
        (root / "sandbox.yml").write_text(scenario)
    return root


def _io(root: Path) -> Path:
    return root / "agent_workflow" / WORKFLOW / "agent_io"


def _run(root: Path, *args: str, command: str = "run", workflow: str = WORKFLOW):
    return run_agac(root, command, "-w", workflow, "--sandbox", *args, env=ENV)


def _said(result) -> str:
    return " ".join((result.stdout + result.stderr).split())


def _ok(result):
    assert result.returncode == 0, _said(result)
    return result


def _summary(result) -> str:
    """The one scenario line the command printed."""
    lines = [line for line in result.stdout.splitlines() if line.startswith("SANDBOX scenario")]
    assert len(lines) == 1, _said(result)
    return lines[0]


def _stored(root: Path, action: str, workflow: str = WORKFLOW) -> list[dict]:
    """The answers the action stored; a failed record keeps the parse error it got instead."""
    shown = _ok(run_agac(root, "records", "-w", workflow, "-A", action, "--sandbox", env=ENV))
    answers = [record["content"][action] for record in json.loads(shown.stdout)]
    return [answer for answer in answers if "_parse_error" not in answer]


def _pages(root: Path, action: str) -> set[str]:
    return {record["page_id"] for record in _stored(root, action)}


def _failed(root: Path, action: str) -> int:
    shown = _ok(run_agac(root, "dispositions", "-w", WORKFLOW, "--sandbox", "--json", env=ENV))
    counts = next(e for e in json.loads(shown.stdout)["actions"] if e["name"] == action)["counts"]
    return counts.get("failed", 0) + counts.get("exhausted", 0)


ALL_PAGES = {row["page_id"] for row in ROWS}
KINDS = ["rate_limit", "timeout", "server_error", "refusal", "truncated", "empty", "invalid_json"]


@pytest.mark.parametrize("kind", KINDS)
def test_each_error_kind_fails_its_record_until_the_attempt_it_heals_at(tmp_path, kind):
    root = _project(
        tmp_path,
        f"actions:\n  extract:\n    errors: {{rate: 1.0, kinds: [{kind}], heal_on_attempt: 2}}\n",
    )

    result = _ok(_run(root))

    assert _pages(root, "extract") == ALL_PAGES
    assert _summary(result) == (
        "SANDBOX scenario sandbox.yml: 6 errors, 0 rules broken, 0 batch results dropped"
    )


@pytest.mark.parametrize("kind", KINDS)
def test_each_error_kind_that_never_heals_fails_every_record_through_retry_and_repair(
    tmp_path, kind
):
    root = _project(
        tmp_path, f"actions:\n  extract:\n    errors: {{rate: 1.0, kinds: [{kind}]}}\n"
    )

    result = _run(root)

    # Every record of extract failed, so the action failed.
    assert result.returncode == 1, _said(result)
    assert "Failed actions: extract" in _said(result)
    assert _failed(root, "extract") == 6
    assert _pages(root, "classify") == ALL_PAGES


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


PRINTED = """records:
  - match: {source.text: low tide}
    actions: {extract: {error: refusal}, classify: {pin: {label: matched}}}
"""


@pytest.mark.parametrize("run_mode", ["online", "batch"])
def test_a_record_is_matched_on_a_field_its_prompt_prints(tmp_path, run_mode):
    root = _project(tmp_path, PRINTED, run_mode=run_mode, repair="none")

    result = _run(root, "--wait", "--poll", "1")

    assert result.returncode == 3, _said(result)
    assert _pages(root, "extract") == ALL_PAGES - {"p3"}
    labels = {record["page_id"]: record["label"] for record in _stored(root, "classify")}
    assert {page for page, label in labels.items() if label == "matched"} == {"p3"}


def test_the_hint_names_the_scenario_given_and_a_retry_with_another_repairs(tmp_path):
    root = _project(tmp_path)
    (root / "faults.yml").write_text(MATCHED)

    result = _run(root, "--scenario", "faults.yml")

    assert result.returncode == 3, _said(result)
    assert f"agac retry -w {WORKFLOW} --sandbox --scenario faults.yml." in _said(result)
    assert _summary(result).startswith("SANDBOX scenario faults.yml: 3 errors")

    repaired = _ok(_run(root, "--scenario", "happy", command="retry"))

    assert _failed(root, "extract") == 0
    assert _pages(root, "extract") == ALL_PAGES
    assert _summary(repaired) == (
        "SANDBOX scenario happy: 0 errors, 0 rules broken, 0 batch results dropped"
    )


HEALS_ON_RETRY = """records:
  - match: {source.page_id: p3}
    actions: {extract: {errors: {rate: 1.0, kinds: [refusal], heal_on_attempt: 2}}}
"""


def test_a_retry_continues_the_count_so_a_fault_heals_in_the_retry_run(tmp_path):
    root = _project(tmp_path, HEALS_ON_RETRY, repair="none")

    failed = _run(root)
    retried = _run(root, command="retry")

    assert failed.returncode == 3, _said(failed)
    assert retried.returncode == 0, _said(retried)
    assert _pages(root, "extract") == ALL_PAGES
    assert _summary(retried).startswith("SANDBOX scenario sandbox.yml: 0 errors")


def test_a_rerun_of_an_action_starts_its_count_again_and_fresh_starts_every_count(tmp_path):
    root = _project(tmp_path, HEALS_ON_RETRY, repair="none")
    assert _run(root).returncode == 3
    _ok(_run(root, command="retry"))

    rerun = _run(root, "--rerun", "extract")
    assert rerun.returncode == 3, _said(rerun)
    assert _pages(root, "extract") == ALL_PAGES - {"p3"}

    fresh = _run(root, "--fresh")
    assert fresh.returncode == 3, _said(fresh)
    assert _pages(root, "extract") == ALL_PAGES - {"p3"}


FAILS_ONCE = "defaults:\n  errors: {rate: 1.0, kinds: [timeout], heal_on_attempt: 2}\n"


def test_an_input_staged_again_after_it_was_removed_starts_its_count_again(tmp_path):
    root = _project(tmp_path, FAILS_ONCE)
    # classify reads extract, so a record gone from staging is forgotten at both.
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    reads_source = "    prompt: $scripted.Classify\n    context_scope: { observe: ["
    assert reads_source in config.read_text()
    config.write_text(
        config.read_text().replace(
            reads_source, f"    dependencies: [extract]\n{reads_source}extract.code, "
        )
    )
    staged = _io(root) / "staging" / "pages.json"
    errors = "SANDBOX scenario sandbox.yml: %d errors, 0 rules broken, 0 batch results dropped"

    # Each record fails its first call at each of the two actions.
    assert _summary(_ok(_run(root))) == errors % 12
    staged.write_text(json.dumps(ROWS[:5]))
    assert _summary(_ok(_run(root))) == errors % 0
    assert _pages(root, "classify") == ALL_PAGES - {"p6"}

    # The same input has the same source_guid, and is a new record all the same.
    staged.write_text(json.dumps(ROWS))
    again = _ok(_run(root))

    assert _summary(again) == errors % 2
    assert _pages(root, "classify") == ALL_PAGES


def test_a_retry_of_a_transport_fault_does_not_wait_its_backoff(tmp_path):
    root = _project(tmp_path, FAILS_ONCE)
    config = root / "agent_workflow" / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
    short = "base_delay: 0.01, max_delay: 0.01"
    assert short in config.read_text()
    # A real run would wait up to 20 s before each of the twelve retries.
    config.write_text(config.read_text().replace(short, "base_delay: 20, max_delay: 60"))

    result = _ok(_run(root))

    assert _summary(result).startswith("SANDBOX scenario sandbox.yml: 12 errors")
    events = (_io(root) / "sandbox" / "logs" / "events.json").read_text().splitlines()
    retries = [json.loads(line)["message"] for line in events if "Retry attempt 1/3" in line]
    assert len(retries) == 12, retries
    assert all(message.endswith("s; skipped in sandbox)") for message in retries), retries


HEAL_IN_TURN = """records:
  - match: {source.page_id: p3}
    actions: {extract: {errors: {rate: 1.0, kinds: [refusal], heal_on_attempt: 2}}}
  - match: {source.page_id: p4}
    actions: {extract: {errors: {rate: 1.0, kinds: [refusal], heal_on_attempt: 3}}}
"""


def test_a_retry_of_several_passes_prints_one_line_that_counts_them_all(tmp_path):
    root = _project(tmp_path, HEAL_IN_TURN, repair="none")
    assert _run(root).returncode == 3

    # Pass 1 repairs p3 and fails p4 again; pass 2 repairs p4.
    retried = _ok(_run(root, "--all", command="retry"))

    assert "Pass 2: 0 open failure(s) left" in _said(retried)
    assert _summary(retried) == (
        "SANDBOX scenario sandbox.yml: 1 errors, 0 rules broken, 0 batch results dropped"
    )
    assert retried.stdout.rstrip().endswith(_summary(retried))
    assert _pages(root, "extract") == ALL_PAGES


BROKEN = "actions:\n  extract:\n    break_rules: {rules: [matches_regex], rate: 1.0%s}\n"


def test_a_broken_rule_is_repaired_on_the_attempt_it_heals_at(tmp_path):
    root = _project(tmp_path, BROKEN % ", heal_on_attempt: 2")

    result = _ok(_run(root))

    assert _summary(result) == (
        "SANDBOX scenario sandbox.yml: 0 errors, 6 rules broken, 0 batch results dropped"
    )
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
        "records:\n  - match: {source.page_id: p2}\n"
        "    actions: {classify: {pin: {label: urgent}}}\n",
    )

    _ok(_run(root))

    labels = {record["page_id"]: record["label"] for record in _stored(root, "classify")}
    assert labels == {page: "urgent" if page == "p2" else "routine" for page in ALL_PAGES}


HALF = "seed: 11\ndefaults:\n  errors: {rate: 0.5, kinds: [refusal]}\n"


def test_a_parallel_run_fails_the_records_a_serial_run_fails_in_any_order(tmp_path):
    serial = _project(tmp_path / "serial", HALF, repair="none")
    # The records arrive in the other order, so a decision tied to the order of the calls
    # would fall on other records.
    parallel = _project(tmp_path / "parallel", HALF, repair="none", rows=ROWS[::-1])

    first = _run(serial, "--execution-mode", "sequential")
    second = _run(parallel, "--execution-mode", "parallel", "--concurrency-limit", "4")

    assert first.returncode == second.returncode == 3, _said(first) + _said(second)
    assert "sequential" in _said(first) and "parallel" in _said(second)
    for action in ("extract", "classify"):
        assert _pages(serial, action) == _pages(parallel, action), action
    # With no repair, extract keeps only the records whose one attempt was not refused.
    assert set() < _pages(serial, "extract") < ALL_PAGES


SPLIT_CONFIG = """name: split_pages
description: "A tool splits each page in two; an LLM action labels each part"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  model_vendor: openai
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: { type: local, folder: ./staging, file_type: [json] }
actions:
  - name: split
    kind: tool
    intent: "Split each page in two"
    impl: split_page
    schema: part_output
    context_scope: { observe: [source.page_id, source.text] }
  - name: label
    intent: "Label each part"
    dependencies: [split]
    schema: label_output
    prompt: $split_pages.Label
    context_scope: { observe: [split.page_id, split.part, split.text] }
"""

SPLIT_TOOL = """from typing import Any

from agent_actions import udf_tool


def _find(data: Any, key: str) -> Any:
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for value in data.values():
            found = _find(value, key)
            if found is not None:
                return found
    return None


@udf_tool
def split_page(data: Any, *args) -> list[dict]:
    page, text = _find(data, "page_id"), str(_find(data, "text"))
    return [{"page_id": page, "part": part, "text": f"{text} {part}"} for part in ("a", "b")]
"""


def _split_project(base: Path) -> Path:
    root = base / "project"
    workflow_dir = root / "agent_workflow" / "split_pages"
    (workflow_dir / "agent_config").mkdir(parents=True)
    (workflow_dir / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema" / "split_pages").mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "tools" / "split_pages").mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\n"
        "schema_path: schema\ntool_path: [tools]\n"
    )
    (workflow_dir / "agent_config" / "split_pages.yml").write_text(SPLIT_CONFIG)
    (workflow_dir / "agent_io" / "staging" / "pages.json").write_text(json.dumps(ROWS))
    (root / "prompt_store" / "split_pages.md").write_text(
        "# split_pages\n\n{prompt Label}\nLabel this part.\n{{ split.text }}\n{end_prompt}\n"
    )
    (root / "tools" / "split_pages" / "split.py").write_text(SPLIT_TOOL)
    for name, fields in (
        ("part_output", ("page_id", "part", "text")),
        ("label_output", ("page_id", "part", "label")),
    ):
        body = "".join(
            f"  - id: {field}\n    type: string\n    required: true\n" for field in fields
        )
        (root / "schema" / "split_pages" / f"{name}.yml").write_text(
            f"name: {name}\nfields:\n{body}"
        )
    (root / "sandbox.yml").write_text(
        "seed: 5\nactions:\n  label:\n    errors: {rate: 0.5, kinds: [refusal]}\n"
    )
    return root


def test_two_fresh_runs_fail_the_same_records_below_an_expansion(tmp_path):
    root = _split_project(tmp_path)

    kept = []
    for _ in range(2):
        result = _run(root, "--fresh", workflow="split_pages")
        assert result.returncode == 3, _said(result)
        kept.append({(r["page_id"], r["part"]) for r in _stored(root, "label", "split_pages")})

    every_part = {(row["page_id"], part) for row in ROWS for part in ("a", "b")}
    assert kept[0] == kept[1]
    assert set() < kept[0] < every_part, kept[0]


def test_the_chaos_preset_completes_a_workflow_with_retry_and_repair(tmp_path):
    root = _project(tmp_path)

    result = _ok(_run(root, "--scenario", "chaos"))

    assert _summary(result).startswith("SANDBOX scenario chaos:")
    assert _pages(root, "extract") == ALL_PAGES
    assert _pages(root, "classify") == ALL_PAGES


@pytest.mark.parametrize(
    ("scenario", "named"),
    [
        ("actions:\n  extract:\n    errors: {kinds: [explode]}\n", "actions.extract.errors.kinds"),
        ("actions:\n  summarise: {latency_ms: 1}\n", "actions.summarise"),
        ("defaults:\n  latency_ms: [9, 1]\n", "defaults.latency_ms"),
        ("batch:\n  drops: 0.5\n", "batch.drops"),
        ("actions:\n  classify:\n    pin: {lable: x}\n", "actions.classify.pin.lable"),
    ],
)
def test_a_bad_scenario_stops_the_run_before_any_call(tmp_path, scenario, named):
    root = _project(tmp_path, scenario)

    result = _run(root)

    assert result.returncode != 0
    said = _said(result)
    assert named in said, said
    assert "Invalid configuration in sandbox.yml" in said, said
    assert "agent configuration file" not in said, said
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

    assert _summary(result) == (
        "SANDBOX scenario sandbox.yml: 0 errors, 0 rules broken, 12 batch results dropped"
    )
    assert _pages(root, "extract") == ALL_PAGES
    assert _pages(root, "classify") == ALL_PAGES


def test_a_batch_error_entry_is_retried_until_it_heals(tmp_path):
    root = _project(
        tmp_path,
        "actions:\n  extract:\n"
        "    errors: {rate: 1.0, kinds: [server_error], heal_on_attempt: 2}\n",
        run_mode="batch",
    )

    result = _ok(_run(root, "--wait", "--poll", "1"))

    assert _summary(result) == (
        "SANDBOX scenario sandbox.yml: 6 errors, 0 rules broken, 0 batch results dropped"
    )
    assert _pages(root, "extract") == ALL_PAGES


def test_a_batch_rule_broken_until_it_heals_is_repaired_by_the_repair_batch(tmp_path):
    root = _project(tmp_path, BROKEN % ", heal_on_attempt: 2", run_mode="batch")

    result = _ok(_run(root, "--wait", "--poll", "1"))

    assert _summary(result) == (
        "SANDBOX scenario sandbox.yml: 0 errors, 6 rules broken, 0 batch results dropped"
    )
    codes = [record["code"] for record in _stored(root, "extract")]
    assert len(codes) == 6 and all(len(code) == 6 and code[3] == "-" for code in codes), codes


def test_a_batch_the_scenario_fails_fails_its_action(tmp_path):
    root = _project(tmp_path, "batch: {fail: [classify]}\n", run_mode="batch")

    result = _run(root, "--wait", "--poll", "1")

    assert result.returncode == 1, _said(result)
    said = _said(result)
    assert "the provider reports it failed, not completed" in said, said
    assert "✗ classify" in said, said
    assert _pages(root, "extract") == ALL_PAGES


def test_polls_until_complete_alone_holds_the_batch_for_that_many_checks(tmp_path):
    root = _project(tmp_path, "batch: {polls_until_complete: 2}\n", run_mode="batch")

    submitted = _run(root)
    first_check = _run(root)
    second_check = _run(root)
    collected = _run(root)

    held = (submitted, first_check, second_check)
    assert [result.returncode for result in held] == [4, 4, 4], _said(second_check)
    assert _ok(collected)
    assert _pages(root, "extract") == ALL_PAGES
