"""Each templates/ file's top level runs once, after the files whose names it reads."""

from pathlib import Path

import pytest
import yaml

from agent_actions.errors import TemplateRenderingError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates


def _prompt(tmp_path: Path, prompt: str, templates: dict[str, str], unrelated: int = 0) -> str:
    folder = tmp_path / "templates"
    for name, text in templates.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    for n in range(unrelated):
        (folder / f"other_{n}.j2").write_text(f"{{% set other_{n} = {n} %}}\n")
    path = tmp_path / "wf.yml"
    path.write_text(f'name: wf\nactions:\n  - name: act\n    intent: x\n    prompt: "{prompt}"\n')
    rendered = render_pipeline_with_templates(
        path, folder, compile_schemas=False, project_root=tmp_path
    )
    return yaml.safe_load(rendered)["actions"][0]["prompt"]


THREE_NAMES = pytest.mark.parametrize(
    "names",
    [("a.j2", "b.j2", "c.j2"), ("c.j2", "b.j2", "a.j2"), ("b.j2", "c.j2", "a.j2")],
    ids=["abc", "cba", "bca"],
)


@THREE_NAMES
@pytest.mark.parametrize("unrelated", [0, 2])
@pytest.mark.parametrize(
    "importing",
    [
        "{% from 'IMPORTED' import h with context %}{% macro g2() %}[{{ h() }}]{% endmacro %}",
        "{% import 'IMPORTED' as bb with context %}{% macro g2() %}[{{ bb.h() }}]{% endmacro %}",
        "{% set first = 1 %}{% from 'IMPORTED' import h with context %}"
        "{% macro g2() %}[{{ h() }}]{% endmacro %}",
    ],
    ids=["from", "import-as", "after-a-set"],
)
def test_a_file_imported_with_context_reads_a_third_files_variable(
    tmp_path, names, unrelated, importing
):
    importer, imported, setter = names
    templates = {
        importer: importing.replace("IMPORTED", imported) + "\n",
        imported: "{% macro h() %}H{{ style }}{% endmacro %}\n",
        setter: "{% set style = 'formal' %}\n",
    }

    assert _prompt(tmp_path, "{{ g2() }}", templates, unrelated) == "[Hformal]"


@pytest.mark.parametrize(
    "state, helpers",
    [("state.j2", "helpers.j2"), ("a_state.j2", "z_helpers.j2"), ("z_state.j2", "a_helpers.j2")],
)
def test_two_files_append_to_a_third_files_list_through_a_fourth_files_macro(
    tmp_path, state, helpers
):
    templates = {
        state: "{% set agents = [] %}\n",
        helpers: "{% macro register(x) %}{% set _ = agents.append(x) %}{% endmacro %}\n",
        "c_alpha.j2": "{{ register('alpha') }}\n",
        "m_zeta.j2": "{{ register('zeta') }}\n",
    }

    assert _prompt(tmp_path, "{{ agents | join(',') }}", templates) == "alpha,zeta"


@THREE_NAMES
def test_an_item_appended_through_another_name_for_the_list_is_in_the_list(tmp_path, names):
    setter, alias, changer = names
    templates = {
        setter: "{% set reg = [] %}\n",
        alias: "{% set reg2 = reg %}\n",
        changer: "{% set _ = reg2.append('c') %}\n",
    }

    assert _prompt(tmp_path, "{{ reg | join(',') }}|{{ reg2 | join(',') }}", templates) == "c|c"


@pytest.mark.parametrize("extra", ["{% set cy = cycler('x', 'y') %}", "{% set j = joiner(',') %}"])
@pytest.mark.parametrize("setter, changer", [("a.j2", "m.j2"), ("m.j2", "a.j2")])
def test_a_value_that_prints_its_address_does_not_lose_another_files_append(
    tmp_path, extra, setter, changer
):
    templates = {
        setter: "{% set reg = [] %}\n",
        changer: "{% set _ = reg.append('b') %}\n",
        "k.j2": extra + "\n",
    }

    assert _prompt(tmp_path, "{{ reg | join(',') }}", templates) == "b"


@pytest.mark.parametrize("unrelated", [0, 1, 3])
def test_a_file_that_counts_its_runs_ran_once(tmp_path, unrelated):
    templates = {
        "a.j2": "{% set runs = [] %}\n",
        "m.j2": "{% set _ = runs.append(1) %}{% set seen = other_0 | default('') %}\n",
        "z.j2": "{% from 'm.j2' import seen %}{% set again = seen %}\n",
    }

    assert _prompt(tmp_path, "{{ runs | length }}", templates, unrelated) == "1"


@pytest.mark.parametrize("failing, reading", [("a.j2", "z.j2"), ("z.j2", "a.j2")])
def test_the_file_named_by_the_error_is_the_one_that_reads_the_missing_name(
    tmp_path, failing, reading
):
    templates = {
        failing: "{% set y = nope() %}{% macro h() %}H{% endmacro %}\n",
        reading: "{% set x = h() %}\n",
    }

    with pytest.raises(TemplateRenderingError) as raised:
        _prompt(tmp_path, "x", templates)

    assert f"'{failing}'" in str(raised.value)
    assert "'nope' is undefined" in str(raised.value)


@pytest.mark.parametrize("first, second", [("a.j2", "z.j2"), ("z.j2", "a.j2")])
def test_two_files_reading_each_others_names_load_with_the_unset_one_empty(tmp_path, first, second):
    templates = {
        first: "{% set x = 'x' ~ (y | default('')) %}\n",
        second: "{% set y = 'y' ~ (x | default('')) %}\n",
    }

    assert _prompt(tmp_path, "{{ x }} {{ y }}", templates) in {"x yx", "xy y"}
