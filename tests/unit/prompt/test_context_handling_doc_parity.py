"""Regression tests pinning the claim in docs/reference/execution/context-handling.md.

The doc states that batch and online modes build identical Jinja contexts when
given the same observe fields and context_scope, and that `{{ source.field }}`
is the single correct template pattern in both modes.

These tests fail if a future change re-introduces the historical inversion
(root-level injection in batch, source-namespaced in online).
"""

from __future__ import annotations

import pytest
from jinja2 import Environment, StrictUndefined, UndefinedError

from agent_actions.config.types import RunMode
from agent_actions.prompt.service import PromptPreparationService


def _build(mode: RunMode, observe_context: dict, context_scope: dict) -> dict:
    return PromptPreparationService._build_llm_context(
        mode=mode,
        llm_additional_context=observe_context,
        context_scope=context_scope,
    )


def _render(template_src: str, context: dict) -> str:
    env = Environment(undefined=StrictUndefined, autoescape=False)
    return env.from_string(template_src).render(**context)


class TestBatchOnlineContextParity:
    """Both modes must produce the same Jinja context for the same inputs."""

    def test_same_observe_yields_equal_context(self):
        observe_context = {"source": {"passage": "alpha", "url": "https://x"}}
        context_scope = {"observe": ["source.passage", "source.url"]}

        batch = _build(RunMode.BATCH, observe_context, context_scope)
        online = _build(RunMode.ONLINE, observe_context, context_scope)

        assert batch == online
        assert batch == {"source": {"passage": "alpha", "url": "https://x"}}

    def test_seed_observe_yields_equal_context(self):
        observe_context = {
            "source": {"passage": "alpha"},
            "seed": {"syllabus": {"unit": 1}},
        }
        context_scope = {"observe": ["source.passage", "seed.syllabus"]}

        batch = _build(RunMode.BATCH, observe_context, context_scope)
        online = _build(RunMode.ONLINE, observe_context, context_scope)

        assert batch == online

    def test_upstream_action_observe_yields_equal_context(self):
        observe_context = {
            "source": {"passage": "alpha"},
            "extract": {"facts": ["a", "b"]},
        }
        context_scope = {"observe": ["source.passage", "extract.facts"]}

        batch = _build(RunMode.BATCH, observe_context, context_scope)
        online = _build(RunMode.ONLINE, observe_context, context_scope)

        assert batch == online

    def test_empty_observe_yields_equal_empty_context(self):
        observe_context: dict = {}
        context_scope = {"observe": []}

        batch = _build(RunMode.BATCH, observe_context, context_scope)
        online = _build(RunMode.ONLINE, observe_context, context_scope)

        assert batch == online == {}


class TestSourceFieldRendersIdenticallyInBothModes:
    """`{{ source.field }}` is the single correct template pattern in both modes."""

    @pytest.mark.parametrize("mode", [RunMode.BATCH, RunMode.ONLINE])
    def test_source_field_renders_per_record_value(self, mode):
        observe_context = {"source": {"passage": "the quick brown fox"}}
        context_scope = {"observe": ["source.passage"]}

        context = _build(mode, observe_context, context_scope)
        prompt = _render("Echo: {{ source.passage }}", context)

        assert prompt == "Echo: the quick brown fox"

    def test_compiled_prompt_is_byte_identical_across_modes(self):
        """The doc's central claim: same input → same compiled prompt in both modes."""
        observe_context = {"source": {"passage": "alpha"}}
        context_scope = {"observe": ["source.passage"]}
        template_src = "Echo: {{ source.passage }}"

        batch_prompt = _render(
            template_src,
            _build(RunMode.BATCH, observe_context, context_scope),
        )
        online_prompt = _render(
            template_src,
            _build(RunMode.ONLINE, observe_context, context_scope),
        )

        assert batch_prompt == online_prompt == "Echo: alpha"


class TestBareFieldFailsInBothModes:
    """`{{ field }}` (bare, no namespace) is undefined in both modes."""

    @pytest.mark.parametrize("mode", [RunMode.BATCH, RunMode.ONLINE])
    def test_bare_field_raises_strict_undefined(self, mode):
        observe_context = {"source": {"passage": "alpha"}}
        context_scope = {"observe": ["source.passage"]}

        context = _build(mode, observe_context, context_scope)

        with pytest.raises(UndefinedError):
            _render("Echo: {{ passage }}", context)
