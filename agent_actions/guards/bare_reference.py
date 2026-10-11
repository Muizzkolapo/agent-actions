"""Whether a bare (un-dotted) guard reference provably resolves against nothing.

A guard clause naming a field without its namespace -- `n` rather than `a1.n` -- resolves
nowhere at runtime: the record is filtered or skipped with a warning and the run exits
successfully, so a workflow spelled that way discards every record and reports no error.

The rule is narrow on purpose. A bare name resolves through several promotions, and
refusing every un-dotted reference would reject configurations that work today. Only a
reference this module can prove wrong is reportable; anything it cannot settle is left
alone, because the alternative is refusing a run over a clause the runtime answers.

Shared so the pre-flight check and any other reader apply one rule. The editor diagnostic
in ``tooling/lsp/diagnostics.py`` implements the same model against its own metadata and
should be migrated onto this function once both land.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from agent_actions.record.envelope import RECORD_FRAMEWORK_FIELDS
from agent_actions.utils.constants import RUNTIME_BUS_NAMESPACES

# The evaluator promotes every record key EXCEPT `content`, whose namespaces it spreads.
# A clause on `content` itself therefore resolves against nothing.
PROMOTED_RECORD_FIELDS = RECORD_FRAMEWORK_FIELDS - {"content"}

# VersionNamespaceBuilder promotes `i` and `idx` explicitly and every _version_context key
# outside its reserved set, which is how `base_name` and `param_name` arrive too.
# `length`, `first` and `last` are reserved and stay under `version`.
PROMOTED_VERSION_KEYS = frozenset({"i", "idx", "base_name", "param_name"})


def bare_reference_is_unresolvable(
    variable: str,
    *,
    upstreams: Iterable[str],
    upstream_output_fields: Mapping[str, str | None],
    version_params: Iterable[str] = (),
    any_upstream_spreads_flat: bool = False,
) -> bool:
    """True only when *variable* cannot resolve by any promotion the runtime performs.

    ``upstreams`` is the set of actions this one names. An empty set means a first-stage
    action, whose content is the staging row: its columns are not knowable from config, so
    nothing about it is provable. ``upstream_output_fields`` maps each upstream to its
    declared ``output_field`` (``None`` when the action is unknown here, which is also
    unprovable). ``any_upstream_spreads_flat`` is set when an upstream is a
    FILE-granularity version-merge tool, which spreads its output flat over record content
    so any bare name may be one of its fields.
    """
    if "." in variable:
        return False
    if variable in PROMOTED_VERSION_KEYS or variable in set(version_params):
        return False
    if variable in PROMOTED_RECORD_FIELDS or variable in RUNTIME_BUS_NAMESPACES:
        return False
    if any_upstream_spreads_flat:
        return False

    named = set(upstreams)
    if not named:
        return False
    if variable in named:
        # `assess IS NOT NULL` names the namespace itself, which is promoted to top level.
        return False
    for name in named:
        if name not in upstream_output_fields:
            return False
        if upstream_output_fields[name] == variable:
            return False
    return True


def spreads_output_flat(action_config: Mapping) -> bool:
    """Whether this action's output is spread flat over record content, not namespaced.

    The three conditions `validate_version_merge_output_namespaces` uses, so the two
    cannot drift: only a FILE-granularity version-merge tool behaves this way.
    """
    granularity = str(action_config.get("granularity") or "").lower()
    is_tool = action_config.get("kind") == "tool" or action_config.get("model_vendor") == "tool"
    return bool(granularity == "file" and is_tool and action_config.get("version_consumption"))


__all__ = [
    "PROMOTED_RECORD_FIELDS",
    "PROMOTED_VERSION_KEYS",
    "bare_reference_is_unresolvable",
    "spreads_output_flat",
]
