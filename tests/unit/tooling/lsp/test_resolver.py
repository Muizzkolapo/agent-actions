import importlib
import sys
from types import ModuleType
from pathlib import Path


def _bootstrap_agent_actions_namespace() -> None:
    root = Path(__file__).resolve().parents[4]
    agent_actions_path = root / "agent_actions"
    packages = {
        "agent_actions": agent_actions_path,
        "agent_actions.tooling": agent_actions_path / "tooling",
        "agent_actions.tooling.lsp": agent_actions_path / "tooling" / "lsp",
    }
    for name, path in packages.items():
        if name in sys.modules:
            continue
        module = ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module


_bootstrap_agent_actions_namespace()

ReferenceType = importlib.import_module("agent_actions.tooling.lsp.models").ReferenceType
get_reference_at_position = importlib.import_module(
    "agent_actions.tooling.lsp.resolver"
).get_reference_at_position


def test_get_reference_at_position_with_context_scope_passthrough() -> None:
    content = """actions:
  - name: sample_action
    context_scope:
      passthrough:
        - sample_action.output_value
"""
    reference = get_reference_at_position(content=content, line=4, character=12)
    assert reference is not None
    assert reference.type == ReferenceType.CONTEXT_FIELD
    assert reference.value == "sample_action.output_value"
