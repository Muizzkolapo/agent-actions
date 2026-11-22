"""One prompt template rendered for many records gives each record its own text and errors."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_actions.errors import TemplateVariableError
from agent_actions.errors.classification import is_action_fatal
from agent_actions.prompt.context.null_namespace import NullNamespace
from agent_actions.prompt.service import PromptPreparationService

render = PromptPreparationService._render_prompt_template

# The mapping the template reads `zz` off is picked by the record, so the place the
# missing-field error names differs between records of one template.
PICKED = "{{ source[source.which].zz }}"


def _picked_context(which: str) -> dict:
    return {"source": {"which": which, "a": {"one": 1}, "b": {"two": 2}}}


def _render_error(template: str, context: dict) -> TemplateVariableError:
    with pytest.raises(TemplateVariableError) as raised:
        render(template, context, agent_name="act", mode="online")
    return raised.value


def test_one_template_renders_each_records_values():
    template = "Hello {{ source.name }}{% if source.vip %} (VIP){% endif %}!\n"
    for i in range(5):
        rendered = render(template, {"source": {"name": f"user{i}", "vip": i % 2 == 0}})
        assert rendered == f"Hello user{i}{' (VIP)' if i % 2 == 0 else ''}!\n"


def test_templates_rendered_in_turn_keep_their_own_text():
    assert render("A {{ x.v }}", {"x": {"v": 1}}) == "A 1"
    assert render("B {{ x.v }}", {"x": {"v": 2}}) == "B 2"
    assert render("A {{ x.v }}", {"x": {"v": 3}}) == "A 3"


def test_a_null_namespace_renders_empty_on_every_record():
    for _ in range(3):
        assert render("[{{ dep }}]", {"dep": NullNamespace("skipped")}) == "[]"


def test_inline_code_stays_literal_on_every_record():
    template = "Use `{% test %}` for {{ s.n }}"
    assert render(template, {"s": {"n": 1}}) == "Use `{% test %}` for 1"
    assert render(template, {"s": {"n": 2}}) == "Use `{% test %}` for 2"


def test_a_cache_point_renders_to_its_mark_on_every_record():
    first = render("head {% cache_point %}{{ s.n }}", {"s": {"n": 1}})
    second = render("head {% cache_point %}{{ s.n }}", {"s": {"n": 2}})
    assert first.startswith("head ") and first.endswith("1")
    assert second == first[:-1] + "2"


def test_the_missing_field_error_names_each_records_own_place():
    first = _render_error(PICKED, _picked_context("a"))
    second = _render_error(PICKED, _picked_context("b"))
    again = _render_error(PICKED, _picked_context("a"))

    assert first.missing_variables == ["source.a.zz"]
    assert "'source.a' has no field 'zz' (it has: one)" in str(first)
    assert second.missing_variables == ["source.b.zz"]
    assert "'source.b' has no field 'zz' (it has: two)" in str(second)
    assert again.missing_variables == ["source.a.zz"]


def test_a_syntax_error_raises_the_same_error_on_every_record():
    template = "line one\n{% if source.x %}never closed"
    errors = [_render_error(template, {"source": {"x": i}}) for i in range(3)]
    for error in errors:
        assert error.template_line == 2
        assert error.missing_variables == []
        assert is_action_fatal(error)
        assert str(error) == str(errors[0])


def test_an_undefined_name_raises_on_every_record():
    for _ in range(3):
        error = _render_error("{{ source.missing }}", {"source": {"present": 1}})
        assert error.missing_variables == ["source.missing"]


def test_records_rendered_at_once_on_threads_keep_their_own_values_and_places():
    def one(i: int) -> tuple[str, list[str]]:
        which = "a" if i % 2 else "b"
        rendered = render(
            "{{ source.n }}-{{ source[source.which].one | default('x') }}",
            {"source": {"n": i, "which": which, "a": {"one": 1}, "b": {}}},
        )
        error = _render_error(PICKED, _picked_context(which))
        return rendered, error.missing_variables

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, range(200)))

    for i, (rendered, missing) in enumerate(results):
        which = "a" if i % 2 else "b"
        assert rendered == f"{i}-{'1' if which == 'a' else 'x'}"
        assert missing == [f"source.{which}.zz"]


def test_two_renders_in_flight_at_once_each_search_their_own_context(monkeypatch):
    from agent_actions.prompt import service

    barrier = threading.Barrier(2, timeout=10)
    original = service._PROMPT_ENV.place_of

    def place_of_once_both_are_rendering(target):
        # Both renders have published their context before either reads it.
        barrier.wait()
        return original(target)

    monkeypatch.setattr(service._PROMPT_ENV, "place_of", place_of_once_both_are_rendering)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.map(lambda which: _render_error(PICKED, _picked_context(which)), "ab")

    assert a.missing_variables == ["source.a.zz"]
    assert b.missing_variables == ["source.b.zz"]
