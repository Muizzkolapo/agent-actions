"""`agac skills list` shows each bundled skill with the description of its frontmatter."""

from pathlib import Path

from click.testing import CliRunner

from agent_actions.cli.skills import skill_description, skills

_SKILLS = Path(__file__).resolve().parents[3] / "agent_actions" / "skills"


def test_the_frontmatter_description_is_read():
    text = "---\nname: demo\ndescription: Run demo workflows safely.\n---\n\n# Demo\n\nBody text.\n"
    assert skill_description(text) == "Run demo workflows safely."


def test_a_page_with_no_frontmatter_gives_its_first_line_of_text():
    assert skill_description("# Demo\n\n# Heading\nFirst line.\n") == "First line."


def test_each_bundled_skill_has_a_description_and_the_list_shows_it():
    result = CliRunner().invoke(skills, ["list"])
    assert result.exit_code == 0, result.output
    for skill_md in sorted(_SKILLS.glob("*/SKILL.md")):
        description = skill_description(skill_md.read_text(encoding="utf-8"))
        assert description and not description.startswith("name:"), skill_md
        assert skill_md.parent.name in result.output
        assert description[:40] in result.output
