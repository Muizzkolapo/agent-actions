"""The editor reads each `context_scope.retrieve` entry as the step `<action>__<entry>`."""

from pathlib import Path

from agent_actions.tooling.lsp.diagnostics import collect_diagnostics
from agent_actions.tooling.lsp.indexer import _retrieve_reads, build_index

WORKFLOW = """name: wf
actions:
  - name: classify
    prompt: $wf.classify
  - name: write_reply
    prompt: $wf.answer
    dependencies: [classify]
    guard:
      condition: 'retrieve.help.count > 0'
    context_scope:
      observe: [source.text, retrieve.help.matches]
      retrieve:
        help:
          from: help_center
          query: [source.text, classify.keywords]
  - name: audit
    prompt: $wf.answer
    dependencies: [write_reply__help]
    context_scope:
      observe: [write_reply__help.matches]
"""


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "proj"
    workflow = root / "agent_workflow" / "wf"
    (workflow / "agent_config").mkdir(parents=True)
    (root / "agent_actions.yml").write_text("tool_path: [tools]\nschema_path: schema\n")
    config = workflow / "agent_config" / "wf.yml"
    config.write_text(WORKFLOW)
    return root, config


def test_the_step_and_the_alias_are_not_unresolved(tmp_path: Path):
    root, config = _project(tmp_path)

    messages = [d.message for d in collect_diagnostics(config, build_index(root))]

    assert not [m for m in messages if "retrieve" in m or "__help" in m], messages


def test_an_alias_in_an_action_with_no_entry_is_unresolved_as_before(tmp_path: Path):
    root, config = _project(tmp_path)
    config.write_text(
        WORKFLOW
        + """  - name: second
    prompt: $wf.answer
    context_scope:
      observe:
        - retrieve.faq.matches
      retrieve:
        faq: {from: help_center, query: source.text}
  - name: other
    prompt: $wf.answer
    guard:
      condition: 'retrieve.help.count > 0'
    context_scope:
      observe:
        - retrieve.help.matches
"""
    )

    messages = [d.message for d in collect_diagnostics(config, build_index(root))]

    assert [m for m in messages if "action `retrieve` is not defined" in m], messages
    assert [m for m in messages if "`retrieve.help.count`" in m], messages
    assert len([m for m in messages if "retrieve" in m]) == 2, messages


def test_reading_an_entry_leaves_its_parsed_query_as_it_is():
    entry = {"query": ["source.text", "classify.keywords"], "where": {"p": "classify.product"}}

    assert _retrieve_reads(entry) == ["classify"]
    assert entry["query"] == ["source.text", "classify.keywords"]


def test_the_step_is_indexed_at_its_entry_and_reads_its_query(tmp_path: Path):
    root, config = _project(tmp_path)

    step = build_index(root).file_actions[config]["write_reply__help"]

    assert step.location.line == 12
    assert step.dependencies == ["classify"]
