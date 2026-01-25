from pathlib import Path

import importlib
import sys
from types import ModuleType
from textwrap import dedent


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


def _bootstrap_ruamel_stub() -> None:
    if "ruamel" in sys.modules and "ruamel.yaml" in sys.modules:
        return

    ruamel = ModuleType("ruamel")
    ruamel_yaml = ModuleType("ruamel.yaml")

    class YAML:  # noqa: N801 - match ruamel.yaml API
        def __init__(self) -> None:
            self.preserve_quotes = False

        def load(self, _content: str):
            return {}

    ruamel_yaml.YAML = YAML
    sys.modules["ruamel"] = ruamel
    sys.modules["ruamel.yaml"] = ruamel_yaml


_bootstrap_agent_actions_namespace()
_bootstrap_ruamel_stub()

build_index = importlib.import_module("agent_actions.tooling.lsp.indexer").build_index
ReferenceType = importlib.import_module("agent_actions.tooling.lsp.models").ReferenceType


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_indexer_tracks_context_scope_and_duplicates(tmp_path: Path) -> None:
    _write_file(tmp_path / "agent_actions.yml", "name: demo\n")
    _write_file(
        tmp_path / "schema" / "output_schema.yml",
        dedent(
            """
type: object
properties:
  vote_summary:
    type: string
  details:
    type: object
    properties:
      score:
        type: number
"""
        ),
    )
    workflow_path = tmp_path / "agent_workflow" / "demo" / "agent_config" / "demo.yml"
    _write_file(
        workflow_path,
        dedent(
            """
actions:
  - name: aggregate_votes
    schema: output_schema
    context_scope:
      observe:
        - aggregate_votes.vote_summary
      drop:
        - aggregate_votes.details
      passthrough:
        - aggregate_votes.details.score
  - name: duplicate_action
    impl: do_something
  - name: duplicate_action
    impl: do_something_else
"""
        ),
    )

    index = build_index(tmp_path)
    action_meta = index.file_actions[workflow_path]["aggregate_votes"]
    assert action_meta.context_observe == ["aggregate_votes.vote_summary"]
    assert action_meta.context_drop == ["aggregate_votes.details"]
    assert action_meta.context_passthrough == ["aggregate_votes.details.score"]

    references = index.references_by_file[workflow_path]
    context_refs = [ref.value for ref in references if ref.type == ReferenceType.CONTEXT_FIELD]
    assert "aggregate_votes.vote_summary" in context_refs
    assert "aggregate_votes.details" in context_refs
    assert "aggregate_votes.details.score" in context_refs

    assert index.duplicate_actions_by_file[workflow_path] == {"duplicate_action"}
