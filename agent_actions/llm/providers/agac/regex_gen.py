"""Strings that a regular expression matches, for a bounded subset of the syntax.

The subset: literals and escaped characters, ``.``, ``\\d \\w \\s`` and their negations,
``[...]`` with ranges and negation, the quantifiers ``? * + {m} {m,} {m,n} {,n}``,
groups ``( )``, ``(?: )`` and ``(?P<name> )``, alternation ``|`` and the anchors ``^ $``.
A pattern outside it raises :class:`UnsupportedPattern`, as does one that Python refuses,
one nested too deep, or a repeat count above ``MAX_REPEAT``. The caller checks each result
with :mod:`re`, because a pattern inside the subset can still match nothing.
"""

from __future__ import annotations

import functools
import random
import re
import string
from typing import Any

# Repeats an unbounded quantifier may add above its minimum.
UNBOUNDED_EXTRA = 3
# The largest count a braced repeat may name.
MAX_REPEAT = 1000

_DIGITS = string.digits
_WORD = string.ascii_letters + string.digits + "_"
_WHITESPACE = " \t\n\r\f\v"
_PRINTABLE = string.ascii_letters + string.digits + string.punctuation + " "
_ANY = string.ascii_letters + string.digits
_CONTROL_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "f": "\f", "v": "\v", "0": "\0"}

# A node is ("chars", pool), ("cat", [nodes]), ("alt", [nodes]) or ("rep", node, low, high).
Node = tuple[Any, ...]


class UnsupportedPattern(ValueError):
    """The pattern uses syntax outside the subset this module generates from."""


def generate(pattern: str, rng: random.Random) -> str:
    """One string built from *pattern*, drawn with *rng*."""
    node = _parsed(pattern)
    if isinstance(node, UnsupportedPattern):
        raise UnsupportedPattern(str(node))
    return _render(node, rng)


@functools.lru_cache(maxsize=256)
def _parsed(pattern: str) -> Node | UnsupportedPattern:
    """The tree of *pattern*, or why it is refused; kept, because a mock asks many times."""
    try:
        # What Python refuses is refused here too, so the parser reads only valid syntax.
        re.compile(pattern)
        return _Parser(pattern).parse()
    except UnsupportedPattern as e:
        return e
    except re.error as e:
        return UnsupportedPattern(f"Python refuses the pattern: {e}")
    except RecursionError:
        return UnsupportedPattern("the pattern is nested too deep")


def _complement(chars: str) -> str:
    return "".join(c for c in _PRINTABLE if c not in chars)


_CLASS_ESCAPES = {
    "d": _DIGITS,
    "w": _WORD,
    "s": " ",
    "D": _complement(_DIGITS),
    "W": _complement(_WORD),
    "S": _complement(_WHITESPACE),
}
# What a class escape adds inside [...], where \s must match every whitespace character.
_SET_ESCAPES = {**_CLASS_ESCAPES, "s": _WHITESPACE}


class _Parser:
    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self.pos = 0

    def parse(self) -> Node:
        node = self._alternation()
        if self.pos < len(self.pattern):
            raise UnsupportedPattern(f"unbalanced ')' at {self.pos}")
        return node

    def _peek(self) -> str | None:
        return self.pattern[self.pos] if self.pos < len(self.pattern) else None

    def _next(self) -> str:
        if self.pos >= len(self.pattern):
            raise UnsupportedPattern("pattern ends early")
        char = self.pattern[self.pos]
        self.pos += 1
        return char

    def _alternation(self) -> Node:
        branches = [self._concatenation()]
        while self._peek() == "|":
            self.pos += 1
            branches.append(self._concatenation())
        return branches[0] if len(branches) == 1 else ("alt", branches)

    def _concatenation(self) -> Node:
        items: list[Node] = []
        while self._peek() not in (None, "|", ")"):
            atom = self._atom()
            if atom is None:
                if self._quantifier() is not None:
                    raise UnsupportedPattern("a quantifier follows an anchor")
                continue
            quantifier = self._quantifier()
            items.append(atom if quantifier is None else ("rep", atom, *quantifier))
        return ("cat", items)

    def _atom(self) -> Node | None:
        char = self._next()
        if char in "^$":
            return None
        if char == ".":
            return ("chars", _ANY)
        if char == "\\":
            return ("chars", self._escape(_CLASS_ESCAPES))
        if char == "[":
            return ("chars", self._set())
        if char == "(":
            return self._group()
        if char in "*+?":
            raise UnsupportedPattern(f"nothing to repeat at {self.pos - 1}")
        return ("chars", char)

    def _escape(self, classes: dict[str, str]) -> str:
        char = self._next()
        if char in classes:
            return classes[char]
        if char in _CONTROL_ESCAPES:
            return _CONTROL_ESCAPES[char]
        if char.isalnum():
            raise UnsupportedPattern(f"escape '\\{char}' is outside the subset")
        return char

    def _set(self) -> str:
        negated = self._peek() == "^"
        if negated:
            self.pos += 1
        members: list[str] = []
        first = True
        while True:
            char = self._next()
            if char == "]" and not first:
                break
            first = False
            if char == "\\":
                char = self._escape(_SET_ESCAPES)
                if len(char) != 1:
                    members.append(char)
                    continue
            if self._peek() == "-" and self.pos + 1 < len(self.pattern):
                end = self.pattern[self.pos + 1]
                if end != "]":
                    self.pos += 2
                    if end == "\\":
                        end = self._escape({})
                    if ord(end) < ord(char):
                        raise UnsupportedPattern(f"bad range {char}-{end}")
                    members.append("".join(chr(c) for c in range(ord(char), ord(end) + 1)))
                    continue
            members.append(char)
        chars = "".join(dict.fromkeys("".join(members)))
        pool = _complement(chars) if negated else chars
        if not pool:
            raise UnsupportedPattern("a character set with nothing to choose")
        return pool

    def _group(self) -> Node:
        if self._peek() == "?":
            self.pos += 1
            kind = self._next()
            if kind == "P" and self._peek() == "<":
                end = self.pattern.find(">", self.pos)
                if end < 0:
                    raise UnsupportedPattern("unterminated group name")
                self.pos = end + 1
            elif kind != ":":
                raise UnsupportedPattern(f"group '(?{kind}' is outside the subset")
        node = self._alternation()
        if self._next() != ")":
            raise UnsupportedPattern("unterminated group")
        return node

    def _quantifier(self) -> tuple[int, int] | None:
        char = self._peek()
        if char == "?":
            bounds = (0, 1)
            self.pos += 1
        elif char == "*":
            bounds = (0, UNBOUNDED_EXTRA)
            self.pos += 1
        elif char == "+":
            bounds = (1, 1 + UNBOUNDED_EXTRA)
            self.pos += 1
        elif char == "{":
            braced = self._braces()
            if braced is None:
                return None
            bounds = braced
        else:
            return None
        # A lazy or possessive mark changes how a match is found, not what matches.
        if self._peek() in ("?", "+"):
            self.pos += 1
        return bounds

    def _braces(self) -> tuple[int, int] | None:
        """``{m}``, ``{m,}``, ``{m,n}`` or ``{,n}``; None when the brace is a literal."""
        end = self.pattern.find("}", self.pos)
        if end < 0:
            return None
        low_text, comma, high_text = self.pattern[self.pos + 1 : end].partition(",")
        if not (low_text.isdigit() or (comma and not low_text)):
            return None
        if high_text and not high_text.isdigit():
            return None
        if any(int(count) > MAX_REPEAT for count in (low_text, high_text) if count):
            raise UnsupportedPattern(f"a repeat count above {MAX_REPEAT}")
        low = int(low_text) if low_text else 0
        if not comma:
            high = low
        elif high_text:
            high = int(high_text)
        else:
            high = low + UNBOUNDED_EXTRA
        if high < low:
            raise UnsupportedPattern("a repeat whose maximum is below its minimum")
        self.pos = end + 1
        return low, high


def _render(node: Node, rng: random.Random) -> str:
    kind = node[0]
    if kind == "chars":
        return str(rng.choice(node[1]))
    if kind == "cat":
        return "".join(_render(item, rng) for item in node[1])
    if kind == "alt":
        return _render(rng.choice(node[1]), rng)
    _, inner, low, high = node
    return "".join(_render(inner, rng) for _ in range(rng.randint(low, high)))
