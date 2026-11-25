"""A filtered rerun over a database source writes its records back, on each database type.

The workflow reads its tickets from a table and writes three tables: a merge keyed
on the ticket, an append, and a replace. After `--rerun ACTION --where`, the merge
table holds the new answer of each matching ticket and the earlier answer of every
other, on SQLite, DuckDB, PostgreSQL and MySQL alike.
"""

import shutil
import uuid
from pathlib import Path

import pytest

from agent_actions.connections import ColumnType, WriteMode, open_connection
from tests._support.agac_cli import run_agac
from tests._support.databases import has_driver, mysql_server, postgres_server

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "ticket_triage_warehouse"
WORKFLOW = "ticket_triage_warehouse"
CONFIG = Path("agent_workflow") / WORKFLOW / "agent_config" / f"{WORKFLOW}.yml"
TOOLS = Path("tools") / WORKFLOW / "triage_tools.py"
TICKETS = [
    (1, "Charged twice", "I was billed two times this month"),
    (2, "App crashes", "The app crashes on start"),
    (3, "Locked out", "Cannot log in to my account"),
    (4, "Invoice wrong", "The invoice shows the wrong plan"),
    (5, "Slow sync", "Sync takes minutes"),
]
# What the routing tool adds to each ticket's hours, so a ticket answered again shows.
BONUS = "PASS_BONUS"
SLA = '        "sla_hours": 4 if int(data["classify"]["urgency"]) >= 4 else 24,\n'
SLA_WITH_BONUS = (
    '        "sla_hours": (4 if int(data["classify"]["urgency"]) >= 4 else 24)\n'
    f'        + int(__import__("os").environ.get("{BONUS}", "0")),\n'
)


@pytest.fixture(scope="module")
def servers():
    with postgres_server() as postgres, mysql_server() as mysql:
        yield {"postgres": postgres, "mysql": mysql}


@pytest.fixture(params=["sqlite", "duckdb", "postgres", "mysql"])
def settings(request, servers) -> dict:
    kind = request.param
    if kind == "sqlite":
        return {"type": "sqlite", "path": "warehouse.db"}
    if kind == "duckdb":
        if not has_driver("duckdb"):
            pytest.skip("the duckdb driver is not installed")
        return {"type": "duckdb", "path": "warehouse.duckdb"}
    if servers[kind] is None:
        pytest.skip(f"no {kind} server or driver on this machine")
    return servers[kind]


class _Warehouse:
    """A project whose tickets and results live in tables of one database."""

    def __init__(self, project: Path) -> None:
        self.project = project
        tag = uuid.uuid4().hex[:10]
        self.tickets = f"tickets_{tag}"
        self.routing = f"routing_{tag}"
        self.log = f"triage_log_{tag}"
        self.digest = f"digest_{tag}"

    def read(self, query: str) -> list[dict]:
        with open_connection("warehouse", self.project) as connector:
            return list(connector.read(query))

    def add_tickets(self, rows: list[tuple]) -> None:
        kinds = {
            "ticket_id": ColumnType.INTEGER,
            "subject": ColumnType.TEXT,
            "body": ColumnType.TEXT,
        }
        with open_connection("warehouse", self.project) as connector:
            connector.write(self.tickets, list(kinds), rows, mode=WriteMode.APPEND, types=kinds)

    def hours(self) -> dict[int, int]:
        rows = self.read(f"SELECT ticket_id, sla_hours FROM {self.routing}")
        return {int(row["ticket_id"]): int(row["sla_hours"]) for row in rows}

    def count(self, table: str) -> int:
        return len(self.read(f"SELECT * FROM {table}"))

    def agac(self, *args: str, bonus: int = 0, ends_with: int = 0) -> str:
        result = run_agac(self.project, *args, "-a", WORKFLOW, env={BONUS: str(bonus)})
        output = " ".join((result.stdout + result.stderr).split())
        assert result.returncode == ends_with, output[-3000:]
        return output


@pytest.fixture
def warehouse(settings, tmp_path: Path) -> _Warehouse:
    project = tmp_path / WORKFLOW
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns("warehouse.db", "agent_io"))
    (project / "agent_workflow" / WORKFLOW / "agent_io").mkdir()
    made = _Warehouse(project)

    settings_file = project / "agent_actions.yml"
    kept = settings_file.read_text(encoding="utf-8").split("connections:")[0]
    lines = "".join(f"    {key}: {value}\n" for key, value in settings.items())
    settings_file.write_text(f"{kept}connections:\n  warehouse:\n{lines}", encoding="utf-8")

    config = (project / CONFIG).read_text(encoding="utf-8")
    for old, new in (
        ("FROM tickets", f"FROM {made.tickets}"),
        ("table: ticket_routing", f"table: {made.routing}"),
        ("table: triage_log", f"table: {made.log}"),
        ("table: routing_digest", f"table: {made.digest}"),
    ):
        assert old in config, old
        config = config.replace(old, new)
    (project / CONFIG).write_text(config, encoding="utf-8")

    tools = project / TOOLS
    text = tools.read_text(encoding="utf-8")
    assert SLA in text
    tools.write_text(text.replace(SLA, SLA_WITH_BONUS), encoding="utf-8")

    made.add_tickets(TICKETS)
    made.agac("run")
    return made


def test_the_merge_table_holds_the_new_answer_of_each_matching_ticket_only(warehouse):
    before = warehouse.hours()
    assert sorted(before) == [1, 2, 3, 4, 5]

    output = warehouse.agac(
        "run", "--rerun", "route", "--where", "source.ticket_id <= 2", bonus=100
    )

    assert "2 of 5 record(s) of 'route' match; the other 3 keep their answers" in output
    after = warehouse.hours()
    assert {ticket: after[ticket] - before[ticket] for ticket in after} == {
        1: 100,
        2: 100,
        3: 0,
        4: 0,
        5: 0,
    }


def test_a_text_column_of_the_source_row_chooses_the_records(warehouse):
    before = warehouse.hours()

    warehouse.agac(
        "run", "--rerun", "route", "--where", 'source.subject == "App crashes"', bonus=7
    )

    after = warehouse.hours()
    assert [ticket for ticket in after if after[ticket] != before[ticket]] == [2]


def test_the_replace_table_is_rewritten_and_the_append_table_keeps_what_it_held(warehouse):
    logged = warehouse.count(warehouse.log)

    output = warehouse.agac(
        "run", "--rerun", "classify", "--where", "source.ticket_id <= 2", bonus=1
    )

    assert warehouse.count(warehouse.digest) == 1
    assert warehouse.count(warehouse.log) == logged == 5
    assert f"{warehouse.log} is written with mode: append" in output, output


def test_a_dry_run_and_no_match_leave_every_table_as_it_was(warehouse):
    before = warehouse.hours()

    warehouse.agac(
        "run", "--rerun", "route", "--where", "source.ticket_id <= 2", "--dry-run", bonus=100
    )
    warehouse.agac("run", "--rerun", "route", "--where", "source.ticket_id > 99", bonus=100)

    assert warehouse.hours() == before


def test_a_ticket_read_by_a_refresh_can_be_chosen_afterwards(warehouse):
    warehouse.add_tickets([(6, "Refund", "I want a refund")])
    warehouse.agac("run", "--refresh-input")
    before = warehouse.hours()
    assert sorted(before) == [1, 2, 3, 4, 5, 6]

    warehouse.agac("run", "--rerun", "route", "--where", "source.ticket_id == 6", bonus=50)

    after = warehouse.hours()
    assert [ticket for ticket in after if after[ticket] != before[ticket]] == [6]


def test_export_after_a_filtered_rerun_writes_the_same_table(warehouse):
    warehouse.agac("run", "--rerun", "route", "--where", "source.ticket_id <= 2", bonus=100)
    held = warehouse.hours()

    warehouse.agac("export")

    assert warehouse.hours() == held
