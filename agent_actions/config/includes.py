"""Expand the include entries of a workflow into the actions of shared branch files."""

from __future__ import annotations

import copy
import difflib
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import TemplateSyntaxError
from pydantic import BaseModel, ValidationError

from agent_actions.config.path_config import load_project_config, resolve_project_root
from agent_actions.config.paths import PathType
from agent_actions.config.schema import (
    ActionConfig,
    DefaultsConfig,
    WorkflowConfig,
    dump_defaults,
    version_variant_names,
)
from agent_actions.errors import ConfigurationError, ConfigValidationError
from agent_actions.errors.base import enrich_exception_context
from agent_actions.input.context.normalizer import DIRECTIVE_REGISTRY, normalize_context_scope
from agent_actions.output.response.expander_merge import (
    adapt_inherited_expect,
    collect_judge_context_refs,
    inherited_context_scope,
    layered_defaults,
    merge_expect,
)
from agent_actions.output.response.expander_validation import (
    inherited_routing_kind,
    resolved_granularity,
)

INCLUDE_KEYS = ("include", "inputs", "defaults", "override", "remove")
BRANCH_KEYS = ("branch", "description", "inputs", "outputs", "actions")
_NOT_YET_INCLUDE_KEYS = frozenset({"as"})
_WORKFLOW_ONLY_DEFAULTS = ("data_source",)
_REQUIRED_BRANCH_KEYS = ("branch", "description", "actions")
_JINJA_MARKERS = ("{{", "{%", "{#")
_NAME_CHARS = re.compile(r"[A-Za-z0-9_]+\Z")
_NAME_RULE = "Use letters, digits and single underscores, starting with a letter."
_ORIGIN_KEY = "_include"
_OVERRIDE_KEYS = tuple(
    sorted(
        (
            {field.alias or name for name, field in ActionConfig.model_fields.items()}
            - {"name", _ORIGIN_KEY, "_version_context"}
        )
        | {"schema_name"}
    )
)
# One key spelt two ways: the render step reads ``schema_name`` over ``schema``.
_SCHEMA_SPELLINGS = ("schema", "schema_name")


@dataclass(frozen=True)
class Branch:
    """A parsed and validated branch file."""

    name: str
    file: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    actions: tuple[dict[str, Any], ...]

    @property
    def label(self) -> str:
        return f"branch '{self.name}' ({self.file})"


@dataclass(frozen=True)
class Inclusion:
    """One include entry of a workflow, bound to its branch.

    *actions* are the branch actions after the entry's override and removal.
    """

    branch: Branch
    instance: str
    bindings: Mapping[str, str]
    workflow_file: str
    actions: tuple[dict[str, Any], ...]
    removed: tuple[str, ...] = ()
    defaults: Mapping[str, Any] | None = None

    @property
    def outputs(self) -> tuple[str, ...]:
        return tuple(name for name in self.branch.outputs if name not in self.removed)

    def removed_names(self) -> dict[str, str]:
        """Each name a reference to a removed action can use, mapped to that action."""
        names: dict[str, str] = {}
        for action in self.branch.actions:
            if action["name"] in self.removed:
                for name in _final_and_base_names(action):
                    names[name] = action["name"]
        return names


def branch_file(name: str) -> str:
    """The branch file of *name*, relative to the project root."""
    return f"{PathType.BRANCHES.value}/{name}.yml"


def _branch_where(name: str, workflow_file: str, action: str | None = None) -> str:
    """How a refusal about branch file *name* begins; *action* is quoted or a position."""
    where = f"Branch '{name}' ({branch_file(name)}), included in {workflow_file}"
    return where if action is None else f"{where}, action {action}"


def expand_includes(
    data: Any, workflow_path: str | Path, project_root: Path | None = None
) -> tuple[Any, list[Inclusion]]:
    """Read the branch files *data* includes, then expand them into *data*'s actions.

    A refusal carries the workflow file under ``file_path``, so the CLI shows it.
    """
    if not isinstance(data, dict) or not isinstance(data.get("actions"), list):
        return data, []
    root = resolve_project_root(project_root)
    workflow_file = _workflow_label(Path(workflow_path), root)
    try:
        sources: dict[str, Any] = {}
        available: list[str] = []
        if has_include(data):
            folder = root / PathType.BRANCHES.value
            if folder.is_dir():
                available = sorted(path.stem for path in folder.glob("*.yml"))
            for name in _included_names(data):
                if name in available:
                    sources[name] = _read_branch_file(folder, name, workflow_file)
        return expand_workflow_includes(data, workflow_file, sources, available)
    except ConfigurationError as e:
        enrich_exception_context(e, file_path=workflow_file)
        raise


def expand_workflow_includes(
    data: Any,
    workflow_file: str,
    branches: Mapping[str, Any],
    available: Sequence[str],
) -> tuple[Any, list[Inclusion]]:
    """Replace each include entry of *data* with the actions of its branch, in place order.

    *branches* holds the parsed content of each included branch file that exists, and
    *available* names every branch file found. *data* is not changed.
    """
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(actions, list):
        return data, []
    _refuse_written_origin(actions, workflow_file)
    if not has_include(data):
        return data, []
    workflow = str(data.get("name"))
    parsed: dict[str, Branch] = {}
    inclusions: list[Inclusion] = []
    for entry in actions:
        if _is_include(entry):
            inclusions.append(_inclusion(entry, workflow_file, branches, available, parsed))
    _refuse_repeated_instances(inclusions, workflow, workflow_file)
    hosts = [entry for entry in actions if not _is_include(entry)]
    _refuse_name_collisions(hosts, inclusions, workflow, workflow_file)
    _refuse_bad_bindings(hosts, inclusions, workflow, workflow_file)

    expanded: list[Any] = []
    pending = iter(inclusions)
    for entry in actions:
        if _is_include(entry):
            inclusion = next(pending)
            expanded.extend(_with_origin(action, inclusion) for action in inclusion.actions)
        else:
            expanded.append(entry)
    return {**data, "actions": expanded}, inclusions


def check_include_reads(
    data: Any, inclusions: Sequence[Inclusion], project_root: Path | None = None
) -> None:
    """Refuse a host read of a branch action that is not an output, a branch read of
    anything outside the branch and its declared inputs, and a read of a removed action.

    What an action inherits from the defaults counts, computed by the steps the load
    takes. Defaults the load would refuse leave the workflow unchecked, and so does a
    malformed workflow: the validation after the render refuses it with the message it
    gives a workflow with no include. A read of a removed action leaves a dangling name,
    which fails that validation too, so the removal check runs first, on each action that
    validates alone.
    """
    if not inclusions:
        return
    workflow_file = inclusions[0].workflow_file
    try:
        levels = _Levels.load(data, project_root)
        if levels is None:
            return
        if any(inclusion.removed for inclusion in inclusions):
            _refuse_removed_reads(data, inclusions, levels)
        if _validates(data):
            _check_reads(data, inclusions, levels)
    except ConfigurationError as e:
        enrich_exception_context(e, file_path=workflow_file)
        raise


@dataclass(frozen=True)
class _Levels:
    """The defaults an action inherits, computed by the functions the load calls."""

    defaults: dict[str, Any]
    agent: dict[str, Any]
    workflow_scope: Any

    @classmethod
    def load(cls, data: dict[str, Any], project_root: Path | None) -> _Levels | None:
        """The levels of *data*; None when the load refuses its defaults or the project's."""
        from agent_actions.config.manager import (
            merge_workflow_defaults,
            project_action_defaults,
            project_agent_config,
        )

        project_config = load_project_config(resolve_project_root(project_root))
        written = data.get("defaults")
        try:
            workflow = dump_defaults(DefaultsConfig.model_validate(written or {}))
            defaults = merge_workflow_defaults(project_action_defaults(project_config), workflow)
            agent = project_agent_config(project_config)
        except (ValidationError, ConfigValidationError, ConfigurationError):
            return None
        scope = written.get("context_scope") if isinstance(written, dict) else None
        return cls(defaults=defaults, agent=agent, workflow_scope=scope)

    def of(self, action: dict[str, Any]) -> dict[str, Any]:
        """The defaults the expander gives *action*."""
        from agent_actions.output.response.expander import ActionExpander

        if not _mapping_or_none(self.defaults.get("context_scope")):
            return {key: value for key, value in self.defaults.items() if key != "context_scope"}
        return ActionExpander.defaults_for(action, self.defaults)

    def scope(self, action: dict[str, Any]) -> dict[str, list[Any]]:
        """The read directives of the ``context_scope`` the run gives *action*.

        Empty when a level is malformed: the load refuses it with its own message.
        """
        from agent_actions.config.manager import merge_over_agent_defaults

        inherited = inherited_context_scope(action, self.of(action))
        agent = merge_over_agent_defaults(
            self.agent, {} if inherited is None else {"context_scope": inherited}
        )
        return _normalised_reads(agent.get("context_scope")) or {}


def _mapping_or_none(value: Any) -> bool:
    return value is None or isinstance(value, dict)


def _normalised_reads(scope: Any) -> dict[str, list[Any]] | None:
    """The directives of *scope* that read an action, once normalised as the run does.

    Version base names are kept, which the boundary checks know. None when the
    normaliser refuses *scope*; a ``seed`` reads nothing.
    """
    try:
        normalised = normalize_context_scope(scope, {})
    except ConfigurationError:
        return None
    return {
        directive: refs
        for directive, refs in normalised.items()
        if DIRECTIVE_REGISTRY[directive]["type"] == "list"
    }


def _validates(data: Any, model: type[BaseModel] = WorkflowConfig) -> bool:
    try:
        model.model_validate(data)
    except (ValidationError, ConfigValidationError):
        return False
    return True


def action_defaults(action: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """The defaults the expander gives *action*: its instance defaults over *defaults*."""
    origin = action.get(_ORIGIN_KEY)
    instance = origin.get("defaults") if isinstance(origin, dict) else None
    return layered_defaults(defaults, instance) if instance else defaults


def _repair_view(action: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """The kind and granularity the expander gives *action*, which decide if it can repair."""
    kind = inherited_routing_kind(action, defaults)
    return {"kind": kind, "granularity": resolved_granularity(kind, action, defaults)[0]}


def _check_reads(data: dict[str, Any], inclusions: Sequence[Inclusion], levels: _Levels) -> None:
    workflow_file = inclusions[0].workflow_file
    # Imported here: a large import that only a workflow with an include needs.
    from agent_actions.validation.static_analyzer.reference_extractor import ReferenceExtractor

    actions = [action for action in data["actions"] if isinstance(action, dict)]
    by_instance = {inclusion.instance: inclusion for inclusion in inclusions}
    owner: dict[str, Inclusion] = {}
    local: dict[str, str] = {}
    base_of: dict[str, str] = {}
    known: set[str] = set()
    for action in actions:
        names = _final_and_base_names(action)
        known.update(names)
        version = action.get("_version_context")
        if isinstance(version, dict) and isinstance(version.get("base_name"), str):
            base_of[action["name"]] = version["base_name"]
        origin = action.get(_ORIGIN_KEY)
        if isinstance(origin, dict):
            for name in names:
                owner[name] = by_instance[origin["instance"]]
                local[name] = origin["local_name"]

    extractor = ReferenceExtractor()
    for action in actions:
        origin = action.get(_ORIGIN_KEY)
        reader = by_instance[origin["instance"]] if isinstance(origin, dict) else None
        reader_local = origin["local_name"] if isinstance(origin, dict) else action["name"]
        for name in _reads(
            action, extractor, workflow_file, levels.of(action), levels.scope(action)
        ):
            if name not in known:
                continue
            source = owner.get(name)
            if reader is not None:
                inputs = reader.branch.inputs
                if source is reader or name in inputs or base_of.get(name) in inputs:
                    continue
                where = _branch_where(reader.branch.name, workflow_file, f"'{reader_local}'")
                via = _scope_origin(action, name, extractor, workflow_file, levels)
                raise ConfigurationError(
                    f"{where}: reads '{name}'{via}, which is not a branch action or a declared "
                    "input. Declare it under 'inputs:'.",
                    context=_context(reader, action_name=reader_local),
                )
            if source is not None and local[name] not in source.outputs:
                via = _scope_origin(action, name, extractor, workflow_file, levels)
                raise ConfigurationError(
                    f"Action '{action['name']}' in {workflow_file} reads '{name}'{via}, which "
                    f"{source.branch.label} does not list under outputs. "
                    f"Outputs of '{source.branch.name}': {_listed(source.outputs)}.",
                    context=_context(source, action_name=action["name"]),
                )


def _scope_origin(
    action: dict[str, Any],
    name: str,
    extractor: Any,
    workflow_file: str,
    levels: _Levels,
) -> str:
    """Which defaults level gives *action* its read of *name* through ``context_scope``.

    Empty when the action's own config reads it; else the most specific level whose
    ``context_scope`` reads it.
    """
    own = _normalised_reads(action.get("context_scope")) or {}
    if name in _reads(action, extractor, workflow_file, levels.of(action), own):
        return ""
    found = action.get(_ORIGIN_KEY)
    origin: dict[str, Any] = found if isinstance(found, dict) else {}
    instance = origin.get("defaults")
    instance_scope = instance.get("context_scope") if isinstance(instance, dict) else None
    if name in _scope_reads(instance_scope, extractor):
        level = f"'defaults:' of include '{origin['instance']}'"
    elif name in _scope_reads(levels.workflow_scope, extractor):
        level = "the workflow's 'defaults:'"
    else:
        level = "'default_agent_config:' in agent_actions.yml"
    return f" (from 'context_scope' under {level})"


def _scope_reads(scope: Any, extractor: Any) -> set[str]:
    reads = _normalised_reads(scope) or {}
    return {req.source_agent for req in extractor.extract_from_agent({"context_scope": reads})}


def _refuse_removed_reads(
    data: dict[str, Any], inclusions: Sequence[Inclusion], levels: _Levels
) -> None:
    """Refuse a read of an action that an include removes, naming every reader in its branch."""
    workflow_file = inclusions[0].workflow_file
    from agent_actions.validation.static_analyzer.reference_extractor import ReferenceExtractor

    actions = [action for action in data["actions"] if isinstance(action, dict)]
    known = {name for action in actions for name in _final_and_base_names(action)}
    removed = {
        name: (inclusion, local)
        for inclusion in inclusions
        for name, local in inclusion.removed_names().items()
        if name not in known
    }
    by_instance = {inclusion.instance: inclusion for inclusion in inclusions}
    readers: dict[tuple[str, str], dict[str, str]] = {}
    extractor = ReferenceExtractor()
    for action in actions:
        if not _validates(action, ActionConfig):
            continue
        origin = action.get(_ORIGIN_KEY)
        reader = by_instance[origin["instance"]] if isinstance(origin, dict) else None
        for name in _reads(
            action, extractor, workflow_file, levels.of(action), levels.scope(action)
        ):
            if name not in removed:
                continue
            source, local = removed[name]
            via = _scope_origin(action, name, extractor, workflow_file, levels)
            if reader is source:
                readers.setdefault((source.instance, local), {}).setdefault(action["name"], via)
                continue
            raise ConfigurationError(
                f"Action '{action['name']}' in {workflow_file} reads '{name}'{via}, which include "
                f"'{source.instance}' leaves out under 'remove:'. Outputs that include "
                f"'{source.instance}' keeps from {source.branch.label}: "
                f"{_listed(source.outputs)}.",
                context=_context(source, action_name=action["name"]),
            )
    for inclusion in inclusions:
        for local in inclusion.removed:
            found = readers.get((inclusion.instance, local), {})
            if not found:
                continue
            verb = "reads" if len(found) == 1 else "read"
            named = ", ".join(f"'{reader}'{via}" for reader, via in found.items())
            raise ConfigurationError(
                f"Include '{inclusion.instance}' in {workflow_file}: remove names '{local}' of "
                f"{inclusion.branch.label}, but {named} still {verb} it. "
                f"{_removal_advice(list(found.values()))}",
                context=_context(inclusion, action_name=local),
            )


def _removal_advice(levels: list[str]) -> str:
    """What to do about the readers of a removed action, by where each read comes from."""
    if not any(levels):
        return "Remove the readers too, or override them so that they do not read it."
    return (
        "Remove the readers too, or override their 'context_scope' so that they do not read "
        "it (a directive that the override sets, null included, replaces the inherited one), "
        "or remove the read from the defaults named above."
    )


def parse_branch(name: str, source: Any, workflow_file: str) -> Branch:
    """Validate the content of branch file *name*, which *workflow_file* includes."""
    file = branch_file(name)
    label = _branch_where(name, workflow_file)
    if not isinstance(source, dict):
        raise ConfigurationError(
            f"{label}: the file must hold a mapping with the keys {', '.join(BRANCH_KEYS)}.",
            context={"branch_file": file},
        )
    for key in source:
        if key not in BRANCH_KEYS:
            raise ConfigurationError(
                f"{label}: key '{key}' is not a branch key."
                f"{_near_miss(str(key), BRANCH_KEYS)} Branch keys: {', '.join(BRANCH_KEYS)}.",
                context={"branch_file": file, "key": key},
            )
    for key in _REQUIRED_BRANCH_KEYS:
        if key not in source:
            raise ConfigurationError(
                f"{label}: the file has no '{key}' key.", context={"branch_file": file}
            )
    if source["branch"] != name:
        raise ConfigurationError(
            f"{label}: the file has 'branch: {source['branch']}'. "
            f"The name must equal the file name '{name}'.",
            context={"branch_file": file},
        )
    if not isinstance(source["description"], str):
        raise ConfigurationError(f"{label}: 'description' must be text.")
    inputs = source.get("inputs") or {}
    if not isinstance(inputs, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in inputs.items()
    ):
        raise ConfigurationError(f"{label}: 'inputs' must map each input name to a description.")
    outputs = source.get("outputs") or []
    if not isinstance(outputs, list) or not all(isinstance(item, str) for item in outputs):
        raise ConfigurationError(f"{label}: 'outputs' must be a list of action names.")
    actions = source["actions"]
    if not isinstance(actions, list) or not actions:
        raise ConfigurationError(f"{label}: 'actions' must be a list of actions.")
    if any(_is_include(action) for action in actions):
        raise ConfigurationError(
            f"{label}: the branch contains an include. A branch cannot include another branch.",
            context={"branch_file": file},
        )

    names: list[str] = []
    for index, action in enumerate(actions, start=1):
        names.append(_checked_action(name, workflow_file, index, action))
    for action_name in names:
        if names.count(action_name) > 1:
            twice = _branch_where(name, workflow_file, f"'{action_name}'")
            raise ConfigurationError(
                f"{twice}: the branch defines this action twice.",
                context={"action_name": action_name},
            )
    for output in outputs:
        if output not in names:
            raise ConfigurationError(
                f"{label}: output '{output}' is not an action of the branch. "
                f"Branch actions: {_listed(names)}."
            )
    for input_name in inputs:
        if input_name in names:
            raise ConfigurationError(
                f"{label}: '{input_name}' is declared as an input and defined as an action."
            )
    return Branch(
        name=name,
        file=file,
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        actions=tuple(actions),
    )


def _checked_action(branch: str, workflow_file: str, index: int, action: Any) -> str:
    """Validate one branch action and return its name."""
    name = action.get("name") if isinstance(action, dict) else None
    where = _branch_where(
        branch, workflow_file, f"'{name}'" if isinstance(name, str) else str(index)
    )
    context = {"action_name": name}
    if not isinstance(action, dict):
        raise ConfigurationError(f"{where}: an action must be a mapping.", context=context)
    if _ORIGIN_KEY in action:
        raise ConfigurationError(
            f"{where}: '{_ORIGIN_KEY}' is set by the load on an included action and cannot "
            "be written in a branch file.",
            context=context,
        )
    try:
        name = ActionConfig.model_validate(_with_named_schema(action)).name
    except ValidationError as e:
        # The reason is in the message, and the CLI prints the innermost error.
        raise ConfigurationError(f"{where}: {_problems(e)}", context=context) from None
    reason = _name_problem(name)
    if reason:
        named = _branch_where(branch, workflow_file, f"'{name}'")
        raise ConfigurationError(
            f"{named}: the name {reason} {_NAME_RULE}",
            context={"action_name": name},
        )
    prompt = action.get("prompt")
    if isinstance(prompt, str) and not prompt.strip().startswith("$"):
        raise ConfigurationError(
            f"{where}: the prompt is written inline. A branch action names a prompt store "
            "block, for example 'prompt: $store.Block'.",
            context=context,
        )
    for key, value in action.items():
        if any(marker in text for text in _strings(value) for marker in _JINJA_MARKERS):
            raise ConfigurationError(
                f"{where}: '{key}' holds Jinja. A branch file is plain YAML and is not rendered.",
                context=context,
            )
    return name


def _problems(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
        if item["loc"]
        else item["msg"]
        for item in error.errors()
    )


def _with_named_schema(action: dict[str, Any]) -> dict[str, Any]:
    """*action* with ``schema_name`` read as ``schema``, as the render step reads it."""
    named = action.get("schema_name")
    if not isinstance(named, str) or not named:
        return action
    return {**{k: v for k, v in action.items() if k != "schema_name"}, "schema": named}


def _name_problem(name: str) -> str | None:
    if not name[:1].isascii() or not name[:1].isalpha():
        return "does not start with a letter."
    if not _NAME_CHARS.match(name):
        return "holds a character that is not a letter, a digit or '_'."
    if "__" in name:
        return "contains '__', which is reserved for instance names."
    if name.endswith("_"):
        return "ends with '_'."
    return None


def _inclusion(
    entry: dict[str, Any],
    workflow_file: str,
    branches: Mapping[str, Any],
    available: Sequence[str],
    parsed: dict[str, Branch],
) -> Inclusion:
    name = entry["include"]
    if not isinstance(name, str) or not name:
        raise ConfigurationError(
            f"Include in {workflow_file}: 'include' must name a branch, got {name!r}."
        )
    where = f"Include '{name}' in {workflow_file}"
    for key in entry:
        if key in INCLUDE_KEYS:
            continue
        accepted = f"Include keys: {', '.join(INCLUDE_KEYS)}."
        if key in _NOT_YET_INCLUDE_KEYS:
            raise ConfigurationError(f"{where}: key '{key}' is not supported yet. {accepted}")
        raise ConfigurationError(
            f"{where}: key '{key}' is not an include key."
            f"{_near_miss(str(key), INCLUDE_KEYS)} {accepted}"
        )
    if name not in branches:
        found = ", ".join(available) if available else "none"
        raise ConfigurationError(
            f"{where}: no branch file {branch_file(name)}. Branch files found: {found}.",
            context={"workflow_file": workflow_file, "branch": name},
        )
    if name not in parsed:
        parsed[name] = parse_branch(name, branches[name], workflow_file)
    branch = parsed[name]
    bindings = entry.get("inputs") or {}
    if not isinstance(bindings, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in bindings.items()
    ):
        raise ConfigurationError(f"{where}: 'inputs' must map each branch input to an action name.")
    override = _override(entry.get("override"), branch, where)
    removed = _removal(entry.get("remove"), branch, where)
    for action_name in override:
        if action_name in removed:
            raise ConfigurationError(
                f"{where}: '{action_name}' of {branch.label} is named under both 'override' "
                "and 'remove'. Override it or remove it.",
                context={"branch_file": branch.file, "action_name": action_name},
            )
    actions = tuple(
        _overridden(action, override[action["name"]], branch, where)
        if action["name"] in override
        else action
        for action in branch.actions
        if action["name"] not in removed
    )
    return Inclusion(
        branch=branch,
        instance=name,
        bindings=dict(bindings),
        workflow_file=workflow_file,
        actions=actions,
        removed=removed,
        defaults=_instance_defaults(entry.get("defaults"), where),
    )


def _override(override: Any, branch: Branch, where: str) -> dict[str, dict[str, Any]]:
    if override is None:
        return {}
    if not isinstance(override, dict) or not all(
        isinstance(key, str) and isinstance(value, dict) for key, value in override.items()
    ):
        raise ConfigurationError(
            f"{where}: 'override' must map each branch action to a mapping of action keys."
        )
    for action_name in override:
        _refuse_unknown_action(action_name, "override", branch, where)
    return override


def _removal(removed: Any, branch: Branch, where: str) -> tuple[str, ...]:
    if removed is None:
        return ()
    if not isinstance(removed, list) or not all(isinstance(item, str) for item in removed):
        raise ConfigurationError(f"{where}: 'remove' must be a list of branch action names.")
    for action_name in removed:
        _refuse_unknown_action(action_name, "remove", branch, where)
    return tuple(dict.fromkeys(removed))


def _refuse_unknown_action(action_name: str, key: str, branch: Branch, where: str) -> None:
    names = [action["name"] for action in branch.actions]
    if action_name not in names:
        raise ConfigurationError(
            f"{where}: {key} names '{action_name}', which {branch.label} does not define."
            f"{_near_miss(action_name, names)} Branch actions: {_listed(names)}.",
            context={"branch_file": branch.file, "action_name": action_name},
        )


def _overridden(
    action: dict[str, Any], keys: dict[str, Any], branch: Branch, where: str
) -> dict[str, Any]:
    """*action* with each key of *keys* replaced, and each key given ``null`` removed."""
    local = action["name"]
    where = f"{where}, override of '{local}' in {branch.label}"
    context = {"branch_file": branch.file, "action_name": local}
    for key in keys:
        if key == "name":
            raise ConfigurationError(
                f"{where}: key 'name' cannot be overridden. An included action keeps the name "
                "its branch gives it.",
                context=context,
            )
        if key not in _OVERRIDE_KEYS:
            raise ConfigurationError(
                f"{where}: key '{key}' is not an action field.{_near_miss(str(key), _OVERRIDE_KEYS)}",
                context=context,
            )
    merged = dict(action)
    for key, value in keys.items():
        if key in _SCHEMA_SPELLINGS:
            for spelling in _SCHEMA_SPELLINGS:
                merged.pop(spelling, None)
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = copy.deepcopy(value)
    try:
        ActionConfig.model_validate(_with_named_schema(merged))
    except ValidationError as e:
        raise ConfigurationError(f"{where}: {_problems(e)}", context=context) from None
    return merged


def _instance_defaults(defaults: Any, where: str) -> dict[str, Any] | None:
    """The include's ``defaults:`` block, refused as a workflow ``defaults:`` block is."""
    if defaults is None:
        return None
    try:
        DefaultsConfig.model_validate(defaults)
    except ValidationError as e:
        raise ConfigurationError(f"{where}: defaults: {_problems(e)}") from None
    for key in _WORKFLOW_ONLY_DEFAULTS:
        if key in defaults:
            raise ConfigurationError(
                f"{where}: defaults: '{key}' is a setting of the workflow. Set it under the "
                "workflow's own 'defaults:'."
            )
    return copy.deepcopy(defaults) or None


def _refuse_repeated_instances(
    inclusions: Sequence[Inclusion], workflow: str, workflow_file: str
) -> None:
    seen: set[str] = set()
    for inclusion in inclusions:
        if inclusion.instance in seen:
            raise ConfigurationError(
                f"Workflow '{workflow}' ({workflow_file}) includes "
                f"{inclusion.branch.label} twice with the instance name "
                f"'{inclusion.instance}'. Include the branch once; 'as:' is not supported yet.",
                context=_context(inclusion),
            )
        seen.add(inclusion.instance)


def _refuse_name_collisions(
    hosts: Sequence[Any],
    inclusions: Sequence[Inclusion],
    workflow: str,
    workflow_file: str,
) -> None:
    """Refuse a name that a branch defines and the host or another branch defines too.

    A versioned action counts under its own name and under each name its versions expand
    to; two host actions with one name are left to the workflow's own duplicate check.
    """
    host_label = f"workflow '{workflow}'"
    origin: dict[str, str] = {}
    for action in hosts:
        for name in _ordered_names(action):
            origin.setdefault(name, host_label)
    for inclusion in inclusions:
        for action in inclusion.actions:
            for name in _ordered_names(action):
                if name in origin:
                    raise ConfigurationError(
                        f"Action name '{name}' is defined twice in {workflow_file}: by "
                        f"{origin[name]} and by {inclusion.branch.label}. Rename one of them.",
                        context=_context(inclusion, action_name=name),
                    )
                origin[name] = inclusion.branch.label


def _refuse_bad_bindings(
    hosts: Sequence[Any],
    inclusions: Sequence[Inclusion],
    workflow: str,
    workflow_file: str,
) -> None:
    host_names = {name for action in hosts for name in _final_and_base_names(action)}
    owner: dict[str, tuple[Inclusion, str]] = {}
    remover: dict[str, Inclusion] = {}
    for inclusion in inclusions:
        for action in inclusion.actions:
            for name in _final_and_base_names(action):
                owner[name] = (inclusion, action["name"])
        for name in inclusion.removed_names():
            remover[name] = inclusion

    for inclusion in inclusions:
        branch = inclusion.branch
        where = f"Include '{branch.name}' in {workflow_file}"
        for key, target in inclusion.bindings.items():
            if key not in branch.inputs:
                declared = _listed(branch.inputs)
                raise ConfigurationError(
                    f"{where}: 'inputs' names '{key}', which {branch.label} does not "
                    f"declare. Branch inputs: {declared}.",
                    context=_context(inclusion),
                )
            if target != key:
                raise ConfigurationError(
                    f"{where}: input '{key}' is bound to '{target}'. A branch reads an input "
                    f"by its own name, so '{key}' must be bound to an action named '{key}'.",
                    context=_context(inclusion),
                )
        for key in branch.inputs:
            if key not in inclusion.bindings:
                raise ConfigurationError(
                    f"{where}: input '{key}' of {branch.label} is not bound. Bind it under "
                    f"'inputs:' to an action of workflow '{workflow}'.",
                    context=_context(inclusion),
                )
            target = inclusion.bindings[key]
            if target in host_names:
                continue
            if target not in owner and target in remover:
                raise ConfigurationError(
                    f"{where}: input '{key}' is bound to '{target}', which include "
                    f"'{remover[target].instance}' leaves out under 'remove:'.",
                    context=_context(inclusion),
                )
            if target not in owner:
                raise ConfigurationError(
                    f"{where}: input '{key}' is bound to '{target}', which is not an action of "
                    f"workflow '{workflow}'.",
                    context=_context(inclusion),
                )
            source, local_name = owner[target]
            if local_name not in source.outputs:
                raise ConfigurationError(
                    f"{where}: input '{key}' is bound to '{target}', which "
                    f"{source.branch.label} does not list under outputs. Outputs of "
                    f"'{source.branch.name}': {_listed(source.outputs)}.",
                    context=_context(inclusion),
                )


def _reads(
    action: dict[str, Any],
    extractor: Any,
    workflow_file: str,
    defaults: dict[str, Any],
    scope: dict[str, list[Any]],
) -> list[str]:
    """Every name *action* reads, in the order its config states them.

    *scope* stands for its ``context_scope``, and *defaults* give its ``expect`` block.
    """
    names: list[str] = []
    dependencies = action.get("dependencies") or []
    names.extend([dependencies] if isinstance(dependencies, str) else dependencies)
    view = {**action, "context_scope": scope}
    try:
        requirements = extractor.extract_from_agent(view)
    except TemplateSyntaxError as e:
        origin = action.get(_ORIGIN_KEY)
        where = (
            _branch_where(origin["branch"], workflow_file, f"'{origin['local_name']}'")
            if isinstance(origin, dict)
            else f"Action '{action.get('name')}' in {workflow_file}"
        )
        raise ConfigurationError(
            f"{where}: the prompt is not a valid template (line {e.lineno}): "
            f"{(e.message or '').rstrip('.')}.",
            context={"action_name": action.get("name")},
        ) from None
    names.extend(requirement.source_agent for requirement in requirements)
    consumption = action.get("version_consumption")
    if isinstance(consumption, dict) and isinstance(consumption.get("source"), str):
        names.append(consumption["source"])
    own = action.get("expect")
    expect = adapt_inherited_expect(
        merge_expect(defaults.get("expect"), own), own, _repair_view(action, defaults)
    )
    if expect is not None:
        for ref in collect_judge_context_refs(expect, action.get("schema")):
            if isinstance(ref, str):
                names.append(ref.split(".", 1)[0])
    return list(dict.fromkeys(name for name in names if isinstance(name, str)))


def _final_names(action: Any) -> list[str]:
    """The names *action* has once its versions expand."""
    if not isinstance(action, dict) or not isinstance(action.get("name"), str):
        return []
    if action.get("versions"):
        return version_variant_names(action["name"], action["versions"])
    return [action["name"]]


def _ordered_names(action: Any) -> list[str]:
    """*action*'s own name, then each name its versions expand to."""
    own = (
        [action["name"]] if isinstance(action, dict) and isinstance(action.get("name"), str) else []
    )
    return list(dict.fromkeys([*own, *_final_names(action)]))


def _final_and_base_names(action: Any) -> set[str]:
    """Every name a reference to *action* can use: its own, and its version base name."""
    names = set(_final_names(action))
    if isinstance(action, dict) and isinstance(action.get("name"), str):
        names.add(action["name"])
        version = action.get("_version_context")
        if isinstance(version, dict) and isinstance(version.get("base_name"), str):
            names.add(version["base_name"])
    return names


def _with_origin(action: dict[str, Any], inclusion: Inclusion) -> dict[str, Any]:
    origin: dict[str, Any] = {
        "branch": inclusion.branch.name,
        "instance": inclusion.instance,
        "local_name": action["name"],
        "branch_file": inclusion.branch.file,
    }
    if inclusion.defaults:
        origin["defaults"] = copy.deepcopy(dict(inclusion.defaults))
    return {**copy.deepcopy(action), _ORIGIN_KEY: origin}


def _is_include(entry: Any) -> bool:
    return isinstance(entry, dict) and "include" in entry


def _refuse_written_origin(actions: Sequence[Any], workflow_file: str) -> None:
    for entry in actions:
        if isinstance(entry, dict) and not _is_include(entry) and _ORIGIN_KEY in entry:
            raise ConfigurationError(
                f"Action '{entry.get('name')}' in {workflow_file}: '{_ORIGIN_KEY}' is set by the "
                "load on an included action and cannot be written in a workflow.",
                context={"action_name": entry.get("name")},
            )


def has_written_origin(data: Any) -> bool:
    """Whether an action of *data* that is not an include entry carries ``_include``."""
    actions = data.get("actions") if isinstance(data, dict) else None
    return isinstance(actions, list) and any(
        isinstance(entry, dict) and not _is_include(entry) and _ORIGIN_KEY in entry
        for entry in actions
    )


def has_include(data: Any) -> bool:
    """Whether *data* is a workflow with at least one include entry."""
    actions = data.get("actions") if isinstance(data, dict) else None
    return isinstance(actions, list) and any(_is_include(entry) for entry in actions)


def _included_names(data: Any) -> list[str]:
    names = [entry["include"] for entry in data["actions"] if _is_include(entry)]
    return list(dict.fromkeys(name for name in names if isinstance(name, str)))


def _read_branch_file(folder: Path, name: str, workflow_file: str) -> Any:
    path = folder / f"{name}.yml"
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        # The reason is in the message, and the CLI prints the innermost error.
        raise ConfigurationError(
            f"{_branch_where(name, workflow_file)}: the file is not valid YAML{where}: "
            f"{getattr(e, 'problem', None) or e}.",
            context={"branch_file": branch_file(name)},
        ) from None


def _workflow_label(workflow_path: Path, root: Path) -> str:
    """*workflow_path* relative to the project root when it lies under it."""
    resolved = workflow_path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(workflow_path)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _near_miss(key: str, accepted: Sequence[str]) -> str:
    near = difflib.get_close_matches(key, accepted, n=1)
    return f" Did you mean '{near[0]}'?" if near else ""


def _listed(names: Sequence[str]) -> str:
    return ", ".join(names) if names else "none"


def _context(inclusion: Inclusion, **extra: Any) -> dict[str, Any]:
    return {
        "workflow_file": inclusion.workflow_file,
        "branch": inclusion.branch.name,
        "branch_file": inclusion.branch.file,
        "instance": inclusion.instance,
        **extra,
    }


__all__ = [
    "BRANCH_KEYS",
    "INCLUDE_KEYS",
    "Branch",
    "Inclusion",
    "action_defaults",
    "branch_file",
    "check_include_reads",
    "expand_includes",
    "expand_workflow_includes",
    "has_include",
    "has_written_origin",
    "parse_branch",
]
