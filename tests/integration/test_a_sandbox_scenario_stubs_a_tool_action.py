"""`agac run --sandbox` does not run a tool action that the scenario stubs.

`stub: true` under `actions.<tool action>` in the scenario has the mock build the tool's
output from its output schema, so a tool that calls a network service does not make a
sandbox run slow or online. Each tool here writes a marker file when its function runs.
Everything after the call is the real path: the output is stored, an action downstream
reads it, and two fresh runs store the same output. With no `stub`, and in a real run,
the tool runs. A scenario the run cannot follow stops it before any call.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import jsonschema
import pytest

from tests._support.agac_cli import REPO, run_agac

WORKFLOW = "catalog"
TITLES = ["Dune", "Emma", "Ulysses", "Beloved", "Hamlet", "Walden"]
ROWS = [{"isbn": f"978-{n}", "title": title} for n, title in enumerate(TITLES, start=1)]
ENV = {"OPENAI_API_KEY": ""}

CONFIG = """name: catalog
description: "Two tools read each book; an LLM action ranks what they found"
version: "0.1.0"
defaults:
  json_mode: true
  granularity: Record
  model_vendor: {vendor}
  model_name: gpt-4o-mini
  api_key: OPENAI_API_KEY
  data_source: {{ type: local, folder: ./staging, file_type: [json] }}
actions:
  - name: search
    kind: tool
    intent: "Search a catalog service"
    impl: search_catalog
    schema: search_output
    context_scope: {{ observe: [source.title, source.isbn] }}
    expect:
      repair: none
      expectations:
        - id: shelf_shape
          type: matches_regex
          field: shelf
          params: {{pattern: "^[A-Z]{{2}}-[0-9]{{3}}$"}}
  - name: lookup
    kind: tool
    intent: "Look up the publisher"
    impl: lookup_publisher
{lookup_keys}    context_scope: {{ observe: [source.title] }}
  - name: rank
    intent: "Rank what the catalog returned"
    dependencies: [search]
    schema: rank_output
    prompt: $catalog.Rank
    context_scope: {{ observe: [search.title, search.shelf, search.total_found] }}
"""

TOOLS = """from pathlib import Path
from typing import Any

from agent_actions import udf_tool

CALLED = Path(__file__).resolve().parents[2] / "called"


def _mark(name: str) -> None:
    CALLED.mkdir(exist_ok=True)
    (CALLED / name).write_text("called")


@udf_tool()
def search_catalog(data: dict[str, Any]) -> dict[str, Any]:
    _mark("search")
    return {
        "title": data["source"]["title"],
        "shelf": "AB-123",
        "origin": "the catalog service",
        "total_found": 1,
    }


@udf_tool()
def lookup_publisher(data: dict[str, Any]) -> dict[str, Any]:
    _mark("lookup")
    return {"title": data["source"]["title"], "publisher": "the publisher service"}
"""

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "shelf": {"type": "string", "pattern": "^[A-Z]{2}-[0-9]{3}$"},
        "origin": {"type": "string"},
        "total_found": {"type": "integer"},
    },
    "required": ["title", "shelf", "origin", "total_found"],
    "additionalProperties": False,
}
SCHEMAS = {
    "search_output": (
        "name: search_output\nfields:\n"
        "  - {id: title, type: string, required: true}\n"
        "  - {id: shelf, type: string, required: true}\n"
        "  - {id: origin, type: string, required: true}\n"
        "  - {id: total_found, type: integer, required: true}\n"
    ),
    "lookup_output": (
        "name: lookup_output\nfields:\n"
        "  - {id: title, type: string, required: true}\n"
        "  - {id: publisher, type: string, required: true}\n"
    ),
    "rank_output": (
        "name: rank_output\nfields:\n"
        "  - {id: title, type: string, required: true}\n"
        "  - {id: shelf, type: string, required: true}\n"
        "  - {id: pick, type: string, required: true}\n"
    ),
}
LOOKUP_KEYS = {
    "record": "    schema: lookup_output\n",
    "file": "    schema: lookup_output\n    granularity: File\n",
}
STUB_SEARCH = "actions:\n  search: {stub: true}\n"
STUB_BOTH = "actions:\n  search: {stub: true}\n  lookup: {stub: true}\n"


def _project(
    base: Path,
    scenario: str | None = None,
    *,
    lookup: str = "record",
    vendor: str = "openai",
    rows: list[dict] = ROWS,
) -> Path:
    root = base / "project"
    workflow_dir = root / "agent_workflow" / WORKFLOW
    (workflow_dir / "agent_config").mkdir(parents=True)
    (workflow_dir / "agent_io" / "staging").mkdir(parents=True)
    (root / "schema" / WORKFLOW).mkdir(parents=True)
    (root / "prompt_store").mkdir()
    (root / "tools" / WORKFLOW).mkdir(parents=True)
    (root / "agent_actions.yml").write_text(
        "default_agent_config: {model_name: gpt-4o-mini}\n"
        "schema_path: schema\ntool_path: [tools]\n"
    )
    (workflow_dir / "agent_config" / f"{WORKFLOW}.yml").write_text(
        CONFIG.format(vendor=vendor, lookup_keys=LOOKUP_KEYS[lookup])
    )
    (workflow_dir / "agent_io" / "staging" / "books.json").write_text(json.dumps(rows))
    (root / "prompt_store" / f"{WORKFLOW}.md").write_text(
        "# catalog\n\n{prompt Rank}\nRank the books found for this title.\n{end_prompt}\n"
    )
    (root / "tools" / WORKFLOW / "catalog_tools.py").write_text(TOOLS)
    for name, text in SCHEMAS.items():
        (root / "schema" / WORKFLOW / f"{name}.yml").write_text(text)
    if scenario is not None:
        (root / "sandbox.yml").write_text(scenario)
    return root


def _run(root: Path, *args: str):
    return run_agac(root, "run", "-w", WORKFLOW, "--sandbox", *args, env=ENV)


def _said(result) -> str:
    return " ".join((result.stdout + result.stderr).split())


def _ok(result):
    assert result.returncode == 0, _said(result)
    return result


def _stored(root: Path, action: str, *flags: str) -> dict[str, dict]:
    """What the action stored for each book, by the book's title."""
    shown = _ok(run_agac(root, "records", "-w", WORKFLOW, "-A", action, *flags, env=ENV))
    outputs = [record["content"][action] for record in json.loads(shown.stdout)]
    return {output["title"]: output for output in outputs}


def _called(root: Path) -> set[str]:
    folder = root / "called"
    return {path.name for path in folder.iterdir()} if folder.is_dir() else set()


def test_a_stubbed_tool_does_not_run_and_the_mock_s_output_is_stored(tmp_path):
    root = _project(tmp_path, STUB_SEARCH)

    result = _ok(_run(root))

    assert _called(root) == {"lookup"}
    found = _stored(root, "search", "--sandbox")
    assert set(found) == set(TITLES)
    for output in found.values():
        # The run adds the verdict of the action's rules to what the tool wrote.
        verdict = output.pop("expect")
        assert verdict["overall_pass"] is True, verdict
        jsonschema.validate(output, SEARCH_SCHEMA)
        assert output["origin"] != "the catalog service"
    assert _stored(root, "lookup", "--sandbox")["Dune"]["publisher"] == "the publisher service"
    assert "SANDBOX scenario sandbox.yml: 0 errors" in result.stdout


def test_an_action_downstream_reads_what_the_mock_built(tmp_path):
    root = _project(tmp_path, STUB_SEARCH)

    _ok(_run(root))

    found = _stored(root, "search", "--sandbox")
    ranked = _stored(root, "rank", "--sandbox")
    assert set(ranked) == set(TITLES)
    assert {title: ranked[title]["shelf"] for title in TITLES} == {
        title: found[title]["shelf"] for title in TITLES
    }
    assert len({output["shelf"] for output in found.values()}) > 1


@pytest.mark.parametrize("mode", ["sequential", "parallel"])
def test_the_run_says_which_tools_are_stubbed_and_does_not_show_them_as_run(tmp_path, mode):
    root = _project(tmp_path, STUB_SEARCH)

    result = _ok(_run(root, "--execution-mode", mode))

    assert mode in result.stdout
    notice = "SANDBOX: the scenario stubs these tool actions, so their code does not run: search"
    assert notice in result.stderr.splitlines(), result.stderr
    lines = {line.split()[1]: line for line in result.stderr.splitlines() if "records in" in line}
    assert lines["search"].rstrip().endswith("(stubbed)"), lines
    assert "stubbed" not in lines["lookup"], lines


def test_two_fresh_runs_store_the_same_output_serial_and_parallel(tmp_path):
    serial = _project(tmp_path / "serial", STUB_BOTH)
    # The books arrive in the other order, so an output tied to the order of the calls
    # would fall on other books.
    parallel = _project(tmp_path / "parallel", STUB_BOTH, rows=ROWS[::-1])

    runs = []
    for _ in range(2):
        _ok(_run(serial, "--fresh", "--execution-mode", "sequential"))
        runs.append({name: _stored(serial, name, "--sandbox") for name in ("search", "lookup")})
    second = _ok(_run(parallel, "--execution-mode", "parallel", "--concurrency-limit", "4"))

    assert "parallel" in _said(second)
    assert _called(serial) == _called(parallel) == set()
    assert runs[0] == runs[1]
    assert runs[0] == {name: _stored(parallel, name, "--sandbox") for name in runs[0]}
    assert runs[0]["search"]["Dune"] != runs[0]["search"]["Emma"]


def test_a_pin_and_a_matched_record_s_pin_set_the_stubbed_output(tmp_path):
    root = _project(
        tmp_path,
        "actions:\n  search: {stub: true, pin: {origin: stubbed}}\n"
        "records:\n  - match: {source.title: Dune}\n"
        "    actions: {search: {pin: {total_found: 0}}}\n",
    )

    _ok(_run(root))

    found = _stored(root, "search", "--sandbox")
    assert {title for title, output in found.items() if output["origin"] == "stubbed"} == set(
        TITLES
    ) - {"Dune"}
    assert found["Dune"]["total_found"] == 0


@pytest.mark.parametrize("scenario", [None, "seed: 4\n", "actions:\n  search: {stub: false}\n"])
def test_a_tool_the_scenario_does_not_stub_runs_its_own_code(tmp_path, scenario):
    root = _project(tmp_path, scenario)

    result = _ok(_run(root))

    assert _called(root) == {"search", "lookup"}
    assert _stored(root, "search", "--sandbox")["Dune"]["origin"] == "the catalog service"
    assert "stub" not in _said(result)


KEPT = "the stubs come from sandbox.yml, the rest from preset"


@pytest.mark.parametrize("preset", ["happy", "chaos"])
def test_a_preset_keeps_the_project_s_stubs_and_their_pin(tmp_path, preset):
    root = _project(tmp_path, "actions:\n  search: {stub: true, pin: {origin: stubbed}}\n")

    result = _run(root, "--scenario", preset)

    assert _called(root) == {"lookup"}, _said(result)
    notice = next(line for line in result.stderr.splitlines() if "stubs these tool" in line)
    assert notice.endswith(f"search ({KEPT} {preset})"), notice
    if preset == "happy":
        _ok(result)
        assert {output["origin"] for output in _stored(root, "search", "--sandbox").values()} == {
            "stubbed"
        }


def test_a_preset_keeps_only_the_stub_entries_of_the_project_file(tmp_path):
    root = _project(
        tmp_path,
        "defaults:\n  errors: {rate: 1.0, kinds: [server_error]}\n"
        "actions:\n  search: {stub: true}\n  rank: {pin: {pick: from the file}}\n"
        "records:\n  - match: {source.title: Dune}\n    actions: {rank: {error: refusal}}\n",
    )

    result = _ok(_run(root, "--scenario", "happy"))

    assert _called(root) == {"lookup"}
    assert "SANDBOX scenario happy: 0 errors" in result.stdout, _said(result)
    assert "from the file" not in {o["pick"] for o in _stored(root, "rank", "--sandbox").values()}


def test_a_scenario_path_does_not_take_the_project_s_stubs(tmp_path):
    root = _project(tmp_path, STUB_BOTH)
    path = tmp_path / "plain.yml"
    path.write_text("seed: 3\n")

    result = _ok(_run(root, "--scenario", str(path)))

    assert _called(root) == {"search", "lookup"}
    assert "stubs these tool actions" not in result.stderr
    assert "(stubbed)" not in result.stderr


def test_a_preset_refuses_a_project_stub_the_run_cannot_follow(tmp_path):
    root = _project(tmp_path, "actions:\n  rank: {stub: true}\n")

    result = _run(root, "--scenario", "chaos")

    said = _said(result)
    assert result.returncode != 0, said
    assert "preset chaos with the stubs of sandbox.yml" in said, said
    assert "- actions.rank.stub: " in said, said
    assert _called(root) == set()


def test_a_real_run_does_not_read_the_stub(tmp_path):
    root = _project(tmp_path, STUB_BOTH, vendor="agac-provider")

    result = _ok(run_agac(root, "run", "-w", WORKFLOW, env=ENV))

    assert _called(root) == {"search", "lookup"}
    assert _stored(root, "search")["Dune"]["origin"] == "the catalog service"
    assert "stub" not in _said(result)


@pytest.mark.parametrize(
    ("scenario", "lookup", "named", "why"),
    [
        ("actions:\n  rank: {stub: true}\n", "record", "actions.rank.stub", "not a tool action"),
        (
            "actions:\n  lookup: {stub: true}\n",
            "file",
            "actions.lookup.stub",
            "tool action 'lookup' has granularity File",
        ),
        (
            "actions:\n  search: {stub: true, errors: {rate: 1.0}}\n",
            "record",
            "actions.search.errors",
            "describes a model call",
        ),
        (
            "actions:\n  search: {latency_ms: 5}\n",
            "record",
            "actions.search.latency_ms",
            "describes a model call",
        ),
        (
            "actions:\n  search: {pin: {origin: x}}\n",
            "record",
            "actions.search.pin",
            "tool action 'search' is not stubbed",
        ),
        ("defaults:\n  stub: true\n", "record", "defaults.stub", "under actions"),
        (
            "actions:\n  search: {stub: true, pin: {orgin: x}}\n",
            "record",
            "actions.search.pin.orgin",
            "declares no field 'orgin'",
        ),
        (
            "actions:\n  serch: {stub: true}\n",
            "record",
            "actions.serch",
            "its tool actions: search, lookup",
        ),
    ],
)
def test_a_stub_the_run_cannot_follow_stops_it_before_any_call(
    tmp_path, scenario, lookup, named, why
):
    root = _project(tmp_path, scenario, lookup=lookup)

    result = _run(root)

    said = _said(result)
    assert result.returncode != 0, said
    assert f"- {named}: " in said, said
    assert why in said, said
    assert "Invalid configuration in sandbox.yml" in said, said
    assert _called(root) == set()
    io = root / "agent_workflow" / WORKFLOW / "agent_io"
    assert not (io / "store" / f"{WORKFLOW}.sandbox.db").exists()
    assert not (io / "sandbox" / "target").exists()


def _inspected(root: Path, action: str, *flags: str) -> str:
    shown = run_agac(root, "inspect", "-w", WORKFLOW, "--sandbox", *flags, "action", action)
    return _said(_ok(shown))


def test_inspect_marks_the_stubbed_tool_and_no_other_action(tmp_path):
    root = _project(tmp_path, STUB_SEARCH)

    assert "stubbed by the sandbox scenario" in _inspected(root, "search")
    assert "stubbed" not in _inspected(root, "lookup")
    assert "answered by the sandbox mock" in _inspected(root, "rank")
    assert _called(root) == set()


def test_inspect_reads_the_scenario_a_run_would_be_given(tmp_path):
    root = _project(tmp_path, STUB_SEARCH)
    other = tmp_path / "other.yml"
    other.write_text("actions:\n  lookup: {stub: true}\n")

    assert "stubbed by the sandbox scenario" in _inspected(root, "search", "--scenario", "happy")
    assert "stubbed by the sandbox scenario" not in _inspected(
        root, "search", "--scenario", str(other)
    )
    assert "stubbed by the sandbox scenario" in _inspected(
        root, "lookup", "--scenario", str(other)
    )


def test_inspect_refuses_a_scenario_the_run_would_refuse(tmp_path):
    root = _project(tmp_path, "actions:\n  rank: {stub: true}\n")

    shown = run_agac(root, "inspect", "-w", WORKFLOW, "--sandbox", "action", "search")

    assert shown.returncode != 0
    assert "actions.rank.stub" in _said(shown)


EXAMPLE = "book_catalog_enrichment"
# Appended to the example's tool: its one network call writes a marker and reaches no host.
NO_NETWORK = """

def _search_open_library(query: str, limit: int = 20) -> list[dict]:
    from pathlib import Path

    (Path(__file__).resolve().parents[2] / "searched").write_text(query)
    return []
"""


@pytest.mark.parametrize("stubbed", [True, False])
def test_the_book_catalog_example_makes_no_search_in_a_sandbox_run(tmp_path, stubbed):
    root = tmp_path / EXAMPLE
    shutil.copytree(REPO / "examples" / EXAMPLE, root)
    tool = root / "tools" / EXAMPLE / "search_book_catalog.py"
    assert "def _search_open_library(" in tool.read_text()
    tool.write_text(tool.read_text() + NO_NETWORK)
    if not stubbed:
        (root / "sandbox.yml").unlink()

    result = run_agac(root, "run", "-w", EXAMPLE, "--sandbox", "--fresh", env=ENV)

    assert result.returncode == 0, _said(result)
    assert (root / "searched").exists() is not stubbed
    assert "retrieve_candidates  3 records" in result.stderr, result.stderr
    assert ("(stubbed)" in result.stderr) is stubbed
