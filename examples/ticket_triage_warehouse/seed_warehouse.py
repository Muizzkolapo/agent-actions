"""Create warehouse.db with the support tickets this example reads.

Run it again to start from the same five tickets.
"""

import sqlite3
from pathlib import Path

TICKETS = [
    (1, "Charged twice", "I was billed two times this month"),
    (2, "App crashes", "The app crashes on start"),
    (3, "Locked out", "Cannot log in to my account"),
    (4, "Invoice wrong", "The invoice shows the wrong plan"),
    (5, "Slow sync", "Sync takes minutes"),
]


def seed(path: Path) -> None:
    path.unlink(missing_ok=True)
    with sqlite3.connect(path) as warehouse:
        warehouse.execute("CREATE TABLE tickets (ticket_id INTEGER, subject TEXT, body TEXT)")
        warehouse.executemany("INSERT INTO tickets VALUES (?, ?, ?)", TICKETS)


if __name__ == "__main__":
    target = Path(__file__).with_name("warehouse.db")
    seed(target)
    print(f"Wrote {len(TICKETS)} tickets to {target}")
