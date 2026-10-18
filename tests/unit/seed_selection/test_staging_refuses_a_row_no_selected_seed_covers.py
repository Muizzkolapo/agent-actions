"""Staging refuses a file whose rows lack a usable value for a selected seed, before any call."""

import pytest

from agent_actions.errors import ConfigValidationError
from agent_actions.input.preprocessing.staging import field_validation

SYLLABUS = {
    "select_by": "source.exam",
    "files": {"dbt": "$file:dbt.json", "snowflake": "$file:snowflake.json"},
}
GLOSSARY = {"select_by": "source.language", "files": {"en": "$file:en.json"}}
FILE = "/project/agent_io/staging/pages.json"


def _actions(**seeds_by_action):
    return {
        name: {"context_scope": {"seed": seed, "observe": ["source.title"]}}
        for name, seed in seeds_by_action.items()
    }


def _check(rows, actions):
    field_validation.validate_seed_selectors(rows, FILE, actions)


class TestEveryRowIsChecked:
    def test_a_bad_row_in_the_middle_names_the_row(self):
        rows = [{"exam": "dbt"}, {"exam": "snowflak"}, {"exam": "snowflake"}]

        with pytest.raises(ConfigValidationError) as excinfo:
            _check(rows, _actions(generate={"exam_syllabus": SYLLABUS}))

        assert str(excinfo.value) == (
            "Seed 'exam_syllabus' in action 'generate': record value 'snowflak' for "
            "'source.exam' is not in the file map. Known values: dbt, snowflake. "
            "(staging/pages.json, record 1)"
        )

    def test_every_row_covered_passes(self):
        rows = [{"exam": "dbt"}, {"exam": "snowflake"}]

        _check(rows, _actions(generate={"exam_syllabus": SYLLABUS}))

    def test_no_selected_seed_means_no_check(self):
        rows = [{"exam": "snowflak"}]

        _check(rows, _actions(generate={"rules": "$file:rules.json"}))

    def test_a_guard_does_not_exempt_a_row(self):
        actions = _actions(generate={"exam_syllabus": SYLLABUS})
        actions["generate"]["guard"] = {"condition": "source.keep == true", "on_false": "filter"}
        rows = [{"exam": "dbt", "keep": True}, {"exam": "snowflak", "keep": False}]

        with pytest.raises(ConfigValidationError, match=r"record 1\)$"):
            _check(rows, actions)


class TestEveryActionIsChecked:
    def test_a_later_action_with_its_own_selector_is_checked(self):
        actions = _actions(
            summarize={"exam_syllabus": SYLLABUS},
            translate={"exam_syllabus": SYLLABUS, "glossary": GLOSSARY},
        )
        rows = [{"exam": "dbt", "language": "en"}, {"exam": "dbt", "language": "de"}]

        with pytest.raises(ConfigValidationError) as excinfo:
            _check(rows, actions)

        assert str(excinfo.value) == (
            "Seed 'glossary' in action 'translate': record value 'de' for "
            "'source.language' is not in the file map. Known values: en. "
            "(staging/pages.json, record 1)"
        )


class TestEveryInputShapeIsChecked:
    def test_a_single_record_file_is_record_zero(self):
        with pytest.raises(ConfigValidationError, match=r"record 0\)$"):
            _check({"title": "a"}, _actions(generate={"exam_syllabus": SYLLABUS}))

    def test_a_text_file_has_no_field_to_select_by(self):
        with pytest.raises(ConfigValidationError) as excinfo:
            _check("# a page of prose", _actions(generate={"exam_syllabus": SYLLABUS}))

        assert str(excinfo.value) == (
            "Seed 'exam_syllabus' in action 'generate': record has no value for "
            "'source.exam'. Known values: dbt, snowflake. (staging/pages.json, record 0)"
        )
