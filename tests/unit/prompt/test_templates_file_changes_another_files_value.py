"""A templates/ file that changes a value another file set changes the one the workflow reads."""

from pathlib import Path

import pytest
import yaml

from agent_actions.prompt.render_workflow import render_pipeline_with_templates

BEFORE_AND_AFTER = pytest.mark.parametrize(
    "setter, changer", [("a.j2", "m.j2"), ("m.j2", "a.j2")], ids=["setter-first", "changer-first"]
)


def _prompt(tmp_path: Path, prompt: str, templates: dict[str, str], head: str = "") -> str:
    folder = tmp_path / "templates"
    for name, text in templates.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    path = tmp_path / "wf.yml"
    path.write_text(
        f'{head}name: wf\nactions:\n  - name: act\n    intent: x\n    prompt: "{prompt}"\n'
    )
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)["actions"][0]["prompt"]


@BEFORE_AND_AFTER
@pytest.mark.parametrize("unrelated", [0, 2])
def test_an_item_appended_to_another_files_list_is_in_it_once(tmp_path, setter, changer, unrelated):
    templates = {setter: "{% set reg = [] %}\n", changer: "{% set _ = reg.append('b') %}\n"}
    for n in range(unrelated):
        templates[f"other_{n}.j2"] = f"{{% set other_{n} = {n} %}}\n"

    assert _prompt(tmp_path, "{{ reg | join(',') }}", templates) == "b"


@BEFORE_AND_AFTER
def test_a_key_added_to_another_files_dict_is_in_it(tmp_path, setter, changer):
    templates = {
        setter: "{% set cfg = {'a': 1} %}\n",
        changer: "{% set _ = cfg.update({'b': 2}) %}\n",
    }

    assert _prompt(tmp_path, "{{ cfg | dictsort | join(' ') }}", templates) == "('a', 1) ('b', 2)"


@pytest.mark.parametrize("names", [("a.j2", "m.j2", "z.j2"), ("z.j2", "a.j2", "m.j2")])
def test_two_files_adding_to_another_files_namespace_each_add_once(tmp_path, names):
    setter, first, second = names
    templates = {
        setter: "{% set ns = namespace(count=0) %}\n",
        first: "{% set ns.count = ns.count + 1 %}\n",
        second: "{% set ns.count = ns.count + 10 %}\n",
    }

    assert _prompt(tmp_path, "{{ ns.count }}", templates) == "11"


def test_a_subfolder_file_the_workflow_imports_reads_its_importers_names_too(tmp_path):
    templates = {
        "a.j2": "{% import 'sub/lib.j2' as lib %}{% set own = 'mine' %}\n",
        "sub/lib.j2": "{% set tone = own | default('none') %}\n",
    }

    prompt = _prompt(
        tmp_path, "{{ lib.tone }}", templates, head="{% import 'sub/lib.j2' as lib %}\n"
    )

    assert prompt == "mine"


def test_a_macro_reads_a_name_only_a_later_named_file_sets_through_its_own_file(tmp_path):
    templates = {
        "a.j2": "{% macro show() %}{{ late }}/{{ mine }}{% endmacro %}{% set mine = 'a' %}\n",
        "z.j2": "{% set late = 'z' %}\n",
    }

    assert _prompt(tmp_path, "{{ show() }}", templates) == "z/a"
