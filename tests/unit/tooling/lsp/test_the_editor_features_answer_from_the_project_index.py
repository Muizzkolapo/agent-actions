"""The editor requests (hover, definition, completion, outline, highlights, lenses,
semantic tokens, signature help) answer from the index of the file's project.

Each test indexes a small project on disk, opens a workflow or prompt file in an
in-memory workspace, and calls the request handler as the editor would.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from lsprotocol import types as lsp
from pygls.workspace import Workspace

from agent_actions.tooling.lsp import server as lsp_server
from agent_actions.tooling.lsp.handlers import (
    SEMANTIC_TOKEN_TYPES,
    build_hover_content,
    build_semantic_tokens,
    find_reference_at_position,
    get_prompt_symbols,
)
from agent_actions.tooling.lsp.indexer import build_index
from agent_actions.tooling.lsp.models import Location, Reference, ReferenceType

WORKFLOW = """\
name: wf
actions:
  - name: extract
    prompt: $wf.Extract
    schema: extract_out
    context_scope:
      observe:
        - source.text
  - name: summarize
    dependencies:
      - extract
    impl: summarize_it
    guard:
      condition: 'extract.score > 1'
      on_false: filter
    context_scope:
      observe:
        - extract.score
    defaults:
      seed: $file:countries.json
"""

PROMPTS = """\
# prompts
{prompt Extract}
Extract things from the text.
{end_prompt}
{prompt Unclosed}
never ends
"""

TOOL = '''\
from agent_actions import udf_tool


@udf_tool()
def summarize_it(data: dict) -> dict:
    """Summarize the record."""
    return data
'''


def _line_of(text: str, needle: str) -> int:
    return next(i for i, line in enumerate(text.splitlines()) if needle in line)


def _column_of(text: str, needle: str) -> int:
    return text.splitlines()[_line_of(text, needle)].index(needle)


@pytest.fixture
def project(tmp_path: Path):
    root = tmp_path.resolve() / "proj"
    config_dir = root / "agent_workflow" / "wf" / "agent_config"
    config_dir.mkdir(parents=True)
    (root / "agent_workflow" / "wf" / "seed_data").mkdir()
    (root / "prompt_store").mkdir()
    (root / "tools" / "wf").mkdir(parents=True)
    (root / "schema" / "wf").mkdir(parents=True)
    (root / "agent_actions.yml").write_text("schema_path: schema\n")
    workflow = config_dir / "wf.yml"
    workflow.write_text(WORKFLOW)
    prompts = root / "prompt_store" / "wf.md"
    prompts.write_text(PROMPTS)
    (root / "tools" / "wf" / "summarize_it.py").write_text(TOOL)
    (root / "schema" / "wf" / "extract_out.yml").write_text(
        "name: extract_out\nfields:\n  - id: score\n    type: number\n"
        "  - id: label\n    type: string\n"
    )
    (root / "agent_workflow" / "wf" / "seed_data" / "countries.json").write_text(
        '[{"code": "FR", "name": "France"}, {"code": "DE", "name": "Germany"}]'
    )

    workspace = Workspace(root.as_uri())
    for path in (workflow, prompts):
        workspace.put_text_document(
            lsp.TextDocumentItem(
                uri=path.as_uri(), language_id="yaml", version=1, text=path.read_text()
            )
        )

    lsp_server.server.project_indexes.clear()
    index = build_index(root)
    lsp_server.server.project_indexes[root] = index
    with patch.object(
        type(lsp_server.server), "workspace", new_callable=lambda: property(lambda _: workspace)
    ):
        yield {"root": root, "workflow": workflow, "prompts": prompts, "index": index}
    lsp_server.server.project_indexes.clear()


def _doc(path: Path) -> lsp.TextDocumentIdentifier:
    return lsp.TextDocumentIdentifier(uri=path.as_uri())


def _at(path: Path, line: int, character: int) -> dict:
    return {"text_document": _doc(path), "position": lsp.Position(line=line, character=character)}


def _hover_text(project, needle: str, offset: int = 1) -> str | None:
    line = _line_of(WORKFLOW, needle)
    column = _column_of(WORKFLOW, needle) + offset
    result = lsp_server.hover(lsp.HoverParams(**_at(project["workflow"], line, column)))
    return result.contents.value if result else None


class TestHover:
    def test_hover_on_a_prompt_reference_shows_the_prompt_text(self, project):
        text = _hover_text(project, "$wf.Extract", offset=2)

        assert text is not None
        assert "**Prompt**: `wf.Extract`" in text
        assert "Extract things from the text." in text

    def test_hover_on_a_tool_shows_its_signature_and_docstring(self, project):
        text = _hover_text(project, "summarize_it")

        assert text == (
            "**Tool**: `summarize_it`\n\n```python\ndef summarize_it(data: dict) -> dict\n```"
            "\n\nSummarize the record."
        )

    def test_hover_on_a_schema_lists_its_fields_and_file(self, project):
        text = _hover_text(project, "extract_out")

        assert text is not None
        assert text.startswith("**Schema**: `extract_out`")
        assert "extract_out.yml" in text
        assert "- `score`" in text
        assert "- `label`" in text

    def test_hover_on_a_dependency_shows_the_action_card(self, project):
        text = _hover_text(project, "- extract", offset=2)

        assert text is not None
        assert "**Action**: `extract`" in text
        assert "**Prompt**: `wf.Extract`" in text
        assert "**Schema**: `extract_out`" in text
        assert f"_Defined at line {_line_of(WORKFLOW, '- name: extract') + 1}_" in text

    def test_hover_on_a_seed_file_previews_its_first_record(self, project):
        text = _hover_text(project, "$file:countries.json", offset=8)

        assert text is not None
        assert text.startswith("**Seed file**: `countries.json` (2 records)")
        assert "France" in text
        assert "Germany" not in text

    def test_hover_away_from_any_reference_returns_nothing(self, project):
        result = lsp_server.hover(lsp.HoverParams(**_at(project["workflow"], 0, 0)))

        assert result is None

    def test_hover_in_a_file_of_no_indexed_project_returns_nothing(self, project, tmp_path):
        stray = tmp_path / "elsewhere.yml"

        assert lsp_server.hover(lsp.HoverParams(**_at(stray, 0, 0))) is None


class TestHoverContentFallbacks:
    def _ref(self, kind: ReferenceType, value: str, file_path: Path) -> Reference:
        return Reference(kind, value, Location(file_path=file_path, line=0), value)

    def test_an_unknown_prompt_tool_or_schema_has_no_hover(self, project):
        index = project["index"]
        for kind in (ReferenceType.PROMPT, ReferenceType.TOOL, ReferenceType.SCHEMA):
            assert (
                build_hover_content(self._ref(kind, "missing", project["workflow"]), index) is None
            )

    def test_an_action_with_only_a_location_shows_its_line(self, project):
        index = project["index"]
        index.file_actions.clear()
        index.actions["bare"] = Location(file_path=project["workflow"], line=4)

        text = build_hover_content(
            self._ref(ReferenceType.ACTION, "bare", project["workflow"]), index
        )

        assert text == "**Action**: `bare`\n\nDefined at line 5"

    def test_a_missing_seed_file_says_it_was_not_found(self, project):
        ref = self._ref(ReferenceType.SEED_FILE, "nowhere.json", project["workflow"])

        text = build_hover_content(ref, project["index"], current_file=project["workflow"])

        assert text is not None
        assert text.startswith("**Seed file**: `nowhere.json`\n\n_File not found.")

    def test_a_seed_file_that_escapes_its_folder_is_refused(self, project):
        ref = self._ref(ReferenceType.SEED_FILE, "../../../agent_actions.yml", project["workflow"])

        text = build_hover_content(ref, project["index"], current_file=project["workflow"])

        assert text is not None
        assert text == (
            "**Seed file**: `../../../agent_actions.yml`\n\n_File path escapes the seed folder_"
        )

    def test_a_seed_file_that_is_not_json_says_it_could_not_be_read(self, project):
        seed_dir = project["root"] / "agent_workflow" / "wf" / "seed_data"
        (seed_dir / "broken.json").write_text("{not json")
        ref = self._ref(ReferenceType.SEED_FILE, "broken.json", project["workflow"])

        text = build_hover_content(ref, project["index"], current_file=project["workflow"])

        assert text is not None
        assert text.startswith("**Seed file**: `broken.json`\n\n_Could not read:")

    @pytest.mark.parametrize(
        ("content", "expected_start", "expected_part"),
        [
            ('{"code": "FR"}', "**Seed file**: `one.json`\n\n", "FR"),
            ("[]", "**Seed file**: `one.json`\n\n_Empty or unsupported format_", ""),
            ("[1, 2]", "**Seed file**: `one.json` (2 records)\n\n```json\n1\n```", ""),
        ],
    )
    def test_a_seed_file_preview_follows_the_shape_of_its_data(
        self, project, content, expected_start, expected_part
    ):
        seed_dir = project["root"] / "agent_workflow" / "wf" / "seed_data"
        (seed_dir / "one.json").write_text(content)
        ref = self._ref(ReferenceType.SEED_FILE, "one.json", project["workflow"])

        text = build_hover_content(ref, project["index"], current_file=project["workflow"])

        assert text is not None
        assert text.startswith(expected_start)
        assert expected_part in text


class TestGotoDefinition:
    def test_a_tool_reference_jumps_to_the_function(self, project):
        line = _line_of(WORKFLOW, "summarize_it")
        column = _column_of(WORKFLOW, "summarize_it") + 1

        result = lsp_server.goto_definition(
            lsp.DefinitionParams(**_at(project["workflow"], line, column))
        )

        assert result is not None
        assert result.uri == (project["root"] / "tools" / "wf" / "summarize_it.py").as_uri()
        assert result.range.start.line == _line_of(TOOL, "def summarize_it")

    def test_a_dependency_jumps_to_the_action_it_names(self, project):
        line = _line_of(WORKFLOW, "- extract")
        column = _column_of(WORKFLOW, "- extract") + 2

        result = lsp_server.goto_definition(
            lsp.DefinitionParams(**_at(project["workflow"], line, column))
        )

        assert result is not None
        assert result.uri == project["workflow"].as_uri()
        assert result.range.start.line == _line_of(WORKFLOW, "- name: extract")

    def test_a_position_on_no_reference_has_no_definition(self, project):
        result = lsp_server.goto_definition(lsp.DefinitionParams(**_at(project["workflow"], 0, 0)))

        assert result is None


class TestCompletions:
    def _labels(self, project, line: int, character: int) -> list[str]:
        result = lsp_server.completions(
            lsp.CompletionParams(**_at(project["workflow"], line, character))
        )
        return [item.label for item in result.items]

    def test_after_a_prompt_dollar_the_project_prompts_are_offered(self, project):
        line = _line_of(WORKFLOW, "$wf.Extract")

        labels = self._labels(project, line, _column_of(WORKFLOW, "$wf.Extract") + 1)

        assert "wf.Extract" in labels
        assert all(label.startswith("wf.") for label in labels)

    def test_after_impl_the_project_tools_are_offered(self, project):
        line = _line_of(WORKFLOW, "impl:")

        assert self._labels(project, line, len(WORKFLOW.splitlines()[line])) == ["summarize_it"]

    def test_after_schema_the_project_schemas_are_offered(self, project):
        line = _line_of(WORKFLOW, "schema:")

        assert self._labels(project, line, len(WORKFLOW.splitlines()[line])) == ["extract_out"]

    def test_in_dependencies_the_workflow_actions_are_offered(self, project):
        line = _line_of(WORKFLOW, "- extract")

        labels = self._labels(project, line, len(WORKFLOW.splitlines()[line]))

        assert sorted(labels) == ["extract", "summarize"]

    def test_a_line_past_the_end_of_the_document_offers_nothing(self, project):
        assert self._labels(project, 500, 0) == []

    def test_a_file_of_no_indexed_project_offers_nothing(self, project, tmp_path):
        result = lsp_server.completions(lsp.CompletionParams(**_at(tmp_path / "x.yml", 0, 0)))

        assert result.items == []


class TestDocumentSymbols:
    def test_a_workflow_outline_lists_its_actions(self, project):
        symbols = lsp_server.document_symbols(
            lsp.DocumentSymbolParams(text_document=_doc(project["workflow"]))
        )

        assert [(s.name, s.range.start.line) for s in symbols] == [
            ("extract", _line_of(WORKFLOW, "- name: extract")),
            ("summarize", _line_of(WORKFLOW, "- name: summarize")),
        ]

    def test_a_prompt_file_outline_lists_its_closed_prompt_blocks(self, project):
        symbols = lsp_server.document_symbols(
            lsp.DocumentSymbolParams(text_document=_doc(project["prompts"]))
        )

        assert [(s.name, s.range.start.line, s.range.end.line) for s in symbols] == [
            ("Extract", 1, 4)
        ]

    def test_get_prompt_symbols_skips_a_block_without_an_end(self):
        symbols = get_prompt_symbols("{prompt Open}\ntext\n")

        assert symbols == []


class TestHighlightsLensesAndTokens:
    def test_highlight_marks_every_use_of_the_reference_under_the_cursor(self, project):
        line = _line_of(WORKFLOW, "summarize_it")
        column = _column_of(WORKFLOW, "summarize_it") + 1

        highlights = lsp_server.document_highlight(
            lsp.DocumentHighlightParams(**_at(project["workflow"], line, column))
        )

        assert [(h.range.start.line, h.range.start.character) for h in highlights] == [
            (line, _column_of(WORKFLOW, "summarize_it"))
        ]

    def test_highlight_away_from_a_reference_marks_nothing(self, project):
        params = lsp.DocumentHighlightParams(**_at(project["workflow"], 0, 0))

        assert lsp_server.document_highlight(params) == []

    def test_a_guarded_action_gets_a_guard_lens(self, project):
        lenses = lsp_server.code_lens(lsp.CodeLensParams(text_document=_doc(project["workflow"])))

        assert [(lens.command.title, lens.range.start.line) for lens in lenses] == [
            ("Guard: extract.score > 1", _line_of(WORKFLOW, "guard:"))
        ]
        assert lenses[0].command.arguments == ["summarize"]

    def test_semantic_tokens_encode_each_reference_relative_to_the_previous(self, project):
        result = lsp_server.semantic_tokens(
            lsp.SemanticTokensParams(text_document=_doc(project["workflow"]))
        )

        data = result.data
        assert len(data) % 5 == 0 and data
        quintuples = [data[i : i + 5] for i in range(0, len(data), 5)]
        assert quintuples[0][0] == _line_of(WORKFLOW, "$wf.Extract")
        assert quintuples[0][3] == SEMANTIC_TOKEN_TYPES.index("string")

    def test_semantic_tokens_for_a_file_of_no_project_are_empty(self, project, tmp_path):
        result = lsp_server.semantic_tokens(
            lsp.SemanticTokensParams(text_document=_doc(tmp_path / "x.yml"))
        )

        assert result.data == []


class TestSignatureHelp:
    def test_on_a_guard_condition_line_the_observed_variables_are_listed(self, project):
        line = _line_of(WORKFLOW, "condition:")

        result = lsp_server.signature_help(
            lsp.SignatureHelpParams(**_at(project["workflow"], line, 10))
        )

        assert result is not None
        assert result.signatures[0].label.startswith("Available variables: ")
        assert "extract.score" in result.signatures[0].label

    def test_on_any_other_line_there_is_no_signature_help(self, project):
        result = lsp_server.signature_help(
            lsp.SignatureHelpParams(**_at(project["workflow"], 0, 0))
        )

        assert result is None


def _ref_at(kind: ReferenceType, line: int, column: int, end: int | None) -> Reference:
    return Reference(kind, "v", Location(Path("f.yml"), line, column, line, end), "v")


class TestSemanticTokenEncoding:
    def test_tokens_on_one_line_are_offset_from_the_previous_token(self):
        refs = [
            _ref_at(ReferenceType.TOOL, 2, 10, 14),
            _ref_at(ReferenceType.ACTION, 2, 2, 5),
            _ref_at(ReferenceType.SCHEMA, 4, 6, None),
        ]

        data = build_semantic_tokens(refs)

        assert data == [
            2, 2, 3, SEMANTIC_TOKEN_TYPES.index("variable"), 0,
            0, 8, 4, SEMANTIC_TOKEN_TYPES.index("function"), 0,
            2, 6, 1, SEMANTIC_TOKEN_TYPES.index("type"), 0,
        ]  # fmt: skip

    def test_a_workflow_reference_is_a_namespace_token(self):
        data = build_semantic_tokens([_ref_at(ReferenceType.WORKFLOW, 0, 0, 3)])

        assert data == [0, 0, 3, SEMANTIC_TOKEN_TYPES.index("namespace"), 0]

    def test_find_reference_at_position_matches_inclusive_column_bounds(self):
        ref = _ref_at(ReferenceType.TOOL, 1, 4, 8)

        assert find_reference_at_position([ref], 1, 4) is ref
        assert find_reference_at_position([ref], 1, 8) is ref
        assert find_reference_at_position([ref], 1, 9) is None
        assert find_reference_at_position([ref], 0, 5) is None
