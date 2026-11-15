"""A batch repair round sends the prompt the online loop sends for the same failure (1731).

Batch used to look only at ``repair == "auto"``: it ignored ``structural:`` for a schema
failure and sent no feedback for a ``repair: {prompt: ...}`` template.
"""

from __future__ import annotations

from typing import Any

import pytest

from agent_actions.expectations.service import ExpectationService
from agent_actions.expectations.types import Suite
from agent_actions.llm.batch.processing.preparator import _append_feedback
from agent_actions.llm.providers.batch_base import BatchResult
from agent_actions.processing.evaluation.strategies import ExpectationStrategy

SUITE = Suite(
    name="s",
    expectations=[
        {"id": "enough_options", "type": "item_count", "field": "options", "params": {"min": 2}}
    ],
)
PROMPT = "List the options for {{ source.topic }}."
TEMPLATE = {"prompt": "Your last answer failed:\n{failed_lines}\nAgain:\n{original_prompt}"}

RULE_FAILURE = {"options": ["only-one"]}
SCHEMA_FAILURE = "not a record"


def _batch_prompt(service: ExpectationService, content: Any) -> tuple[str, Any]:
    """The prompt the batch round sends, and the verdict it came from."""
    strategy = ExpectationStrategy(service)
    result = BatchResult(custom_id="r1", content=content, success=True)
    strategy.evaluate(result)
    task = {"target_id": "r1", "prompt": PROMPT}
    _append_feedback([task], {"r1": strategy.build_feedback(result)})
    return task["prompt"], strategy.verdict_for("r1")


def _online_prompt(service: ExpectationService, content: Any, verdict: Any) -> str:
    return service._prompt_for(2, PROMPT, content, verdict)


CASES = {
    "auto, rule failure": ({"repair": "auto"}, RULE_FAILURE),
    "auto with structural retry, schema failure": ({"repair": "auto"}, SCHEMA_FAILURE),
    "retry with structural auto, schema failure": (
        {"repair": "retry", "structural": "auto"},
        SCHEMA_FAILURE,
    ),
    "retry with structural auto, rule failure": (
        {"repair": "retry", "structural": "auto"},
        RULE_FAILURE,
    ),
    "template, rule failure": ({"repair": TEMPLATE}, RULE_FAILURE),
    "structural template, schema failure": (
        {"repair": "retry", "structural": TEMPLATE},
        SCHEMA_FAILURE,
    ),
    "retry, rule failure": ({"repair": "retry"}, RULE_FAILURE),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_batch_sends_the_prompt_online_sends(case):
    policy, content = CASES[case]
    service = ExpectationService(suite=SUITE, max_iterations=2, **policy)

    batch, verdict = _batch_prompt(service, content)

    assert batch == _online_prompt(service, content, verdict)


def test_a_schema_failure_under_structural_retry_resends_the_prompt_untouched():
    service = ExpectationService(suite=SUITE, max_iterations=2, repair="auto")

    assert _batch_prompt(service, SCHEMA_FAILURE)[0] == PROMPT


def test_a_schema_failure_under_structural_auto_gets_feedback():
    service = ExpectationService(suite=SUITE, max_iterations=2, repair="retry", structural="auto")

    sent = _batch_prompt(service, SCHEMA_FAILURE)[0]

    assert sent.startswith(PROMPT + "\n\n")
    assert len(sent) > len(PROMPT) + 2


def test_a_template_is_rendered_around_the_prompt():
    service = ExpectationService(suite=SUITE, max_iterations=2, repair=TEMPLATE)

    sent = _batch_prompt(service, RULE_FAILURE)[0]

    assert sent.startswith("Your last answer failed:\n")
    assert "enough_options" in sent
    assert sent.endswith("Again:\n" + PROMPT)


def test_a_template_that_starts_with_the_prompt_keeps_its_cache_prefix():
    service = ExpectationService(
        suite=SUITE, max_iterations=2, repair={"prompt": "{original_prompt}\n\nFix: {failed_lines}"}
    )
    strategy = ExpectationStrategy(service)
    result = BatchResult(custom_id="r1", content=RULE_FAILURE, success=True)
    strategy.evaluate(result)
    starts, wraps = {"target_id": "r1", "prompt": PROMPT}, {"target_id": "r1", "prompt": PROMPT}
    _append_feedback([starts], {"r1": strategy.build_feedback(result)})
    wrapping = ExpectationStrategy(
        ExpectationService(suite=SUITE, max_iterations=2, repair=TEMPLATE)
    )
    wrapping.evaluate(result)
    _append_feedback([wraps], {"r1": wrapping.build_feedback(result)})

    from agent_actions.llm.batch.processing.preparator import SHARED_PROMPT_LEN_KEY

    assert starts[SHARED_PROMPT_LEN_KEY] == len(PROMPT)
    assert SHARED_PROMPT_LEN_KEY not in wraps
