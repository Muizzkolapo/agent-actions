"""The editor reads an optional observe entry as the reference it names.

`- review.rejected_text?` and `- field: review.rejected_text` both name the field
`rejected_text` of `review`. Indexed with the `?`, or as the mapping's first key, the
entry was reported as an action that is not defined in the workflow.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_actions.tooling.lsp.diagnostics import collect_diagnostics
from agent_actions.tooling.lsp.indexer import _index_workflow_file
from agent_actions.tooling.lsp.models import ProjectIndex, ReferenceType
from agent_actions.tooling.lsp.resolver import get_reference_at_position

_WORKFLOW = """\
actions:
  - name: review
    intent: review
    context_scope:
      observe:
        - source.text
  - name: retry
    intent: retry
    dependencies: [review]
    context_scope:
      observe:
{entries}
      passthrough:
        - review.verdict
"""

_ENTRIES = {
    "suffix": "        - review.rejected_text?",
    "quoted-suffix": "        - 'review.rejected_text?'",
    "mapping": "        - field: review.rejected_text\n          optional: true\n"
    '          default: ""',
    "mapping-with-suffix": "        - field: review.rejected_text?",
    "flow-mapping": "        - {field: review.rejected_text, optional: true}",
    "mapping-field-last": "        - optional: true\n          field: review.rejected_text",
}


def _indexed(tmp_path: Path, entries: str) -> tuple[ProjectIndex, Path]:
    yaml_file = tmp_path / "retry.yml"
    yaml_file.write_text(_WORKFLOW.format(entries=entries))
    index = ProjectIndex(root=tmp_path)
    index.file_actions[yaml_file] = {}
    index.references_by_file[yaml_file] = []
    index.duplicate_actions_by_file[yaml_file] = set()
    _index_workflow_file(index, yaml_file)
    return index, yaml_file


@pytest.mark.parametrize("form", sorted(_ENTRIES))
class TestEveryForm:
    def test_the_action_observes_the_plain_reference(self, tmp_path, form):
        index, yaml_file = _indexed(tmp_path, _ENTRIES[form])

        retry = index.file_actions[yaml_file]["retry"]
        assert retry.context_observe == ["review.rejected_text"]
        assert retry.context_passthrough == ["review.verdict"]

    def test_the_reference_range_covers_the_reference_alone(self, tmp_path, form):
        index, yaml_file = _indexed(tmp_path, _ENTRIES[form])
        lines = yaml_file.read_text().split("\n")

        fields = [
            ref
            for ref in index.references_by_file[yaml_file]
            if ref.type == ReferenceType.CONTEXT_FIELD
        ]
        assert [ref.value for ref in fields] == [
            "source.text",
            "review.rejected_text",
            "review.verdict",
        ]
        location = fields[1].location
        assert lines[location.line][location.column : location.end_column] == "review.rejected_text"

    def test_nothing_is_reported_unresolved(self, tmp_path, form):
        index, yaml_file = _indexed(tmp_path, _ENTRIES[form])

        assert [d.message for d in collect_diagnostics(yaml_file, index)] == []


@pytest.mark.parametrize("form", ["suffix", "mapping", "flow-mapping"])
def test_the_cursor_on_an_entry_finds_its_reference(form):
    lines = _WORKFLOW.format(entries=_ENTRIES[form]).split("\n")
    line = next(i for i, text in enumerate(lines) if "review.rejected_text" in text)
    column = lines[line].index("review.rejected_text") + 3

    reference = get_reference_at_position("\n".join(lines), line, column)

    assert reference is not None
    assert reference.type == ReferenceType.CONTEXT_FIELD
    assert reference.value == "review.rejected_text"
