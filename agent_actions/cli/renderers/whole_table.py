"""Print a Rich table at its full width, wider than the terminal if it has to be."""

from rich.console import Console
from rich.measure import Measurement
from rich.segment import Segments
from rich.table import Table

_UNBOUNDED_WIDTH = 10_000


def print_whole(console: Console, table: Table) -> None:
    """Print *table* without fitting it to a narrow terminal.

    Fitted, Rich cuts cells short, and a record ID cut to "a1b2…" or a count cut to
    "12…" is a wrong answer. A line that wraps loses nothing.
    """
    natural = Measurement.get(
        console, console.options.update(width=_UNBOUNDED_WIDTH), table
    ).maximum
    # Rendered here and printed uncropped: setting console.width instead would pin
    # the console to one width for every print after this one.
    options = console.options.update(width=max(console.width, natural))
    console.print(Segments(console.render(table, options)), crop=False)
