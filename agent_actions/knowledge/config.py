"""The ``knowledge:`` section of ``agent_actions.yml``: named bases a retrieve entry searches."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from agent_actions.config.schema import ChunkConfig
from agent_actions.errors import ConfigurationError

KNOWLEDGE_KEY = "knowledge"
INDEXES = ("keyword", "fuzzy")
DEFAULT_INDEX = ["keyword"]
TEXT_TYPES = frozenset({".md", ".markdown", ".txt", ".html", ".htm", ".pdf", ".docx"})
RECORD_TYPES = frozenset({".json", ".jsonl", ".csv"})
FILE_TYPES = TEXT_TYPES | RECORD_TYPES
DEFAULT_SPLIT_METHOD = "markdown"
DEFAULT_CHUNK_SIZE = 200
DEFAULT_CHUNK_OVERLAP = 0
MAX_FILE_BYTES = 10 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")


def _field_list(value: Any) -> Any:
    return [value] if isinstance(value, str) else value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class StructuredSource(_Strict):
    """A JSON, JSONL or CSV file whose records are one chunk each."""

    path: str = Field(min_length=1)
    text: list[str] = Field(min_length=1)
    title: str | None = None
    id: str | None = None
    metadata: list[str] | None = None

    _fields = field_validator("text", "metadata", mode="before")(_field_list)

    @field_validator("path")
    @classmethod
    def _record_file(cls, path: str) -> str:
        if Path(path).suffix.lower() not in RECORD_TYPES:
            raise ValueError(
                f"path '{path}' must name .json, .jsonl or .csv files: text, title, id and "
                "metadata name the fields of their records"
            )
        return path


class DatabaseSource(_Strict):
    """The rows of one query through a connection of ``connections:``, one chunk each."""

    connection: str = Field(min_length=1)
    sql: str = Field(min_length=1)
    text: list[str] = Field(min_length=1)
    title: str | None = None
    id: str
    metadata: list[str] | None = None

    _fields = field_validator("text", "metadata", mode="before")(_field_list)

    @model_validator(mode="before")
    @classmethod
    def _needs_id(cls, data: Any) -> Any:
        if isinstance(data, dict) and "id" not in data:
            raise ValueError(
                "a database source needs 'id:': the column that names each row, so a "
                "match can be cited"
            )
        return data

    @field_validator("sql")
    @classmethod
    def _reads_only(cls, sql: str) -> str:
        from agent_actions.input.loaders.database_source import refuse_a_statement_that_writes

        try:
            refuse_a_statement_that_writes(sql)
        except ConfigurationError as e:
            raise ValueError(str(e).replace("database data source", "database source")) from None
        return sql


Source = str | StructuredSource | DatabaseSource


class KnowledgeBase(_Strict):
    # Set by the load from the key under ``knowledge:``, never written in the base.
    name: str = ""
    sources: list[Source] = Field(min_length=1)
    index: list[str] = Field(default_factory=lambda: list(DEFAULT_INDEX), min_length=1)
    chunk_config: ChunkConfig | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_written_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and "name" in data:
            raise ValueError("a base takes its name from its key under 'knowledge:'; remove 'name'")
        return data

    @property
    def metadata_fields(self) -> set[str]:
        """The fields a ``where:`` may name: the ``metadata:`` of each record source."""
        fields: set[str] = set()
        for source in self.sources:
            if not isinstance(source, str) and source.metadata:
                fields.update(source.metadata)
        return fields

    @property
    def has_key(self) -> bool:
        """Whether ``method: key`` can find a chunk: every source names its records' ids."""
        return all(not isinstance(s, str) and s.id is not None for s in self.sources)

    @field_validator("sources", mode="before")
    @classmethod
    def _typed_sources(cls, sources: Any) -> Any:
        if not isinstance(sources, list):
            return sources
        typed: list[Any] = []
        for number, source in enumerate(sources, 1):
            if isinstance(source, str):
                typed.append(_file_glob(source, number))
            elif isinstance(source, dict) and "connection" in source:
                typed.append(_validated(DatabaseSource, source, number))
            elif isinstance(source, dict) and "path" in source:
                typed.append(_validated(StructuredSource, source, number))
            else:
                raise ValueError(
                    f"source {number} must be a file glob, a mapping with 'path:' (records of "
                    "a JSON, JSONL or CSV file) or a mapping with 'connection:' and 'sql:'"
                )
        return typed

    @field_validator("index")
    @classmethod
    def _known_indexes(cls, index: list[str]) -> list[str]:
        for kind in index:
            if kind == "vector":
                raise ValueError("index 'vector' comes in a later version; use keyword or fuzzy")
            if kind not in INDEXES:
                raise ValueError(f"index '{kind}' is unknown; the indexes are {', '.join(INDEXES)}")
        if len(set(index)) != len(index):
            raise ValueError("index lists a kind twice")
        return index

    @field_validator("chunk_config", mode="before")
    @classmethod
    def _chunk_config(cls, value: Any) -> Any:
        if isinstance(value, dict) and "field" in value:
            raise ValueError(
                "chunk_config.field splits a staged record; a knowledge base splits its own "
                "files, so it takes no 'field'"
            )
        return value

    @model_validator(mode="after")
    def _overlap_at_most_half(self) -> KnowledgeBase:
        _, size, overlap, _ = self.chunk_settings()
        if overlap * 2 > size:
            raise ValueError(
                f"chunk_config.chunk_overlap ({overlap}) must be at most half of chunk_size "
                f"({size})"
            )
        return self

    def chunk_settings(self) -> tuple[str, int, int, str | None]:
        """The split method, chunk size, overlap and tokenizer, with the knowledge defaults."""
        config = self.chunk_config or ChunkConfig()
        return (
            config.split_method or DEFAULT_SPLIT_METHOD,
            config.chunk_size or DEFAULT_CHUNK_SIZE,
            DEFAULT_CHUNK_OVERLAP if config.chunk_overlap is None else config.chunk_overlap,
            config.tokenizer_model,
        )


def _file_glob(source: str, number: int) -> str:
    suffix = Path(source).suffix.lower()
    if suffix not in FILE_TYPES:
        raise ValueError(
            f"source {number} '{source}' must end in a file type a base reads: "
            f"{', '.join(sorted(FILE_TYPES))}"
        )
    return source


def _validated(model: type[BaseModel], source: dict[str, Any], number: int) -> BaseModel:
    try:
        return model.model_validate(source)
    except ValidationError as e:
        raise ValueError(f"source {number}: {_problems(e)}") from None


def _problems(error: ValidationError) -> str:
    problems = []
    for item in error.errors():
        place = ".".join(str(part) for part in item["loc"])
        message = str(item["msg"]).removeprefix("Value error, ")
        problems.append(f"{place}: {message}" if place else message)
    return "; ".join(problems)


def parse_knowledge(raw: Any) -> dict[str, KnowledgeBase]:
    """Each base of a ``knowledge:`` value, validated; raises ConfigurationError naming it."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigurationError(
            "agent_actions.yml: 'knowledge:' must map each knowledge base name to its sources"
        )
    bases: dict[str, KnowledgeBase] = {}
    for name, value in raw.items():
        if not isinstance(name, str) or not _NAME.match(name):
            raise ConfigurationError(
                f"agent_actions.yml: knowledge base name {name!r} must start with a letter and "
                "hold only letters, digits and '_'",
                context={"knowledge_base": str(name)},
            )
        try:
            bases[name] = KnowledgeBase.model_validate(value).model_copy(update={"name": name})
        except ValidationError as e:
            raise ConfigurationError(
                f"agent_actions.yml: knowledge base '{name}': {_problems(e)}",
                context={"knowledge_base": name},
            ) from None
    return bases


def load_knowledge(project_root: Path) -> dict[str, KnowledgeBase]:
    from agent_actions.config.path_config import load_project_config

    return parse_knowledge(load_project_config(project_root).get(KNOWLEDGE_KEY))


def unknown_base_message(name: str, bases: dict[str, KnowledgeBase]) -> str:
    """The refusal of a base name agent_actions.yml does not declare, with a suggestion."""
    import difflib

    near = difflib.get_close_matches(name, list(bases), n=1)
    hint = f" Did you mean '{near[0]}'?" if near else ""
    known = ", ".join(sorted(bases)) or "none"
    return (
        f"No knowledge base named '{name}' in agent_actions.yml.{hint} "
        f"Knowledge bases: {known}"
    )
