"""One record gets one dispatched schema, however many times the model is called for it.

A repair loop calls the model again for the same record. The schema was resolved on each
call, so the dispatch function ran again and could pick another shape in the middle of a
repair. It now runs once per record, and the result names the schema it chose.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent_actions.processing.invocation.online import OnlineStrategy
from agent_actions.processing.prepared_task import PreparedTask

TOOL = """\
from pathlib import Path


def pick_schema(context_json):
    calls = Path(__file__).with_name("calls")
    calls.write_text(str(int(calls.read_text() or 0) + 1) if calls.exists() else "1")
    return "topic_answer"
"""


class _TwoCallRepairLoop:
    """Stands in for the expectation service: generates, then regenerates once."""

    def execute(self, generate, prompt, **_):
        generate(prompt)
        response, executed = generate(prompt + " (repair)")
        return SimpleNamespace(
            response=response,
            executed=executed,
            suite_results=None,
            exhausted=False,
            iterations=2,
            suite_result=None,
        )


def _project(root: Path) -> Path:
    (root / "agent_actions.yml").write_text("schema_path: schema\n")
    (root / "schema").mkdir()
    (root / "schema" / "topic_answer.yml").write_text(
        "name: topic_answer\nfields:\n  - id: topic\n    type: string\n"
    )
    (root / "tools").mkdir()
    (root / "tools" / "pick_schema.py").write_text(TOOL)
    return root / "tools"


def test_a_repair_loop_calls_the_dispatch_function_once_and_names_the_schema(tmp_path):
    tools = _project(tmp_path)
    context = MagicMock()
    context.agent_name = "label_page"
    context.agent_config = {
        "schema": "dispatch_task('pick_schema')",
        "schema_options": ["topic_answer"],
        "model_vendor": "openai",
        "tool_path": [str(tools)],
        "_project_root": str(tmp_path),
    }
    task = PreparedTask(
        target_id="t1", source_guid="sg1", formatted_prompt="Label it.", llm_context={"source": {}}
    )
    sent: list[dict] = []

    def fake_call(config, *args, **kwargs):
        sent.append(config)
        return [{"topic": "x"}]

    with patch("agent_actions.llm.realtime.builder.create_dynamic_agent", side_effect=fake_call):
        result = OnlineStrategy(expectation_service=_TwoCallRepairLoop()).invoke(task, context)

    assert (tools / "calls").read_text() == "1"
    assert len(sent) == 2
    assert all([f["id"] for f in config["schema"]["fields"]] == ["topic"] for config in sent)
    assert result.output_schema == "topic_answer"
