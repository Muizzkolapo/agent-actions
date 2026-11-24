import textwrap

from agent_actions.prompt.deferred_values import LoadRender
from agent_actions.prompt.render_workflow import new_load_render


def test_new_load_render_uses_given_class_and_globals(tmp_path):
    class Sub(LoadRender): ...

    load, folder_names = new_load_render(
        "a: 1\n", tmp_path / "templates", tmp_path, load_class=Sub
    )
    assert type(load) is Sub
    assert "load_prompt" in load.env.globals
    assert "env" in load.env.globals
    assert folder_names == frozenset()
    assert load.env.filters["dedent"] is textwrap.dedent


def test_new_load_render_registers_template_macros(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "m.jinja2").write_text("{% macro greet(n) %}hi {{ n }}{% endmacro %}\n")

    load, folder_names = new_load_render("a: {{ greet('x') }}\n", templates, tmp_path)
    assert folder_names == {"greet"}
    assert load.render("a: {{ greet('x') }}\n", "wf.yml") == "a: hi x\n"
