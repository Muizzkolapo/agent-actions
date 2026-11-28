"""`split_method: markdown` splits at headings, then paragraphs, then sentences.

Each chunk starts with its heading path, and the path counts toward ``chunk_size``. Text
with no heading is split by paragraphs and sentences. Tokens are counted offline.
"""

from __future__ import annotations

import pytest

from agent_actions.input.preprocessing.transformation.markdown_splitter import (
    count_tokens,
    split_markdown,
)
from agent_actions.input.preprocessing.transformation.string_transformer import Tokenizer

ARTICLE = """# Billing

Our plans are billed each month.

## Duplicate charges

If you see two charges, the second is a pending authorization. It drops off in three days.

## Invoices

Invoices are under Settings.

```
# not a heading
```
"""


def test_each_section_is_a_chunk_with_its_heading_path():
    chunks = split_markdown(ARTICLE, chunk_size=200, overlap=0)

    assert [c.title for c in chunks] == [
        "Billing",
        "Billing > Duplicate charges",
        "Billing > Invoices",
    ]
    assert chunks[1].text.startswith("Billing > Duplicate charges\n")
    assert "pending authorization" in chunks[1].text
    assert "# not a heading" in chunks[2].text


def test_a_long_section_is_packed_by_sentences_under_the_size_with_the_path_counted():
    body = " ".join(f"Sentence number {i} says a few words." for i in range(40))
    chunks = split_markdown(f"# Long\n\n{body}\n", chunk_size=40, overlap=0)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text.startswith("Long\n")
        assert count_tokens(chunk.text) <= 40
        # A chunk never ends in the middle of a sentence.
        assert chunk.text.rstrip().endswith(".")


def test_plain_text_is_split_by_paragraphs():
    text = "First paragraph here.\n\nSecond paragraph here.\n\nThird one."
    chunks = split_markdown(text, chunk_size=5, overlap=0)

    assert [c.title for c in chunks] == ["", "", ""]
    assert chunks[0].text == "First paragraph here."


def test_overlap_repeats_the_last_sentences_of_the_previous_chunk():
    body = " ".join(f"Point {i} is made here." for i in range(12))
    chunks = split_markdown(body, chunk_size=20, overlap=8)

    assert len(chunks) > 1
    last_sentence = chunks[0].text.split(". ")[-1].rstrip(".")
    assert last_sentence in chunks[1].text


def test_the_shared_splitter_takes_markdown_as_a_split_method():
    parts = Tokenizer.split_text_content(ARTICLE, 200, 0, split_method="markdown")

    assert parts[0] == "Billing\nOur plans are billed each month."


def test_the_offline_count_needs_no_tokenizer_download():
    assert count_tokens("") == 0
    assert count_tokens("Hello, world") == 3
    assert count_tokens("internationalization") == 4


@pytest.mark.parametrize(
    "word", ["!" * 200, "https://example.com/a/b/c?x=1&y=2#frag/" * 8, "a.b-c_d" * 40]
)
def test_a_long_punctuation_run_or_url_is_cut_under_the_size(word):
    chunks = split_markdown(f"# T\n\n{word}\n", chunk_size=20, overlap=0)

    assert all(count_tokens(c.text) <= 20 for c in chunks)
    assert "".join(c.body for c in chunks).replace(" ", "") == word


@pytest.mark.parametrize(
    ("heading", "title"),
    [("## Using C#", "Using C#"), ("## Using C# ##", "Using C#"), ("## Notes ###", "Notes")],
)
def test_a_heading_keeps_a_hash_that_ends_a_word(heading, title):
    assert split_markdown(f"{heading}\n\nText.", chunk_size=50, overlap=0)[0].title == title


@pytest.mark.parametrize("size", [1, 3])
def test_a_word_longer_than_the_size_still_makes_progress(size):
    chunks = split_markdown("supercalifragilistic word", chunk_size=size, overlap=0)

    assert "".join(c.text for c in chunks).replace(" ", "") == "supercalifragilisticword"
