"""The load refuses cache points a request cannot carry, and warns of ones that cannot be read."""

from __future__ import annotations

from typing import Any

from agent_actions.validation.static_analyzer.workflow_static_analyzer import analyze_workflow

ONE_POINT = "## PAGE\n{{ source.page_content }}\n{% cache_point %}\n## SLOT\n{{ slots.fact }}\n"


def _analyze(prompt: str, **extra: Any) -> Any:
    slots = {
        "name": "slots",
        "model_vendor": "anthropic",
        "prompt": "List the slots of {{ source.page_content }}.",
        "context_scope": {"observe": ["source.page_content"]},
        "schema": {"fact": "string"},
    }
    action = {
        "name": "write",
        "dependencies": ["slots"],
        "model_vendor": "anthropic",
        "enable_prompt_caching": True,
        "prompt": prompt,
        "context_scope": {"observe": ["source.page_content", "slots.fact"]},
        "schema": {"answer": "string"},
        **extra,
    }
    return analyze_workflow({"name": "pages", "actions": [slots, action]})


def _errors(prompt: str, **extra: Any) -> list[str]:
    return [e.message for e in _analyze(prompt, **extra).errors if "cache point" in e.message]


def _warnings(prompt: str, **extra: Any) -> list[str]:
    return [w.message for w in _analyze(prompt, **extra).warnings if "cache point" in w.message]


class TestTooManyPoints:
    def test_three_points_load(self):
        prompt = "a{% cache_point %}b{% cache_point %}c{% cache_point %}{{ slots.fact }}"

        assert _errors(prompt) == []

    def test_four_points_are_an_error_that_names_the_limit(self):
        prompt = (
            "a{% cache_point %}b{% cache_point %}c{% cache_point %}d{% cache_point %}"
            "{{ slots.fact }}"
        )

        (message,) = _errors(prompt)
        assert message.startswith("Action 'write': its prompt holds 4 cache points")
        assert "at most 3" in message
        assert "4 cache breakpoints" in message

    def test_a_point_in_a_loop_is_an_error(self):
        prompt = "{% for n in [1, 2] %}{{ n }}{% cache_point %}{% endfor %}{{ slots.fact }}"

        (message,) = _errors(prompt)
        assert "inside a loop, a macro" in message

    def test_a_point_in_a_macro_is_an_error(self):
        prompt = "{% macro part() %}x{% cache_point %}{% endmacro %}{{ part() }}{{ slots.fact }}"

        (message,) = _errors(prompt)
        assert "inside a loop, a macro" in message

    def test_a_point_in_a_captured_block_is_an_error(self):
        captured = "{% set part %}x{% cache_point %}{% endset %}{{ part }}{{ slots.fact }}"
        filtered = "{% filter upper %}x{% cache_point %}{% endfilter %}{{ slots.fact }}"

        for prompt in (captured, filtered):
            (message,) = _errors(prompt)
            assert "captures its text" in message

    def test_a_point_in_a_branch_loads(self):
        prompt = "{% if slots.fact %}a{% cache_point %}{% endif %}{{ slots.fact }}"

        assert _errors(prompt) == []

    def test_points_that_are_not_sent_are_no_error(self):
        prompt = "a{% cache_point %}" * 5 + "{{ slots.fact }}"

        assert _errors(prompt, enable_prompt_caching=False) == []
        assert _errors(prompt, model_vendor="openai") == []


class TestPointsThatAreNotSent:
    def test_caching_off_warns_that_the_points_are_ignored(self):
        (message,) = _warnings(ONE_POINT, enable_prompt_caching=False)

        assert message.startswith("Action 'write': its prompt holds a cache point")
        assert "enable_prompt_caching is not on" in message

    def test_caching_unset_warns_too(self):
        action_without_the_flag = {"enable_prompt_caching": None}

        (message,) = _warnings(ONE_POINT, **action_without_the_flag)
        assert "enable_prompt_caching is not on" in message

    def test_a_vendor_agac_marks_nothing_for_warns_that_the_points_are_ignored(self):
        (message,) = _warnings(ONE_POINT, model_vendor="openai")

        assert "'openai'" in message
        assert "sent without" in message


class TestWhatIsReadBeforeAPoint:
    def test_a_point_after_the_source_page_alone_raises_no_warning(self):
        assert _warnings(ONE_POINT) == []

    def test_a_point_after_static_text_alone_raises_no_warning(self):
        assert _warnings("The rules.\n{% cache_point %}\n{{ slots.fact }}") == []

    def test_a_field_of_another_action_before_the_point_is_named(self):
        prompt = "{{ source.page_content }} {{ slots.fact }}{% cache_point %} Write it."

        (message,) = _warnings(prompt)
        assert message.startswith("Action 'write': the text before its cache point reads")
        assert "slots.fact" in message
        assert "source.page_content" not in message

    def test_only_what_is_read_before_the_last_point_is_named(self):
        prompt = "{{ slots.fact }}{% cache_point %}{{ slots.other }}"

        (message,) = _warnings(prompt)
        assert "slots.fact" in message
        assert "slots.other" not in message

    def test_a_value_that_changes_on_every_render_before_the_point_is_named(self):
        prompt = "{{ ['a', 'b'] | random }}{% cache_point %}{{ slots.fact }}"

        (message,) = _warnings(prompt)
        assert "| random" in message
        assert "never read" in message

    def test_the_warning_says_how_short_a_prefix_is_not_cached(self):
        prompt = "{{ slots.fact }}{% cache_point %}"

        (warning,) = [w for w in _analyze(prompt).warnings if "cache point" in w.message]
        assert "512" in warning.hint
        assert "4,096" in warning.hint

    def test_a_schema_the_record_chooses_warns_that_the_points_are_not_marked(self):
        (message,) = _warnings(ONE_POINT, schema="dispatch_task('pick_schema')")

        assert "dispatch_task('pick_schema')" in message
        assert "not marked" in message


class TestTheOlderWarning:
    def test_a_prompt_with_a_point_is_not_told_it_is_sent_unmarked(self):
        result = _analyze(ONE_POINT)

        assert [w.message for w in result.warnings if "without a cache mark" in w.message] == []

    def test_a_prompt_without_a_point_is_warned_as_before(self):
        result = _analyze("{{ source.page_content }} {{ slots.fact }}")

        (message,) = [w.message for w in result.warnings if "without a cache mark" in w.message]
        assert "slots.fact, source.page_content" in message
