"""One entry of ``context_scope.seed``: a file for every record, or a file chosen per record.

The string form names one file. The mapping form names a staged record field
(``select_by: source.<field>``) and one file per value of that field
(``files: {value: path}``). The record's own value picks its file.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agent_actions.errors import ConfigurationError

_SELECTOR = re.compile(r"^source\.([A-Za-z_][A-Za-z0-9_]*)$")
_FILE_PREFIX = "$file:"
_ENTRY_KEYS = frozenset({"select_by", "files"})


class SeedSelectionError(ValueError):
    """A record gives no usable value for the field a seed entry selects by."""


def strip_file_prefix(file_spec: str) -> str:
    return file_spec[len(_FILE_PREFIX) :] if file_spec.startswith(_FILE_PREFIX) else file_spec


@dataclass(frozen=True)
class SeedEntry:
    key: str
    file_spec: str | None = None
    select_by: str | None = None
    files: Mapping[str, str] = field(default_factory=dict)

    @property
    def selected(self) -> bool:
        return self.select_by is not None

    @property
    def field_name(self) -> str | None:
        return self.select_by.split(".", 1)[1] if self.select_by else None

    def file_specs(self) -> list[str]:
        if self.file_spec is not None:
            return [self.file_spec]
        return list(dict.fromkeys(self.files.values()))

    def file_for(self, source: Mapping[str, Any] | None, action_name: str) -> str:
        """The file this record gets; a missing, unknown or wrong-type value is refused."""
        field_name = self.field_name
        if field_name is None:
            if self.file_spec is None:
                raise ConfigurationError(f"Seed '{self.key}' names no file.")
            return self.file_spec
        head = f"Seed '{self.key}' in action '{action_name}': "
        known = ", ".join(self.files)
        value = source.get(field_name) if isinstance(source, Mapping) else None
        if value is None:
            raise SeedSelectionError(
                f"{head}record has no value for '{self.select_by}'. Known values: {known}."
            )
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise SeedSelectionError(
                f"{head}value for '{self.select_by}' must be a string or an integer, "
                f"got {type(value).__name__}."
            )
        try:
            return self.files[str(value)]
        except KeyError:
            raise SeedSelectionError(
                f"{head}record value '{value}' for '{self.select_by}' is not in the file map. "
                f"Known values: {known}."
            ) from None


def parse_seed_entry(key: str, raw: Any, action_name: str) -> SeedEntry:
    head = f"Seed '{key}' in action '{action_name}': "
    if isinstance(raw, str):
        return SeedEntry(key=key, file_spec=raw)
    if not isinstance(raw, Mapping):
        raise ConfigurationError(
            f"{head}expected a file path or a mapping with 'select_by' and 'files', "
            f"got {type(raw).__name__}."
        )
    unknown = sorted(str(k) for k in raw if k not in _ENTRY_KEYS)
    if unknown:
        raise ConfigurationError(
            f"{head}unknown key{'s' if len(unknown) > 1 else ''} "
            f"{', '.join(repr(k) for k in unknown)}. Allowed keys: files, select_by."
        )
    if not _ENTRY_KEYS <= set(raw):
        raise ConfigurationError(f"{head}mapping needs both 'select_by' and 'files'.")
    select_by = raw["select_by"]
    if not isinstance(select_by, str) or not _SELECTOR.match(select_by):
        raise ConfigurationError(f"{head}'select_by' must be 'source.<field>', got {select_by!r}.")
    files = raw["files"]
    if not isinstance(files, Mapping) or not files:
        raise ConfigurationError(f"{head}'files' must be a non-empty map of value to file path.")
    by_value: dict[str, str] = {}
    for value, file_spec in files.items():
        if isinstance(value, bool) or not isinstance(value, str | int):
            raise ConfigurationError(f"{head}'files' key {value!r} must be a string or an integer.")
        if not isinstance(file_spec, str):
            raise ConfigurationError(
                f"{head}file for value '{value}' must be a file path, "
                f"got {type(file_spec).__name__}."
            )
        by_value[str(value)] = file_spec
    return SeedEntry(key=key, select_by=select_by, files=by_value)


def selected_seed_entries(
    action_configs: Mapping[str, Mapping[str, Any]],
) -> list[tuple[str, SeedEntry]]:
    """Every selected seed entry in the workflow, once per distinct map, with the first action that declares it."""
    seen: set[tuple[Any, ...]] = set()
    entries: list[tuple[str, SeedEntry]] = []
    for action_name, config in action_configs.items():
        context_scope = config.get("context_scope") or {}
        seed = context_scope.get("seed") if isinstance(context_scope, Mapping) else None
        if not isinstance(seed, Mapping):
            continue
        for key, raw in seed.items():
            entry = parse_seed_entry(key, raw, action_name)
            if not entry.selected:
                continue
            identity = (key, entry.select_by, tuple(entry.files.items()))
            if identity in seen:
                continue
            seen.add(identity)
            entries.append((action_name, entry))
    return entries
