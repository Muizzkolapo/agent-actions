"""The output the mock builds for a tool action that the sandbox scenario stubs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_actions.llm.providers.agac.contract import Contract
from agent_actions.llm.providers.agac.fake_data import FakeDataGenerator
from agent_actions.utils.constants import RECORD_INPUT_KEY

if TYPE_CHECKING:
    from agent_actions.llm.providers.agac.scenario import Scenario


def stub_output(followed: Scenario, agent_config: dict[str, Any], context_data: Any) -> Any:
    """The record a stubbed tool stores for one input record.

    Built from the tool's output schema as an LLM action's mock answer is: the schema
    keywords, the action's expectation rules, an observed input field of the same name,
    then the scenario's ``pin``. Seeded with the action and the record's input, never
    with a call order or a ``source_guid``, so one input gets one output in every run.
    """
    action = str(agent_config.get("name"))
    record_input = agent_config.get(RECORD_INPUT_KEY)
    if record_input is None:
        record_input = context_data
    schema = agent_config.get("json_output_schema") or {}
    FakeDataGenerator.set_context(prompt=f"{action}:{followed.record_key(record_input, '')}")
    contract = Contract.for_request(agent_config, action, record_input)
    output = contract.generate(schema, 1)
    pin = followed.rules_for(action, record_input).pin
    if pin and isinstance(output, dict):
        contract.pin(output, schema, pin)
    followed.count("calls")
    return output
