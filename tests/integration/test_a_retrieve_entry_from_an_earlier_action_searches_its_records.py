"""`context_scope.retrieve` with `from:` an earlier action: each record searches what that
action produced for the other records.

The workflow has two tool actions: `summarize` writes a summary and canonical keywords for
each ticket, and `link` lists the tickets similar to each one from its retrieve entry
`similar` (`from: summarize`), whose step is `link__similar`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_actions.config.project_paths import ProjectPathsFactory
from agent_actions.storage import get_storage_backend
from tests._support.agac_cli import run_agac

WORKFLOW = "tickets"
STEP = "link__similar"
LABEL = f"link: retrieve 'similar' ({STEP})"

TICKETS = [
    {"id": "T-1", "text": "I was charged twice for my invoice."},
    {"id": "T-2", "text": "My invoice shows a double payment."},
    {"id": "T-3", "text": "The app crashes when I upload a photo."},
    {"id": "T-4", "text": "Uploading a picture makes the app crash."},
    {"id": "T-5", "text": "Please change the email address of my account."},
]

TOOLS = """from pathlib import Path
from typing import Any

from agent_actions import udf_tool

CANONICAL = {
    "charged": "billing", "invoice": "billing", "payment": "billing",
    "crash": "crash", "crashes": "crash", "upload": "upload", "uploading": "upload",
    "photo": "image", "picture": "image", "email": "account", "account": "account",
}


@udf_tool
def summarize(data: Any, *args: Any) -> dict:
    source = data["source"]
    if source.get("fail") and Path("fail.marker").exists():
        raise RuntimeError("summarize failed on purpose")
    words = [w.strip(".,").lower() for w in str(source["text"]).split()]
    return {
        "ticket_id": source["id"],
        "summary": source["text"],
        "keywords": sorted({CANONICAL[w] for w in words if w in CANONICAL}),
    }


@udf_tool
def link(data: Any, *args: Any) -> dict:
    found = data["link__similar"]
    return {
        "similar": ",".join(m["id"] for m in found["matches"]),
        "index": found["index"],
    }
"""

SCHEMA = """name: summary
fields:
  - {id: ticket_id, type: string, required: true}
  - {id: summary, type: string, required: true}
  - id: keywords
    type: array
    items: {type: string}
    required: true
"""


def _workflow(similar: str, summarize_extra: str = "") -> str:
    return f"""name: {WORKFLOW}
description: "Similar tickets"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  run_mode: online
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: summarize
    kind: tool
    impl: summarize
    intent: "Summarize the ticket"
    schema: summary
    context_scope: {{ observe: [source.*] }}
{summarize_extra}
  - name: link
    kind: tool
    impl: link
    intent: "List similar tickets"
    dependencies: [summarize]
    schema: {{ similar: string, index: string }}
    context_scope:
      observe: [summarize.ticket_id]
      retrieve:
        similar: {similar}
"""


SIMILAR = (
    "{from: summarize, text: [summary, keywords], id: ticket_id, "
    "query: [summarize.summary, summarize.keywords], top_k: 2}"
)


def _project(tmp_path: Path, tickets=TICKETS, similar=SIMILAR, summarize_extra="") -> Path:
    root = tmp_path / "project"
    workflow = root / "agent_workflow" / WORKFLOW
    for folder in ("agent_io/staging", "agent_config"):
        (workflow / folder).mkdir(parents=True, exist_ok=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        "project_name: similar\ntool_path: [tools]\nschema_path: schema\n"
    )
    (root / "schema" / WORKFLOW / "summary.yml").write_text(SCHEMA)
    (root / "tools" / WORKFLOW / "ticket_tools.py").write_text(TOOLS)
    (workflow / "agent_config" / f"{WORKFLOW}.yml").write_text(_workflow(similar, summarize_extra))
    _stage(root, "tickets.json", tickets)
    return root


def _stage(root: Path, name: str, tickets) -> None:
    staging = root / "agent_workflow" / WORKFLOW / "agent_io" / "staging"
    (staging / name).write_text(json.dumps(tickets))


def _run(root: Path, *extra: str, code: int = 0) -> str:
    result = run_agac(root, "run", "-a", WORKFLOW, "-u", "tools", *extra)
    output = " ".join((result.stdout + result.stderr).split())
    assert result.returncode == code, output
    return output


def _rows(root: Path, action: str, *, sandbox: bool = False) -> list[dict]:
    paths = ProjectPathsFactory.create_project_paths(
        WORKFLOW, WORKFLOW, auto_create=False, project_root=root
    )
    backend = get_storage_backend(
        workflow_path=str(paths.io_dir.parent),
        workflow_name=f"{WORKFLOW}.sandbox" if sandbox else WORKFLOW,
    )
    backend.initialize()
    try:
        return [
            row
            for path in backend.list_target_files(action)
            for row in backend.read_target(action, path)
        ]
    finally:
        backend.close()


def _similar(root: Path, **kwargs) -> dict[str, list[str]]:
    """Each ticket's similar tickets, as `link__similar` found them."""
    found = {}
    for row in _rows(root, STEP, **kwargs):
        output = row["content"][STEP]
        if isinstance(output, dict):
            found[row["content"]["source"]["id"]] = [m["id"] for m in output["matches"]]
    return found


def _indexes(root: Path) -> set[str]:
    return {
        row["content"][STEP]["index"]
        for row in _rows(root, STEP)
        if isinstance(row["content"].get(STEP), dict)
    }


def _folder(root: Path, *, sandbox: bool = False) -> Path:
    io = root / "agent_workflow" / WORKFLOW / "agent_io"
    return (io / "sandbox" if sandbox else io) / "retrieve" / STEP


class TestEachRecordSearchesTheOthers:
    def test_a_record_never_matches_itself_and_each_gets_top_k(self, tmp_path):
        root = _project(tmp_path)

        _run(root)

        similar = _similar(root)
        assert sorted(similar) == ["T-1", "T-2", "T-3", "T-4", "T-5"]
        for ticket, ids in similar.items():
            assert ticket not in ids
            # Keyword search: a record that shares no word with the others matches fewer.
            assert len(ids) <= 2
        assert similar["T-1"][0] == "T-2"
        assert similar["T-2"][0] == "T-1"
        assert similar["T-3"][0] == "T-4"
        assert similar["T-4"][0] == "T-3"

    def test_the_action_reads_the_matches_and_every_record_reports_one_index(self, tmp_path):
        root = _project(tmp_path)

        _run(root)

        indexes = _indexes(root)
        assert len(indexes) == 1
        links = {r["content"]["source"]["id"]: r["content"]["link"] for r in _rows(root, "link")}
        assert links["T-1"]["similar"].split(",")[0] == "T-2"
        assert {link["index"] for link in links.values()} == indexes
        (index,) = indexes
        assert sorted(p.name for p in _folder(root).iterdir()) == [f"{index}.db"]

    def test_sixteen_concurrent_records_all_report_one_index(self, tmp_path):
        tickets = [{"id": f"T-{n}", "text": f"charged twice for invoice {n}"} for n in range(16)]
        root = _project(tmp_path, tickets=tickets, similar=SIMILAR.replace("top_k: 2", "top_k: 3"))

        _run(root)

        similar = _similar(root)
        assert len(similar) == 16
        assert len(_indexes(root)) == 1
        assert all(len(ids) == 3 and t not in ids for t, ids in similar.items())

    def test_inspect_notes_what_the_step_searches(self, tmp_path):
        root = _project(tmp_path)

        result = run_agac(root, "inspect", "-a", WORKFLOW, "-u", "tools")

        output = " ".join((result.stdout + result.stderr).split())
        assert result.returncode == 0, output
        assert (
            "link: retrieve 'similar' from action summarize by keyword on summarize.summary, "
            "summarize.keywords, top 2"
        ) in output


class TestTheCorpus:
    @pytest.mark.parametrize(
        ("extra", "left_out"),
        [
            # A guard that skips a record stores it guard-skipped; one that filters it
            # stores nothing.
            ("    guard: {condition: 'source.id != \"T-2\"', on_false: skip}", "T-2"),
            ("    guard: {condition: 'source.id != \"T-2\"', on_false: filter}", "T-2"),
        ],
    )
    def test_a_record_the_action_did_not_process_is_not_in_the_corpus(
        self, tmp_path, extra, left_out
    ):
        root = _project(tmp_path, summarize_extra=extra)

        _run(root)

        similar = _similar(root)
        assert similar["T-3"][0] == "T-4"
        assert all(left_out not in ids for ids in similar.values())

    def test_a_failed_record_is_not_in_the_corpus(self, tmp_path):
        tickets = [dict(t, fail=True) if t["id"] == "T-2" else t for t in TICKETS]
        root = _project(tmp_path, tickets=tickets)
        (root / "fail.marker").write_text("")

        _run(root, code=3)

        similar = _similar(root)
        assert "T-2" not in similar
        assert all("T-2" not in ids for ids in similar.values())

    def test_records_of_an_earlier_run_are_in_the_corpus_and_the_new_ones_are_noted(
        self, tmp_path
    ):
        root = _project(tmp_path, tickets=TICKETS[:1] + TICKETS[2:])
        _run(root)
        first = _indexes(root)

        _stage(root, "more.json", [TICKETS[1]])
        output = _run(root)

        similar = _similar(root)
        # The new record sees the records of the earlier run.
        assert similar["T-2"][0] == "T-1"
        # The answers of the earlier run stand: they did not see the new record.
        assert "T-2" not in similar["T-1"]
        assert (
            f"{LABEL}: 1 record was added since 4 earlier answers searched; "
            f"--rerun {STEP} to search again"
        ) in output
        assert output.count("earlier answers searched;") == 1
        (old,) = first
        assert len(_indexes(root)) == 2
        # The index each stored answer names is kept.
        assert {p.stem for p in _folder(root).iterdir()} == _indexes(root)
        assert old in _indexes(root)

        # A later run that adds no record to the corpus says nothing again.
        (root / "fail.marker").write_text("")
        _stage(root, "failing.json", [{"id": "T-9", "text": "Nothing works.", "fail": True}])
        output = _run(root, code=3)
        assert "earlier answer" not in output

    def test_a_changed_record_input_warns_the_step_once(self, tmp_path):
        root = _project(tmp_path)
        _run(root)
        changed = [
            dict(t, text="My invoice has a charge I do not know.") if t["id"] == "T-5" else t
            for t in TICKETS
        ]
        _stage(root, "tickets.json", changed)

        output = _run(root)

        warning = (
            f"{LABEL}: since 4 earlier answers searched the records, 0 changed, 1 left and 1 "
            "was added, so those answers may show old text or cite a record that is gone. "
            f"Run again with --rerun {STEP} to search again"
        )
        assert warning in output
        assert output.count("since 4 earlier answers") == 1
        assert _similar(root)["T-5"][0] in ("T-1", "T-2")

    def test_a_rerun_of_the_action_searches_again_and_warns_of_nothing(self, tmp_path):
        root = _project(tmp_path)
        _run(root)
        tools = root / "tools" / WORKFLOW / "ticket_tools.py"
        tools.write_text(tools.read_text().replace('"summary": source["text"]', '"summary": "x"'))

        # --rerun summarize reopens what reads it, the step too: every record searches again.
        output = _run(root, "--rerun", "summarize")

        assert "earlier answers" not in output
        assert len(_indexes(root)) == 1

    def test_rerun_of_the_step_searches_again_and_the_new_record_is_found(self, tmp_path):
        root = _project(tmp_path, tickets=TICKETS[:1] + TICKETS[2:])
        _run(root)
        _stage(root, "more.json", [TICKETS[1]])
        _run(root)

        output = _run(root, "--rerun", STEP)

        assert "was added since" not in output
        assert _similar(root)["T-1"][0] == "T-2"
        assert len(_indexes(root)) == 1
        assert len(list(_folder(root).iterdir())) == 1

    def test_fresh_empties_the_corpus_and_its_folder(self, tmp_path):
        root = _project(tmp_path)
        _run(root)
        _stage(root, "tickets.json", TICKETS[:2])

        output = _run(root, "--fresh")

        assert "earlier answers" not in output
        assert _similar(root) == {"T-1": ["T-2"], "T-2": ["T-1"]}
        assert len(list(_folder(root).iterdir())) == 1

    def test_clean_all_removes_the_folder(self, tmp_path):
        root = _project(tmp_path)
        _run(root)
        assert _folder(root).is_dir()

        result = run_agac(root, "clean", "-a", WORKFLOW, "--all", "--force")

        assert result.returncode == 0, result.stdout + result.stderr
        assert not _folder(root).parent.exists()

    def test_a_repeated_id_value_fails_the_step_naming_it(self, tmp_path):
        tickets = TICKETS + [{"id": "T-1", "text": "Another ticket with the same id."}]
        root = _project(tmp_path, tickets=tickets)

        output = _run(root, code=1)

        assert "id 'T-1' (ticket_id) names the records with source_guid" in output


class TestARetriedRecord:
    def test_a_retried_record_sees_every_record_while_earlier_ones_do_not_see_it(self, tmp_path):
        tickets = [dict(t, fail=True) if t["id"] == "T-2" else t for t in TICKETS]
        root = _project(tmp_path, tickets=tickets)
        (root / "fail.marker").write_text("")
        _run(root, code=3)
        (root / "fail.marker").unlink()

        result = run_agac(root, "retry", "-a", WORKFLOW)
        output = " ".join((result.stdout + result.stderr).split())

        assert result.returncode == 0, output
        similar = _similar(root)
        assert similar["T-2"][0] == "T-1"
        assert "T-2" not in similar["T-1"]
        assert "1 record was added since 4 earlier answers searched" in output


class TestTheSandbox:
    def test_a_sandbox_run_reads_the_sandbox_store_and_writes_under_the_sandbox_folder(
        self, tmp_path
    ):
        root = _project(tmp_path)
        _run(root)
        real = _similar(root)
        _stage(root, "tickets.json", TICKETS[:3])

        _run(root, "--sandbox")

        sandboxed = _similar(root, sandbox=True)
        assert sandboxed == {"T-1": ["T-2"], "T-2": ["T-1"], "T-3": []}
        assert _folder(root, sandbox=True).is_dir()
        # The real store and its folder are left as they were.
        assert _similar(root) == real
        assert len(list(_folder(root).iterdir())) == 1


class TestTheFieldsAreCheckedAtLoad:
    @pytest.mark.parametrize(
        ("similar", "words"),
        [
            (
                SIMILAR.replace("text: [summary, keywords]", "text: [summary, notes]"),
                "'text' names 'notes', which is no output field of the action it searches",
            ),
            (
                SIMILAR.replace("id: ticket_id", "id: number"),
                "'id' names 'number', which is no output field",
            ),
            (
                SIMILAR.replace("top_k: 2", "top_k: 2, where: {product: app}"),
                "'where' names 'product', which is no output field",
            ),
            (
                SIMILAR.replace("text: [summary, keywords]", "text: [summary, details]"),
                "'text' names 'details', which holds an object",
            ),
        ],
    )
    def test_a_field_the_action_does_not_write_is_refused(self, tmp_path, similar, words):
        root = _project(tmp_path, similar=similar)
        schema = root / "schema" / WORKFLOW / "summary.yml"
        schema.write_text(
            schema.read_text() + "  - {id: details, type: object, required: false}\n"
        )

        output = _run(root, code=1)

        assert words in output
        assert LABEL in output
