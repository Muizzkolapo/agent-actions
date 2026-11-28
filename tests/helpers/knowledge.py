"""A stand-in for the knowledge base API, which the retrieve step calls."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_actions.errors import ConfigurationError
from agent_actions.knowledge import api as real_api
from agent_actions.knowledge.methods import INDEX_FOR_METHOD, METHODS

API_MODULE = "agent_actions.knowledge.api"


@dataclass
class FakeBase:
    name: str
    index: list[str] = field(default_factory=lambda: ["keyword"])
    metadata_fields: set[str] = field(default_factory=set)
    has_key: bool = False


@dataclass
class FakeKnowledge:
    """The bases the fake declares, what it returns, and each call it was given."""

    bases: dict[str, FakeBase]
    digest: str = "digest-1"
    hash: str | None = "digest-1"
    result: dict[str, Any] = field(
        default_factory=lambda: {"matches": [], "count": 0, "query": "", "index": "digest-1"}
    )
    ensured: list[tuple[Path, str, set[str], bool]] = field(default_factory=list)
    hashed: list[tuple[Path, str, set[str], bool]] = field(default_factory=list)
    searched: list[dict[str, Any]] = field(default_factory=list)


class KnowledgeConfigError(ConfigurationError):
    pass


def install_fake_knowledge(monkeypatch: Any, *bases: FakeBase) -> FakeKnowledge:
    """Put a fake ``agent_actions.knowledge.api`` in place for the test."""
    fake = FakeKnowledge(bases={base.name: base for base in bases})
    module = types.ModuleType(API_MODULE)
    # The real names, so the fake cannot drift from the methods the load checks against.
    module.KNOWN_METHODS = frozenset(METHODS)  # type: ignore[attr-defined]
    module.INDEX_FOR_METHOD = dict(INDEX_FOR_METHOD)  # type: ignore[attr-defined]
    module.KnowledgeConfigError = KnowledgeConfigError  # type: ignore[attr-defined]

    def load_knowledge_config(project_root: Path) -> dict[str, FakeBase]:
        return dict(fake.bases)

    def knowledge_hash(project_root: Path, base: str, indexes: set[str], *, sandbox: bool):
        fake.hashed.append((project_root, base, set(indexes), sandbox))
        return fake.hash

    def ensure_indexes(project_root: Path, base: str, indexes: set[str], *, sandbox: bool):
        fake.ensured.append((project_root, base, set(indexes), sandbox))
        return fake.digest

    def retrieve(project_root: Path, **kwargs: Any) -> dict[str, Any]:
        fake.searched.append({"project_root": project_root, **kwargs})
        return dict(fake.result)

    module.load_knowledge_config = load_knowledge_config  # type: ignore[attr-defined]
    module.knowledge_hash = knowledge_hash  # type: ignore[attr-defined]
    module.ensure_indexes = ensure_indexes  # type: ignore[attr-defined]
    module.retrieve = retrieve  # type: ignore[attr-defined]
    # A search of an earlier action's records reads no knowledge base: the real functions.
    for name in ("index_action_corpus", "action_corpus_change", "retrieve_from_corpus"):
        setattr(module, name, getattr(real_api, name))
    monkeypatch.setitem(sys.modules, API_MODULE, module)
    return fake
