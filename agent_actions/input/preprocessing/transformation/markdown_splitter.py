"""Split markdown or plain text at headings, then paragraphs, then sentences.

Tokens are counted offline (no tokenizer download): each run of letters and digits counts
one token per six characters, at least one, and each other visible character counts one.
That is close to ``cl100k_base`` on English prose, and a little over it on code.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_TOKEN = re.compile(r"\w+|[^\w\s]")
_CHARS_PER_TOKEN = 6
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
PATH_SEPARATOR = " > "


@dataclass(frozen=True)
class MarkdownChunk:
    title: str
    text: str
    body: str


def count_tokens(text: str) -> int:
    return sum(
        max(1, math.ceil(len(token) / _CHARS_PER_TOKEN)) if token[0].isalnum() or token[0] == "_"
        else 1
        for token in _TOKEN.findall(text)
    )


def split_markdown(text: str, chunk_size: int, overlap: int) -> list[MarkdownChunk]:
    """Chunks of at most *chunk_size* tokens, each starting with its heading path.

    A unit (sentence or word) that alone passes the size is cut into pieces.
    """
    chunks: list[MarkdownChunk] = []
    for path, body in _sections(text):
        title = PATH_SEPARATOR.join(path)
        prefix = f"{title}\n" if title else ""
        budget = max(1, chunk_size - count_tokens(prefix))
        for packed in _packed(_units(body, budget), budget, min(overlap, budget // 2)):
            chunks.append(MarkdownChunk(title=title, text=prefix + packed, body=packed))
    return chunks


def _sections(text: str) -> list[tuple[list[str], str]]:
    """Each heading path with the text under it, in order; text before any heading has none."""
    sections: list[tuple[list[str], str]] = []
    path: list[tuple[int, str]] = []
    lines: list[str] = []
    in_fence = False

    def close() -> None:
        body = "\n".join(lines).strip()
        if body:
            sections.append(([title for _, title in path], body))
        lines.clear()

    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else _HEADING.match(line)
        if heading is None:
            lines.append(line)
            continue
        close()
        level = len(heading.group(1))
        path = [(lvl, title) for lvl, title in path if lvl < level]
        path.append((level, heading.group(2)))
    close()
    return sections


def _units(body: str, budget: int) -> list[tuple[str, bool]]:
    """The pieces to pack, each with whether it starts a paragraph."""
    units: list[tuple[str, bool]] = []
    for paragraph in _PARAGRAPH_BREAK.split(body):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if count_tokens(paragraph) <= budget:
            units.append((paragraph, True))
            continue
        first = True
        for sentence in _SENTENCE_END.split(paragraph):
            for piece in _fitted(sentence.strip(), budget):
                units.append((piece, first))
                first = False
    return units


def _fitted(sentence: str, budget: int) -> list[str]:
    """*sentence*, or its words packed under *budget*, a word too long cut into pieces."""
    if count_tokens(sentence) <= budget:
        return [sentence] if sentence else []
    pieces: list[str] = []
    current: list[str] = []
    for word in sentence.split():
        if count_tokens(word) > budget:
            if current:
                pieces.append(" ".join(current))
                current = []
            width = budget * _CHARS_PER_TOKEN
            pieces.extend(word[i : i + width] for i in range(0, len(word), width))
            continue
        if current and count_tokens(" ".join([*current, word])) > budget:
            pieces.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _joined(units: list[tuple[str, bool]]) -> str:
    text = ""
    for unit, starts_paragraph in units:
        if text:
            text += "\n\n" if starts_paragraph else " "
        text += unit
    return text


def _packed(units: list[tuple[str, bool]], budget: int, overlap: int) -> list[str]:
    packed: list[str] = []
    current: list[tuple[str, bool]] = []
    for unit in units:
        if current and count_tokens(_joined([*current, unit])) > budget:
            packed.append(_joined(current))
            current = _tail(current, overlap)
            while current and count_tokens(_joined([*current, unit])) > budget:
                current = current[1:]
        current.append(unit)
    if current:
        packed.append(_joined(current))
    return packed


def _tail(units: list[tuple[str, bool]], overlap: int) -> list[tuple[str, bool]]:
    """The last units of a chunk that fit in *overlap* tokens, carried into the next."""
    tail: list[tuple[str, bool]] = []
    for unit in reversed(units):
        if count_tokens(_joined([unit, *tail])) > overlap:
            break
        tail.insert(0, unit)
    return tail
