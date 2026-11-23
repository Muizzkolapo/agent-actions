"""A judged rule in a named suite is sent the field its ``context:`` names.

`summarize` binds ``expect: {suite: quality}``, and the suite's ``llm_judge`` rule
reads ``src.text``. The action itself does not observe ``src.text``, so the load has
to add it, as it does for a rule declared on the action. Both actions batch, and each
judge request is read from the provider's own record of the batch.
"""

import json
from pathlib import Path

import pytest
import yaml

from agent_actions.cli.exit_codes import EXIT_PAUSED
from tests._support.agac_cli import run_agac
from tests.helpers.store import stored_rows

WORKFLOW = "wf"

PROMPTS = """{prompt Summarize}
Summarise the page in one sentence.
## PAGE
{{ source.page_content }}
{end_prompt}
"""

SUITE = {
    "expectations": [
        {
            "id": "grounded",
            "type": "llm_judge",
            "field": "summary",
            "params": {
                "rule": "The summary is supported by the source text.",
                "context": ["src.text"],
            },
        }
    ]
}


def _project(root: Path) -> Path:
    workflow_dir = root / "agent_workflow" / WORKFLOW
    (workflow_dir / "agent_config").mkdir(parents=True)
    (workflow_dir / "agent_io" / "staging").mkdir(parents=True)
    for folder in ("prompt_store", "schema", "templates", "tools", "seed_data"):
        (root / folder).mkdir()
    (root / "agent_actions.yml").write_text(
        "default_agent_config:\n"
        "  api_key: OLLAMA_API_KEY\n"
        "  model_name: test-model\n"
        'tool_path: ["tools"]\n'
        "schema_path: schema\n"
        "seed_data_path: seed_data\n"
    )
    (root / ".env").write_text("OLLAMA_API_KEY=not-used\n")
    (root / "prompt_store" / "p.md").write_text(PROMPTS)
    (root / "schema" / "src.yml").write_text(
        yaml.safe_dump({"name": "src", "fields": [{"id": "text", "type": "string"}]})
    )
    (root / "schema" / "summary.yml").write_text(
        yaml.safe_dump({"name": "summary", "fields": [{"id": "summary", "type": "string"}]})
    )
    (root / "schema" / "quality.yml").write_text(yaml.safe_dump(SUITE))
    (workflow_dir / "agent_io" / "staging" / "pages.json").write_text(
        json.dumps([{"page_id": "p1", "page_content": "dbt models are SELECT statements."}])
    )
    (workflow_dir / "agent_config" / f"{WORKFLOW}.yml").write_text(
        f"name: {WORKFLOW}\n"
        'description: "A judged rule in a named suite reads another action"\n'
        "defaults:\n"
        "  json_mode: true\n"
        "  granularity: Record\n"
        "  run_mode: batch\n"
        "  model_vendor: agac-provider\n"
        "  model_name: test-model\n"
        "  api_key: OLLAMA_API_KEY\n"
        "  data_source: { type: local, folder: ./staging, file_type: [json] }\n"
        "actions:\n"
        "  - name: src\n"
        '    intent: "Extract the text"\n'
        "    schema: src\n"
        "    prompt: $p.Summarize\n"
        "    context_scope: { observe: [source.page_content] }\n"
        "  - name: summarize\n"
        "    dependencies: [src]\n"
        '    intent: "Summarise"\n'
        "    schema: summary\n"
        "    prompt: $p.Summarize\n"
        "    context_scope: { observe: [source.page_content] }\n"
        "    expect: { suite: quality, repair: none }\n"
    )
    return root


def _run(project: Path, *, again: bool):
    return run_agac(
        project,
        "run",
        "-a",
        WORKFLOW,
        "-u",
        "tools",
        *([] if again else ["--fresh"]),
        env={"AGAC_BATCH_COMPLETE_AFTER_SECONDS": "0"},
    )


def _verdict(dbs: list[Path]) -> dict:
    for db in dbs:
        for (blob,) in stored_rows(
            db, "select data from target_data where action_name = 'summarize'"
        ):
            for record in json.loads(blob):
                return record["content"]["summarize"]["expect"]
    raise AssertionError("summarize stored no record")


def test_the_judge_of_a_named_suite_is_sent_the_field_its_rule_references(tmp_path):
    project = _project(tmp_path / "project")
    state_dir = project / ".agac" / "batch_state"
    store = project / "agent_workflow" / WORKFLOW / "agent_io" / "store"
    judge_requests: dict[str, str] = {}

    result = _run(project, again=False)
    for _ in range(8):
        output = result.stdout + result.stderr
        for state in state_dir.glob("*.json"):
            for task in json.loads(state.read_text())["tasks"]:
                if task["custom_id"].startswith("j_"):
                    judge_requests[task["custom_id"]] = task["prompt"]
        if result.returncode != EXIT_PAUSED:
            assert result.returncode == 0, output
            break
        assert "run again" in output, output
        result = _run(project, again=True)
    else:
        pytest.fail("the workflow never stopped asking to be run again")

    dbs = sorted(store.glob("*.db"))
    texts = {
        record["content"]["src"]["text"]
        for db in dbs
        for (blob,) in stored_rows(db, "select data from target_data where action_name = 'src'")
        for record in json.loads(blob)
    }

    assert judge_requests, "no judge request went out: the rule failed on its context"
    grounding = {
        prompt.split("## Grounding context\n", 1)[-1].split("\n\n## Value under test", 1)[0]
        for prompt in judge_requests.values()
    }
    assert grounding == {f"- src.text: {text}" for text in texts}

    (outcome,) = _verdict(dbs)["outcomes"]
    assert (outcome["id"], outcome["type"]) == ("grounded", "llm_judge")
    assert "context" not in outcome["detail"], "the rule failed on its context, not on a verdict"
