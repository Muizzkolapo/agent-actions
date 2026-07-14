"""ContextCommand surfaces the seed.* namespace from the seed directive."""

from agent_actions.cli.inspect import ContextCommand


class TestSeedNamespaceKeys:
    def test_seed_directive_keys_surfaced_in_order(self):
        ctx = {"seed": {"exam_syllabus": "$file:a.json", "rubric": "$file:b.json"}}
        assert ContextCommand._seed_namespace_keys(ctx) == ["exam_syllabus", "rubric"]

    def test_no_seed_directive_yields_no_keys(self):
        assert ContextCommand._seed_namespace_keys({"observe": ["x"]}) == []

    def test_non_dict_seed_yields_no_keys(self):
        assert ContextCommand._seed_namespace_keys({"seed": None}) == []
