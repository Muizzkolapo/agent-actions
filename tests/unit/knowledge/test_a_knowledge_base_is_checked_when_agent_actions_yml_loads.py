"""`knowledge:` in agent_actions.yml is typed: an unknown key or a bad value is refused by name."""

from __future__ import annotations

import pytest

from agent_actions.errors import ConfigurationError
from agent_actions.knowledge.config import parse_knowledge


def _refused(raw) -> str:
    with pytest.raises(ConfigurationError) as caught:
        parse_knowledge(raw)
    return str(caught.value)


def test_a_base_of_files_takes_the_knowledge_defaults():
    bases = parse_knowledge({"help": {"sources": ["knowledge/help/*.md"]}})

    assert bases["help"].index == ["keyword"]
    assert bases["help"].chunk_settings() == ("markdown", 200, 0, None)


def test_each_source_form_is_read():
    bases = parse_knowledge(
        {
            "help": {
                "sources": [
                    "kb/**/*.md",
                    {"path": "seed_data/faq.json", "text": ["q", "a"], "title": "q", "id": "n"},
                    {
                        "connection": "warehouse",
                        "sql": "SELECT id, body FROM articles",
                        "text": "body",
                        "id": "id",
                        "metadata": ["product"],
                    },
                ],
                "index": ["keyword", "fuzzy"],
            }
        }
    )

    sources = bases["help"].sources
    assert sources[0] == "kb/**/*.md"
    assert sources[2].text == ["body"]
    assert bases["help"].name == "help"
    assert bases["help"].metadata_fields == {"product"}
    assert not bases["help"].has_key


def test_key_is_usable_only_when_every_source_names_its_ids():
    bases = parse_knowledge(
        {
            "faq": {"sources": [{"path": "faq.json", "text": "a", "id": "n"}]},
            "mixed": {"sources": ["kb/*.md", {"path": "faq.json", "text": "a", "id": "n"}]},
            "no_id": {"sources": [{"path": "faq.json", "text": "a"}]},
        }
    )

    assert [b.has_key for b in bases.values()] == [True, False, False]
    assert bases["faq"].metadata_fields == set()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({"help": {"sources": ["a.md"], "search": "keyword"}}, "search"),
        ({"help": {"sources": []}}, "sources"),
        ({"help": {"sources": ["a.exe"]}}, "must end in a file type"),
        ({"help": {"sources": ["a.md"], "index": ["vector"]}}, "comes in a later version"),
        ({"help": {"sources": ["a.md"], "index": ["semantic"]}}, "index 'semantic' is unknown"),
        (
            {"help": {"sources": [{"connection": "w", "sql": "SELECT 1", "text": ["b"]}]}},
            "a database source needs 'id:'",
        ),
        (
            {
                "help": {
                    "sources": [
                        {"connection": "w", "sql": "DELETE FROM t", "text": "b", "id": "i"}
                    ]
                }
            },
            "must be a SELECT",
        ),
        ({"help": {"sources": [{"path": "notes.md", "text": "b"}]}}, ".json, .jsonl or .csv"),
        (
            {"help": {"sources": ["a.md"], "chunk_config": {"field": "source.text"}}},
            "takes no 'field'",
        ),
        (
            {
                "help": {
                    "sources": ["a.md"],
                    "chunk_config": {"chunk_size": 100, "chunk_overlap": 60},
                }
            },
            "at most half of chunk_size",
        ),
        ({"help": {"sources": ["a.md"], "chunk_config": {"overlap": 5}}}, "overlap"),
        ({"bad-name": {"sources": ["a.md"]}}, "must start with a letter"),
        ({"help": {"sources": ["a.md"], "name": "other"}}, "takes its name from its key"),
        (["help"], "must map each knowledge base name"),
    ],
)
def test_a_bad_base_is_refused_by_name(raw, message):
    assert message in _refused(raw)
