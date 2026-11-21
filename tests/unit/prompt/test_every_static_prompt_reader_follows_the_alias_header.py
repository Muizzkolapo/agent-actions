"""The alias header `{% set write = c2__write %}` is read as a read of `c2__write` by every
static reader of prompt references, and is built only for the names a prompt reads."""

from __future__ import annotations

import pytest
from jinja2 import Environment

from agent_actions.prompt.aliases import prompt_aliases, with_alias_header
from agent_actions.prompt.cache_scope import record_reads_in_prompt
from agent_actions.prompt.context.scope_parsing import extract_action_names_from_template
from agent_actions.prompt.service import PromptPreparationService
from agent_actions.validation.prompt_required_field_validator import _unguarded_refs
from agent_actions.validation.static_analyzer.reference_extractor import ReferenceExtractor

NAMES = {"write": "c2__write", "spec": "a", "same": "same"}
HEADER = "{% set write = c2__write %}"


INSTANCE = {"_include": {"instance": "c2", "names": NAMES}}


def _reads(prompt: str, action: dict | None = None) -> list[tuple[str, str]]:
    config = {"name": "x", "prompt": prompt, **(INSTANCE if action is None else action)}
    return [(r.source_agent, r.field_path) for r in ReferenceExtractor().extract_from_agent(config)]


class TestTheHeader:
    def test_it_sets_each_renamed_name_the_prompt_reads_and_no_other(self):
        prompt = "{{ write.text }} {{ same.text }} {% for spec in [1] %}{{ spec }}{% endfor %}"

        assert with_alias_header(prompt, NAMES) == HEADER + prompt

    def test_a_prompt_that_reads_no_renamed_name_or_does_not_parse_is_unchanged(self):
        assert with_alias_header("{{ source.text }}", NAMES) == "{{ source.text }}"
        assert with_alias_header("{{ write.text ", NAMES) == "{{ write.text "

    @pytest.mark.parametrize("prompt", ["{{ write.text }}\nnext", "\n\n  {{ write.text }}\n"])
    def test_the_prompt_renders_as_its_text_does_with_the_short_name_bound(self, prompt):
        render = PromptPreparationService._render_prompt_template

        assert render(with_alias_header(prompt, NAMES), {"c2__write": {"text": "two"}}) == render(
            prompt, {"write": {"text": "two"}}
        )

    def test_a_name_set_twice_at_the_top_level_is_no_alias(self):
        ast = Environment().parse(HEADER + "{% set spec = a %}{% set spec = b %}{{ x }}")

        assert prompt_aliases(ast, {**NAMES, "spec": "a"}) == {"write": "c2__write"}

    def test_a_set_tag_the_map_does_not_name_is_no_alias(self):
        ast = Environment().parse(HEADER + "{% set s = spec_a %}{{ s.x }}")

        assert prompt_aliases(ast, NAMES) == {"write": "c2__write"}
        assert prompt_aliases(ast, {}) == {}


class TestTheReferenceExtractor:
    def test_a_short_name_reads_the_action_it_is_bound_to(self):
        assert _reads(HEADER + "{{ write.text }} {{ write.items() }}") == [
            ("c2__write", "text"),
            ("c2__write", "*"),
        ]

    def test_a_loop_variable_of_the_same_name_is_not_the_alias(self):
        assert _reads(HEADER + "{% for write in rows %}{{ write.text }}{% endfor %}") == []

    def test_a_short_name_written_without_spaces_inside_braces_reads_only_the_action(self):
        assert _reads(HEADER + "{{write.text}}") == [("c2__write", "text")]

    def test_single_brace_text_is_still_reported_as_before(self):
        assert _reads("Use {item.name} as written.") == [("item", "name")]


def test_the_template_scope_extractor_reads_the_action_a_short_name_is_bound_to():
    template = HEADER + "{{ write.text }} {% for write in rows %}{{ write.x }}{% endfor %}"

    assert extract_action_names_from_template(template, NAMES) == {"c2__write"}


def test_the_prompt_contract_check_reads_the_action_a_short_name_is_bound_to():
    template = HEADER + "{{ write.text }}{% if write.note %}{{ write.note }}{% endif %}"

    assert _unguarded_refs(template, NAMES) == {("c2__write", "text"), ("c2__write", "note")}


def test_the_prompt_cache_check_counts_a_short_name_as_a_per_record_read():
    reads = record_reads_in_prompt({"name": "x", "prompt": HEADER + "{{ write.text }}"})

    assert reads == ("c2__write",)


class TestAPromptOutsideAnInclude:
    """Its own `{% set s = spec_a %}` is a local variable, read as it was before the header."""

    PROMPT = "{% set s = spec_a %}{{ s.missing_field }}"

    def test_the_reference_extractor_does_not_read_the_set_value(self):
        assert _reads(self.PROMPT, {}) == []

    def test_the_template_scope_extractor_does_not_read_it(self):
        assert extract_action_names_from_template(self.PROMPT) == set()

    def test_the_prompt_contract_check_does_not_read_it(self):
        assert _unguarded_refs(self.PROMPT, {}) == {("s", "missing_field")}


class TestTheCallersPassTheMapOfTheAction:
    PROMPT = HEADER + "{{ write.word }}"
    REVIEW = {"name": "c2__review", "prompt": PROMPT, **INSTANCE}

    def test_dependency_inference_reads_the_action_a_short_name_is_bound_to(self):
        from agent_actions.prompt.context.scope_inference import infer_dependencies

        actions = ["c2__write", "c2__review", "write"]

        assert infer_dependencies(self.REVIEW, actions, "c2__review", validate=False) == (
            [],
            ["c2__write"],
        )

    def test_the_prompt_contract_check_of_pre_flight_names_the_bound_action(self, monkeypatch):
        from agent_actions.services.preflight_service import PreflightService

        found: list[tuple[str, list[str]]] = []
        monkeypatch.setattr(
            PreflightService,
            "_warn_findings",
            staticmethod(lambda label, f, **_: found.append((label, f))),
        )
        monkeypatch.setattr(
            PreflightService,
            "_collect_producing_schemas",
            lambda self: {"c2__write": {"fields": [{"id": "word", "required": False}]}},
        )
        configs = {
            "c2__write": {"name": "c2__write", "prompt": "Write."},
            "c2__review": self.REVIEW,
        }

        PreflightService("wf", configs, None, "wf.yml")._warn_unguarded_prompt_refs()

        ((label, findings),) = found
        assert label == "prompt-contract"
        assert len(findings) == 1
        assert "c2__write.word" in findings[0]
