"""`prompt_debug` prints each prompt as one block when two actions at one level print at once."""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import patch

from agent_actions.llm.realtime.services.prompt_service import PromptService

ECHO = "agent_actions.llm.realtime.services.prompt_service.click.echo"
DIVIDER = "=" * 50
DASHES = "-" * 50


def _block(prompt: str, context: str) -> str:
    return (
        f"\n{DIVIDER}\nDEBUG MODE: Prompt being sent to the agent\n{DIVIDER}\n"
        f"{prompt}\n"
        f"\n[Context Data Preview]\n{DASHES}\n"
        f"{context}\n"
        f"{DIVIDER}\n\n"
    )


def test_two_threads_printing_at_once_each_print_their_whole_prompt_block():
    written: list[str] = []
    first_write = threading.Barrier(2, timeout=5)
    seen: set[int] = set()

    def echo(message: Any = "", **kwargs: Any) -> None:
        written.append(f"{message}\n")
        thread = threading.get_ident()
        if thread not in seen:
            seen.add(thread)
            # After its first write each thread waits for the other's, so a block
            # printed in more than one write is always cut by the other thread's.
            first_write.wait()

    prompts = [("## PAGE\nalpha", '{"id": "p1"}'), ("Label it.\nbeta", '{"id": "p2"}')]
    with patch(ECHO, side_effect=echo):
        threads = [
            threading.Thread(
                target=PromptService.debug_print_prompt,
                args=({"prompt_debug": True}, prompt, context),
            )
            for prompt, context in prompts
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

    first, second = (_block(*args) for args in prompts)
    assert "".join(written) in (first + second, second + first)


def test_the_block_reads_as_it_did_when_printed_line_by_line(capsys):
    PromptService.debug_print_prompt(
        {"prompt_debug": True}, "the prompt", "the context", {"answer": "string"}
    )

    assert capsys.readouterr().out == (
        f"\n{DIVIDER}\nDEBUG MODE: Prompt being sent to the agent\n{DIVIDER}\n"
        "the prompt\n"
        f"\n[Context Data Preview]\n{DASHES}\n"
        "the context\n"
        f"\n[Context Schema Preview]\n{DASHES}\n"
        '{\n  "answer": "string"\n}\n'
        f"{DIVIDER}\n\n"
    )
