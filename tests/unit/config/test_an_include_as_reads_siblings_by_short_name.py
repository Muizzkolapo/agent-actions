"""A prompt and a schema-file judge context of an `as:` include read a sibling by its short
name: one prompt text and one schema file serve every instance."""

from __future__ import annotations

import pytest
import yaml

from agent_actions.prompt.render_workflow import render_pipeline_with_templates
from agent_actions.prompt.service import PromptPreparationService
from tests.unit.config.test_a_workflow_includes_a_branch_file import (
    WF,
    A,
    Z,
    _names,
    _project,
    _refusal,
    _render,
    _with,
)
from tests.unit.config.test_an_include_as_gives_each_instance_its_own_names import (
    REVIEW,
    WRITE,
    _by_name,
    _round,
    _use,
)

JUDGE_TEXT = "Judge {{ write.text }} against {{ spec.text }}."
JUDGE = {
    "name": "judge",
    "intent": "judge",
    "prompt": "$round.Judge",
    "schema": {"verdict": "string"},
    "dependencies": ["write"],
    "context_scope": {"observe": ["write.text", "spec.text"]},
}


def _render_with_prompts(tmp_path, actions, branches, prompts: str) -> dict:
    _project(tmp_path, [A])
    (tmp_path / "prompt_store" / "round.md").write_text(prompts)
    return _render(tmp_path, actions, branches)


def _judge(text: str) -> str:
    return f"{{prompt Judge}}\n{text}\n{{end_prompt}}\n"


class TestOnePromptServesEveryInstance:
    def test_one_branch_used_with_two_prefixes_renders_two_sets_with_one_prompt(self, tmp_path):
        rendered = _render_with_prompts(
            tmp_path,
            [A, _use("c"), _use("c2")],
            {"round": _round([WRITE, REVIEW, JUDGE], outputs=["judge"])},
            _judge(JUDGE_TEXT),
        )
        actions = _by_name(rendered)

        assert _names(rendered) == [
            "a",
            "c__write",
            "c__review",
            "c__judge",
            "c2__write",
            "c2__review",
            "c2__judge",
        ]
        assert actions["c__write"]["impl"] == actions["c2__write"]["impl"] == "round_write"
        for prefix in ("c", "c2"):
            header = f"{{% set write = {prefix}__write %}}{{% set spec = a %}}"
            assert actions[f"{prefix}__judge"]["prompt"] == header + JUDGE_TEXT

    def test_each_instance_renders_the_prompt_with_its_own_sibling(self, tmp_path):
        text = (
            "{% macro quoted() %}'{{ write.text }}'{% endmacro %}"
            "Judge {{ quoted() }} against {{ spec.text }}."
        )
        actions = _by_name(
            _render_with_prompts(
                tmp_path,
                [A, _use("c"), _use("c2")],
                {"round": _round([WRITE, REVIEW, JUDGE], outputs=["judge"])},
                _judge(text),
            )
        )
        record = {"c__write": {"text": "one"}, "c2__write": {"text": "two"}, "a": {"text": "s"}}

        rendered = {
            prefix: PromptPreparationService._render_prompt_template(
                actions[f"{prefix}__judge"]["prompt"], record
            )
            for prefix in ("c", "c2")
        }

        assert rendered == {"c": "Judge 'one' against s.", "c2": "Judge 'two' against s."}

    def test_a_prompt_that_starts_with_a_new_line_keeps_it(self, tmp_path):
        actions = _by_name(
            _render_with_prompts(
                tmp_path,
                [A, _use("c2")],
                {"round": _round([WRITE, JUDGE], outputs=["judge"])},
                "{prompt Judge}\n\n  Judge {{ write.text }}.\n{end_prompt}\n",
            )
        )
        prompt = actions["c2__judge"]["prompt"]

        assert PromptPreparationService._render_prompt_template(
            prompt, {"c2__write": {"text": "two"}}
        ) == PromptPreparationService._render_prompt_template(
            prompt.split("%}", 1)[1].replace('{{ "" }}', "", 1), {"write": {"text": "two"}}
        )

    @pytest.mark.parametrize(
        "text",
        ["Judge {{ source.text }}.", "Judge {{ a.text }} for {{ source.text }}."],
        ids=["source-only", "input-bound-to-its-own-name"],
    )
    def test_a_prompt_that_reads_no_renamed_name_is_left_as_written(self, tmp_path, text):
        judge = _with(JUDGE, context_scope={"observe": ["source.text"]}, dependencies=["write"])
        branch = _round([WRITE, judge], inputs={"a": "The text"}, outputs=["judge"])
        branch["actions"][0] = _with(
            WRITE, dependencies=["a"], context_scope={"observe": ["a.text"]}
        )
        actions = _by_name(
            _render_with_prompts(tmp_path, [A, _use("c2", a="a")], {"round": branch}, _judge(text))
        )

        assert actions["c2__judge"]["prompt"] == text

    def test_a_prompt_of_an_include_without_as_is_left_as_written(self, tmp_path):
        branch = _round([WRITE, JUDGE], outputs=["judge"], inputs={"spec": "The spec"})
        spec = _with(Z, name="spec", dependencies=["a"])
        rendered = _render_with_prompts(
            tmp_path,
            [A, spec, {"include": "round", "inputs": {"spec": "spec"}}],
            {"round": branch},
            _judge(JUDGE_TEXT),
        )

        assert _by_name(rendered)["judge"]["prompt"] == JUDGE_TEXT


class TestAPromptReadIsChecked:
    def test_a_prompt_reading_a_short_name_the_group_does_not_define_is_refused(self, tmp_path):
        _project(tmp_path / "bad", [A])
        (tmp_path / "bad" / "prompt_store" / "round.md").write_text(
            _judge("Judge {{ write.text }} with {{ draft.text }}.")
        )
        branch = {"round": _round([WRITE, JUDGE], outputs=["judge"])}

        message = _refusal(tmp_path / "bad", [A, _use("c2")], branch)

        assert message == (
            f"Branch 'round' (branches/round.yml), included in {WF} as 'c2', action 'judge': "
            "reads 'draft', which the branch does not define and no input of include 'c2' "
            "binds. Branch actions: write, judge. Inputs: spec."
        )

    @pytest.mark.parametrize(
        "text",
        [
            "Judge {{write.text}} against {{spec.text}}.",
            "Write {item.name} literally, then judge {{ write.text }}.",
        ],
        ids=["no-spaces-inside-braces", "single-brace-text"],
    )
    def test_a_prompt_read_is_found_by_its_short_name_only_inside_jinja(self, tmp_path, text):
        rendered = _render_with_prompts(
            tmp_path,
            [A, _use("c2")],
            {"round": _round([WRITE, JUDGE], outputs=["judge"])},
            _judge(text),
        )

        assert _by_name(rendered)["c2__judge"]["prompt"].endswith(text)


SCHEMA = """\
name: verdict
fields:
  - id: verdict
    type: string
    expectations:
      - type: llm_judge
        params: {rubric: "Fits the question", context: [write.text]}
expectations:
  - type: llm_judge
    params: {rubric: "Fits the spec", context: [spec.text, write.text]}
"""


def test_an_llm_judge_context_in_a_branch_schema_file_resolves_per_instance(tmp_path):
    judge = _with(JUDGE, schema="verdict", expect={})
    workflow = _project(
        tmp_path, [A, _use("c"), _use("c2")], {"round": _round([WRITE, judge], outputs=["judge"])}
    )
    (tmp_path / "prompt_store" / "round.md").write_text(_judge(JUDGE_TEXT))
    (tmp_path / "schema" / "verdict.yml").write_text(SCHEMA)

    rendered = yaml.safe_load(
        render_pipeline_with_templates(workflow, tmp_path / "templates", project_root=tmp_path)
    )
    actions = _by_name(rendered)

    for prefix in ("c", "c2"):
        schema = actions[f"{prefix}__judge"]["schema"]
        field_rule, own_rule = schema["fields"][0]["expectations"][0], schema["expectations"][0]
        assert field_rule["params"]["context"] == [f"{prefix}__write.text"]
        assert own_rule["params"]["context"] == ["a.text", f"{prefix}__write.text"]
