"""A seed key may map a record field to one of several files; each record gets its own."""

import json

import pytest

from agent_actions.config.types import RunMode
from agent_actions.prompt.context.static_loader import StaticDataLoader, StaticDataLoadError
from agent_actions.prompt.service import PromptPreparationService

SYLLABUS = {
    "exam_syllabus": {
        "select_by": "source.exam",
        "files": {"dbt": "$file:dbt.json", "snowflake": "$file:snowflake.json"},
    }
}


def _workflow(tmp_path, files):
    workflow = tmp_path / "workflow"
    (workflow / "agent_config").mkdir(parents=True)
    (workflow / "seed_data").mkdir()
    for name, content in files.items():
        (workflow / "seed_data" / name).write_text(json.dumps(content))
    return str(workflow / "agent_config" / "wf.yml")


def _config(tmp_path, seed, prompt, files=None, **scope):
    files = files or {
        "dbt.json": {"label": "DBT-LABEL"},
        "snowflake.json": {"label": "SNOW-LABEL"},
        "rules.json": {"label": "RULES-LABEL"},
    }
    return {
        "workflow_config_path": _workflow(tmp_path, files),
        "prompt": prompt,
        "context_scope": {"seed": seed, "observe": ["source.title"], **scope},
    }


def _render(agent_config, record, action="generate_question"):
    return PromptPreparationService.prepare_prompt_with_field_context(
        agent_config, action, record, field_context={"source": record}
    ).formatted_prompt


class TestEachRecordGetsItsOwnFile:
    def test_two_records_get_their_own_file(self, tmp_path):
        config = _config(tmp_path, SYLLABUS, "{{ seed.exam_syllabus.label }}")

        assert _render(config, {"exam": "dbt", "title": "a"}) == "DBT-LABEL"
        assert _render(config, {"exam": "snowflake", "title": "b"}) == "SNOW-LABEL"

    def test_two_selected_keys_follow_their_own_selectors(self, tmp_path):
        seed = {
            "house_rules": "$file:house.json",
            "style_guide": {
                "select_by": "source.customer",
                "files": {"acme": "$file:acme.json", "globex": "$file:globex.json"},
            },
            "glossary": {
                "select_by": "source.language",
                "files": {"en": "$file:en.json", "fr": "$file:fr.json"},
            },
        }
        files = {
            "house.json": {"label": "HOUSE"},
            "acme.json": {"label": "ACME"},
            "globex.json": {"label": "GLOBEX"},
            "en.json": {"label": "EN"},
            "fr.json": {"label": "FR"},
        }
        prompt = (
            "{{ seed.style_guide.label }}/{{ seed.glossary.label }}/{{ seed.house_rules.label }}"
        )
        config = _config(tmp_path, seed, prompt, files)

        assert _render(config, {"customer": "acme", "language": "fr", "title": "a"}) == (
            "ACME/FR/HOUSE"
        )
        assert _render(config, {"customer": "globex", "language": "en", "title": "b"}) == (
            "GLOBEX/EN/HOUSE"
        )

    def test_a_plain_seed_is_the_same_for_every_record(self, tmp_path):
        seed = {**SYLLABUS, "rules": "$file:rules.json"}
        config = _config(tmp_path, seed, "{{ seed.exam_syllabus.label }}+{{ seed.rules.label }}")

        assert _render(config, {"exam": "dbt", "title": "a"}) == "DBT-LABEL+RULES-LABEL"
        assert _render(config, {"exam": "snowflake", "title": "b"}) == "SNOW-LABEL+RULES-LABEL"

    def test_an_integer_value_matches_a_key_written_as_an_integer(self, tmp_path):
        seed = {"tier": {"select_by": "source.tier", "files": {1: "$file:dbt.json"}}}
        config = _config(tmp_path, seed, "{{ seed.tier.label }}")

        assert _render(config, {"tier": 1, "title": "a"}) == "DBT-LABEL"
        assert _render(config, {"tier": "1", "title": "b"}) == "DBT-LABEL"

    def test_the_selector_does_not_have_to_be_observed(self, tmp_path):
        config = _config(tmp_path, SYLLABUS, "{{ seed.exam_syllabus.label }}", drop=["source.exam"])

        assert _render(config, {"exam": "snowflake", "title": "a"}) == "SNOW-LABEL"

    def test_two_files_are_cached_separately(self, tmp_path):
        _config(tmp_path, SYLLABUS, "")
        loader = StaticDataLoader(tmp_path / "workflow" / "seed_data")

        first = loader.load_static_data(SYLLABUS, source={"exam": "dbt"}, action_name="a")
        second = loader.load_static_data(SYLLABUS, source={"exam": "snowflake"}, action_name="a")

        assert first["exam_syllabus"]["label"] == "DBT-LABEL"
        assert second["exam_syllabus"]["label"] == "SNOW-LABEL"
        assert len(loader._cache) == 2


class TestARecordWithoutAUsableValueStops:
    def test_an_unknown_value_stops_with_the_known_values(self, tmp_path):
        config = _config(tmp_path, SYLLABUS, "{{ seed.exam_syllabus.label }}")

        with pytest.raises(StaticDataLoadError) as excinfo:
            _render(config, {"exam": "snowflak", "title": "a"})

        assert str(excinfo.value) == (
            "Seed 'exam_syllabus' in action 'generate_question': record value 'snowflak' "
            "for 'source.exam' is not in the file map. Known values: dbt, snowflake."
        )

    @pytest.mark.parametrize("record", [{"title": "a"}, {"exam": None, "title": "a"}])
    def test_a_missing_or_null_value_stops(self, tmp_path, record):
        config = _config(tmp_path, SYLLABUS, "{{ seed.exam_syllabus.label }}")

        with pytest.raises(StaticDataLoadError) as excinfo:
            _render(config, record)

        assert str(excinfo.value) == (
            "Seed 'exam_syllabus' in action 'generate_question': record has no value "
            "for 'source.exam'. Known values: dbt, snowflake."
        )

    @pytest.mark.parametrize(
        ("value", "type_name"),
        [(True, "bool"), (1.5, "float"), (["dbt"], "list"), ({"name": "dbt"}, "dict")],
    )
    def test_a_value_of_the_wrong_type_stops(self, tmp_path, value, type_name):
        config = _config(tmp_path, SYLLABUS, "{{ seed.exam_syllabus.label }}")

        with pytest.raises(StaticDataLoadError) as excinfo:
            _render(config, {"exam": value, "title": "a"})

        assert str(excinfo.value) == (
            "Seed 'exam_syllabus' in action 'generate_question': value for 'source.exam' "
            f"must be a string or an integer, got {type_name}."
        )


class TestEveryRenderPathSelectsTheSameFile:
    @pytest.mark.parametrize("mode", [RunMode.ONLINE, RunMode.BATCH])
    def test_the_staging_dry_run_selects_in_both_modes(self, tmp_path, mode):
        """The render staging does on a file's first record, before any record is prepared."""
        config = _config(tmp_path, SYLLABUS, "{{ seed.exam_syllabus.label }}")
        prompts = {}
        for exam in ("dbt", "snowflake"):
            record = {"exam": exam, "title": exam}
            prompts[exam] = PromptPreparationService.prepare_prompt_with_context(
                config, "a", record, mode=mode, source_content=record, current_item=record
            ).formatted_prompt

        assert prompts == {"dbt": "DBT-LABEL", "snowflake": "SNOW-LABEL"}
