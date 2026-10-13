"""A file in a subfolder of templates/ reads the folder's names wherever it is used from."""

from pathlib import Path

import pytest
import yaml

from agent_actions.errors import TemplateRenderingError
from agent_actions.prompt.render_workflow import render_pipeline_with_templates

DEFINES = "{% set v = 'vee' %}{% macro vm() %}VM{% endmacro %}\n"

# The file that uses the subfolder file, named before and after the one that defines.
BEFORE_AND_AFTER = pytest.mark.parametrize(
    "user, definer", [("a.j2", "z.j2"), ("z.j2", "a.j2")], ids=["user-first", "definer-first"]
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
def test_a_variable_imported_from_a_subfolder_file_was_set_from_the_folders(
    tmp_path, user, definer
):
    templates = {
        user: "{% from 'sub/lib.j2' import tone %}{% set t2 = tone %}\n",
        "sub/lib.j2": "{% set tone = v | upper %}\n",
        definer: DEFINES,
    }

    assert _prompt(tmp_path, "{{ t2 }}", templates) == "VEE"


@BEFORE_AND_AFTER
def test_a_subfolder_files_macro_reads_the_folders_variable_and_macro(tmp_path, user, definer):
    templates = {
        user: "{% import 'sub/lib.j2' as lib %}"
        "{% macro use() %}[{{ lib.helper('q') }}]{% endmacro %}\n",
        "sub/lib.j2": "{% macro helper(x) %}h({{ x }}{{ v }}{{ vm() }}){% endmacro %}\n",
        definer: DEFINES,
    }

    assert _prompt(tmp_path, "{{ use() }}", templates) == "[h(qveeVM)]"


@BEFORE_AND_AFTER
def test_the_workflow_imports_a_subfolder_file_a_templates_file_imported_first(
    tmp_path, user, definer
):
    templates = {
        user: "{% from 'sub/lib.j2' import tone %}{% set t2 = tone %}\n",
        "sub/lib.j2": "{% set tone = v | upper %}"
        "{% macro helper(x) %}h({{ x }}{{ v }}){% endmacro %}\n",
        definer: DEFINES,
    }

    prompt = _prompt(
        tmp_path,
        "{{ lib.tone }} {{ lib.helper('w') }}",
        templates,
        head="{% import 'sub/lib.j2' as lib %}\n",
    )

    assert prompt == "VEE h(wvee)"


@BEFORE_AND_AFTER
def test_a_subfolder_file_included_without_context_reads_the_folders_variable(
    tmp_path, user, definer
):
    templates = {
        user: "{% set line %}{% include 'sub/p.j2' without context %}{% endset %}\n",
        "sub/p.j2": "P {{ v }}",
        definer: DEFINES,
    }

    prompt = _prompt(tmp_path, "{{ line }} / {% include 'sub/p.j2' without context %}", templates)

    assert prompt == "P vee / P vee"


@pytest.mark.parametrize("unrelated", [0, 1, 3])
def test_a_subfolder_file_does_not_hand_its_importer_the_importers_own_names(tmp_path, unrelated):
    templates = {
        "a.j2": "{% from 'sub/lib.j2' import seen %}{% set n = seen + 1 %}\n",
        "sub/lib.j2": "{% set seen = n | default(0) %}\n",
    }
    for i in range(unrelated):
        templates[f"other_{i}.j2"] = f"{{% set other_{i} = {i} %}}\n"

    assert _prompt(tmp_path, "{{ n }}", templates) == "1"


def test_a_subfolder_file_reading_a_name_no_file_defines_fails_the_load(tmp_path):
    templates = {
        "a.j2": "{% import 'sub/lib.j2' as lib %}"
        "{% macro use() %}{{ lib.helper() }}{% endmacro %}\n",
        "sub/lib.j2": "{% macro helper() %}{{ nowhere() }}{% endmacro %}\n",
    }

    with pytest.raises(TemplateRenderingError, match="'nowhere' is undefined"):
        _prompt(tmp_path, "{{ use() }}", templates)


@pytest.mark.parametrize("order", ["abcde", "edcba", "cebda"])
def test_a_variable_passed_down_five_files(tmp_path, order):
    links = [
        "{% set v1 = v2 ~ '1' %}\n",
        "{% set v2 = v3 ~ '2' %}\n",
        "{% set v3 = v4 ~ '3' %}\n",
        "{% set v4 = v5 ~ '4' %}\n",
        "{% set v5 = '5' %}\n",
    ]
    templates = {f"{letter}.j2": link for letter, link in zip(order, links, strict=True)}

    assert _prompt(tmp_path, "{{ v1 }}", templates) == "54321"
