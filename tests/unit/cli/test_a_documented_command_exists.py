"""A command a docs code block shows must be one `agac` has.

Code blocks only: a block is what a reader types, while prose may name a
command to say it is gone.
"""

from __future__ import annotations

import functools
import re
import shlex
from pathlib import Path

import click
import pytest

from agent_actions.cli.main import CLI

_DOCS = Path(__file__).resolve().parents[3] / "docs.agent-actions" / "docs"
_FENCE = re.compile(r"^\s*(```|~~~)")
_PROMPT = re.compile(r"^\s*\$\s+")
_SHELL_SEPARATOR = re.compile(r"\|\|?|&&|;")
_ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=\S*")

# Commands the docs show that the CLI does not have. The list may shrink, never
# grow: an entry here is a documentation gap, not an exemption.
_UNREGISTERED_BACKLOG = {
    ("reference/inspect.md", "inspect field-flow"),
    ("reference/inspect.md", "inspect conflicts"),
}


def _shown_commands(page: Path) -> list[tuple[int, list[str]]]:
    """(line, words after `agac`) for each `agac` invocation in the page's code blocks."""
    shown = []
    in_block = False
    for number, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
        if _FENCE.match(line):
            in_block = not in_block
            continue
        if not in_block:
            continue
        for segment in _SHELL_SEPARATOR.split(_PROMPT.sub("", line)):
            words = segment.split()
            while words and _ENV_ASSIGNMENT.fullmatch(words[0]):
                words.pop(0)
            if words[:1] == ["agac"]:
                shown.append((number, shlex.split(" ".join(words[1:]), comments=True)))
    return shown


def _pages() -> list[Path]:
    return sorted(p for p in _DOCS.rglob("*.md*") if _shown_commands(p))


@functools.cache
def _agac() -> click.Group:
    """The command tree `agac` runs; built on first use, not at collection."""
    return CLI().click_group


def _walk(words: list[str]) -> tuple[list[str], str | None]:
    """Read the words as `agac` does, down to the command they run.

    Returns the command names read and None or, where `agac` refuses a word,
    the names up to and including that word and what `agac` says about it.
    """
    command: click.Command = _agac()
    ctx = click.Context(command, info_name="agac")
    path: list[str] = []
    while isinstance(command, click.Group):
        while words and words[0].startswith("-"):
            flag = words[0].split("=", 1)[0]
            option = next(
                (
                    p
                    for p in command.get_params(ctx)
                    if isinstance(p, click.Option) and flag in p.opts + p.secondary_opts
                ),
                None,
            )
            if option is None:
                return [*path, flag], click.NoSuchOption(flag).format_message()
            takes_value = not (option.is_flag or option.count) and "=" not in words[0]
            words = words[1 + (option.nargs if takes_value else 0) :]
        # A synopsis names a slot, not a command: `agac batch <subcommand> [options]`.
        if not words or words[0].startswith(("<", "[")):
            break
        try:
            name, sub, words = command.resolve_command(ctx, words)
        except click.UsageError as error:
            return [*path, words[0]], error.format_message()
        path.append(name)
        command = sub
        ctx = click.Context(command, info_name=name, parent=ctx)
    return path, None


def _unregistered(page: Path) -> list[tuple[int, str, str]]:
    """(line, command up to the word `agac` refuses, what it says) for each refused one."""
    found = []
    for number, words in _shown_commands(page):
        path, refusal = _walk(words)
        if refusal is not None:
            found.append((number, " ".join(path), refusal))
    return found


def _relative(page: Path) -> str:
    return page.relative_to(_DOCS).as_posix()


def test_the_scan_still_finds_the_documented_commands():
    """Guards the scan: one that finds nothing would pass every page."""
    shown = [words for page in _pages() for _, words in _shown_commands(page)]
    assert len(shown) > 100, f"only {len(shown)} `agac` commands found in code blocks"


@pytest.mark.parametrize(
    "words, path",
    [
        (["run", "-a", "wf"], ["run"]),
        (["--debug", "run", "-a", "wf"], ["run"]),
        (["inspect", "-a", "wf", "action", "summarize"], ["inspect", "action"]),
        (["docs", "--port", "3000"], ["docs"]),
        (["init", "my_project"], ["init", "new"]),
        (["batch", "<subcommand>", "[options]"], ["batch"]),
    ],
)
def test_the_walk_reads_a_command_as_agac_does(words, path):
    """Guards the walk: an option's value is not a subcommand, and `init` routes a name to `new`."""
    assert _walk(words) == (path, None)


def test_the_walk_refuses_a_command_agac_does_not_have():
    """Guards the walk: one that accepts every word would pass every page."""
    assert _walk(["batch", "retry", "--batch-id", "b1"]) == (
        ["batch", "retry"],
        "No such command 'retry'.",
    )


@pytest.mark.parametrize("page", _pages(), ids=_relative)
def test_a_command_a_code_block_shows_is_one_agac_has(page):
    refused = [
        f"line {number}: `agac {command}` -> {refusal}"
        for number, command, refusal in _unregistered(page)
        if (_relative(page), command) not in _UNREGISTERED_BACKLOG
    ]
    assert not refused, f"{_relative(page)} shows commands agac does not have:\n" + "\n".join(
        refused
    )


def test_the_backlog_holds_nothing_that_is_already_fixed():
    """A backlog that outlives its gaps stops reporting the next one."""
    still_shown = {
        (_relative(page), command) for page in _pages() for _, command, _ in _unregistered(page)
    }
    assert _UNREGISTERED_BACKLOG <= still_shown, (
        f"{sorted(_UNREGISTERED_BACKLOG - still_shown)} no longer appear — drop them"
    )
