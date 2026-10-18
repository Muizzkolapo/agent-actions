"""`agac inspect context` shows which file each value of a selected seed gets."""

from agent_actions.cli.inspect import ContextCommand

SCOPE = {
    "seed": {
        "rules": "$file:rules.json",
        "exam_syllabus": {
            "select_by": "source.exam",
            "files": {"dbt": "$file:dbt.json", "snowflake": "snowflake.json"},
        },
    }
}


class TestTheSelectedSeedMap:
    def test_a_selected_seed_lists_its_values_and_files(self):
        assert ContextCommand._seed_selection(SCOPE) == {
            "exam_syllabus": {
                "select_by": "source.exam",
                "files": {"dbt": "dbt.json", "snowflake": "snowflake.json"},
            }
        }

    def test_a_selected_seed_is_still_one_namespace_key(self):
        assert ContextCommand._seed_namespace_keys(SCOPE) == ["rules", "exam_syllabus"]

    def test_plain_seeds_have_no_map(self):
        assert ContextCommand._seed_selection({"seed": {"rules": "$file:rules.json"}}) == {}
        assert ContextCommand._seed_selection({"observe": ["source.x"]}) == {}
