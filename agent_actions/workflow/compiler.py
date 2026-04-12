"""Compile cross-workflow dependencies into a single unified action DAG.

When workflows reference actions in other workflows via dict dependencies
(e.g. ``{workflow: upstream, action: produce}``), the compiler resolves them
into qualified string dependencies (``upstream::produce``) and merges all
involved actions into a single flat list.  The result feeds into the existing
config pipeline — Pydantic never sees dict deps, strategy selection works
naturally, and lineage flows through without special flags.
"""

from __future__ import annotations

import copy
import logging
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import yaml

from agent_actions.errors import ConfigurationError, WorkflowError
from agent_actions.workflow.models import CompilationResult, CompiledAction

logger = logging.getLogger(__name__)

SEPARATOR = "::"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def needs_compilation(
    raw_config: dict[str, Any],
    run_upstream: bool = False,
    run_downstream: bool = False,
) -> bool:
    """Fast check: does this workflow config require cross-workflow compilation?

    Returns ``True`` when any action has dict-format dependencies or when the
    ``--upstream`` / ``--downstream`` CLI flags are set.
    """
    if run_upstream or run_downstream:
        return True
    for action in raw_config.get("actions", []):
        if not isinstance(action, dict):
            continue
        deps = action.get("depends_on") or action.get("dependencies", [])
        if isinstance(deps, list) and any(isinstance(d, dict) for d in deps):
            return True
    return False


def compile_workflows(
    primary_config_path: Path,
    workflows_root: Path,
    *,
    run_upstream: bool = False,
    run_downstream: bool = False,
) -> CompilationResult:
    """Compile all involved workflows into a single action DAG.

    1. Load the primary workflow's raw YAML.
    2. Extract cross-workflow deps to discover referenced workflows.
    3. Transitively load all referenced workflows (and upstream /
       downstream if the flags are set).
    4. Qualify every action name with its source workflow
       (``wf::action``).
    5. Rewrite all dependencies — dict deps become qualified strings,
       intra-workflow string deps are qualified within their source
       workflow.
    6. Return a :class:`CompilationResult` with the merged action list.
    """
    compiler = _WorkflowCompiler(workflows_root)
    return compiler.compile(primary_config_path, run_upstream, run_downstream)


def qualify(workflow_name: str, action_name: str) -> str:
    """Return ``'workflow_name::action_name'``."""
    return f"{workflow_name}{SEPARATOR}{action_name}"


def unqualify(qualified_name: str) -> tuple[str, str]:
    """Return ``(workflow_name, action_name)`` from a qualified name.

    Raises :class:`ValueError` if *qualified_name* does not contain the
    separator.
    """
    parts = qualified_name.split(SEPARATOR, 1)
    if len(parts) != 2:
        raise ValueError(f"Not a qualified action name: {qualified_name!r}")
    return parts[0], parts[1]


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------


class _WorkflowCompiler:
    """Stateful compiler — one instance per compilation."""

    def __init__(self, workflows_root: Path):
        self.workflows_root = workflows_root
        # workflow_name → raw YAML dict
        self._raw_configs: dict[str, dict[str, Any]] = {}
        # workflow_name → Path to its directory
        self._workflow_dirs: dict[str, Path] = {}
        # workflow_name → [upstream workflow names]
        self._workflow_graph: dict[str, list[str]] = {}

    # -- Entry point --------------------------------------------------------

    def compile(
        self,
        primary_config_path: Path,
        run_upstream: bool,
        run_downstream: bool,
    ) -> CompilationResult:
        primary_name = self._load_workflow(primary_config_path)

        # Discover workflows transitively referenced via dict deps.
        self._discover_referenced_workflows(primary_name)

        # If --upstream, ensure all transitive upstreams are loaded.
        if run_upstream:
            self._load_transitive_upstreams(primary_name)

        # If --downstream, load transitive downstreams from workspace.
        if run_downstream:
            self._load_transitive_downstreams(primary_name)

        # Detect cycles in the workflow-level graph.
        self._check_workflow_cycles()

        # Determine which workflows to include and in what order.
        involved = self._resolve_involved_workflows(primary_name, run_upstream, run_downstream)

        # Merge and qualify all actions.
        merged_actions, action_metadata = self._merge_actions(involved)

        return CompilationResult(
            merged_actions=merged_actions,
            action_metadata=action_metadata,
            primary_workflow=primary_name,
            involved_workflows=involved,
            workflow_graph=dict(self._workflow_graph),
        )

    # -- YAML loading -------------------------------------------------------

    def _load_workflow(self, config_path: Path) -> str:
        """Load a single workflow YAML and register it.  Returns the workflow name."""
        raw = self._load_raw_yaml(config_path)
        name = self._extract_workflow_name(raw, config_path)
        if name in self._raw_configs:
            return name  # already loaded
        self._raw_configs[name] = raw
        self._workflow_dirs[name] = config_path.parents[1]  # .../workflow_dir/agent_config/x.yml
        self._workflow_graph[name] = self._extract_upstream_workflows(raw)
        return name

    def _load_workflow_by_name(self, workflow_name: str) -> None:
        """Discover and load a workflow by name from the workspace root."""
        if workflow_name in self._raw_configs:
            return

        wf_dir = self.workflows_root / workflow_name
        if not wf_dir.is_dir():
            raise ConfigurationError(
                f"Referenced workflow directory not found: {workflow_name}",
                context={
                    "workflow_name": workflow_name,
                    "search_root": str(self.workflows_root),
                    "operation": "compile_workflows",
                },
            )

        config_dir = wf_dir / "agent_config"
        config_file = config_dir / f"{workflow_name}.yml"
        if not config_file.exists():
            yml_files = sorted(config_dir.glob("*.yml")) if config_dir.exists() else []
            if yml_files:
                config_file = yml_files[0]
            else:
                raise ConfigurationError(
                    f"No config file found for workflow: {workflow_name}",
                    context={
                        "workflow_name": workflow_name,
                        "search_dir": str(config_dir),
                        "operation": "compile_workflows",
                    },
                )

        self._load_workflow(config_file)

    @staticmethod
    def _load_raw_yaml(config_path: Path) -> dict[str, Any]:
        """Load workflow YAML without template rendering or Pydantic validation.

        We intentionally skip Jinja2 rendering here because the compiler only
        needs the action dependency structure, not fully-resolved prompts or
        schemas.  Template rendering happens later in the normal config pipeline.
        """
        try:
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if not isinstance(data, dict):
                raise ConfigurationError(
                    f"Workflow config is not a YAML mapping: {config_path.name}",
                    context={"config_path": str(config_path), "operation": "compile_workflows"},
                )
            return data
        except yaml.YAMLError as e:
            raise ConfigurationError(
                f"Invalid YAML in {config_path.name}: {e}",
                context={"config_path": str(config_path), "operation": "compile_workflows"},
                cause=e,
            ) from e

    @staticmethod
    def _extract_workflow_name(raw_config: dict[str, Any], config_path: Path) -> str:
        """Extract workflow name from config or derive from filename."""
        name = raw_config.get("name")
        if isinstance(name, str) and name:
            return name
        return config_path.stem

    @staticmethod
    def _extract_upstream_workflows(raw_config: dict[str, Any]) -> list[str]:
        """Extract upstream workflow names from dict-format dependencies."""
        upstreams: list[str] = []
        for action in raw_config.get("actions", []):
            if not isinstance(action, dict):
                continue
            deps = action.get("depends_on") or action.get("dependencies", [])
            if not isinstance(deps, list):
                continue
            for dep in deps:
                if isinstance(dep, dict) and "workflow" in dep:
                    wf = dep["workflow"]
                    if wf not in upstreams:
                        upstreams.append(wf)
        return upstreams

    # -- Transitive discovery -----------------------------------------------

    def _discover_referenced_workflows(self, start: str) -> None:
        """Transitively load all workflows referenced via dict deps."""
        queue = deque(self._workflow_graph.get(start, []))
        while queue:
            wf = queue.popleft()
            if wf in self._raw_configs:
                continue
            self._load_workflow_by_name(wf)
            queue.extend(self._workflow_graph.get(wf, []))

    def _load_transitive_upstreams(self, primary: str) -> None:
        """Ensure all transitive upstream workflows are loaded (--upstream flag)."""
        # Scan workspace to find workflows that the primary depends on transitively.
        self._scan_workspace_for_graph()
        visited: set[str] = set()
        queue = deque(self._workflow_graph.get(primary, []))
        while queue:
            wf = queue.popleft()
            if wf in visited:
                continue
            visited.add(wf)
            self._load_workflow_by_name(wf)
            queue.extend(self._workflow_graph.get(wf, []))

    def _load_transitive_downstreams(self, primary: str) -> None:
        """Load all transitive downstream workflows (--downstream flag)."""
        self._scan_workspace_for_graph()
        # Build reverse graph.
        reverse: dict[str, set[str]] = defaultdict(set)
        for wf, upstreams in self._workflow_graph.items():
            for up in upstreams:
                reverse[up].add(wf)
        # BFS from primary through reverse edges.
        visited: set[str] = set()
        queue = deque(reverse.get(primary, set()))
        while queue:
            wf = queue.popleft()
            if wf in visited:
                continue
            visited.add(wf)
            self._load_workflow_by_name(wf)
            queue.extend(reverse.get(wf, set()))

    def _scan_workspace_for_graph(self) -> None:
        """Scan the workspace root to build the full workflow-level dependency graph.

        Only loads YAML headers (action deps), not full configs.  Workflows
        already in ``_raw_configs`` are skipped.
        """
        if not self.workflows_root.exists():
            return
        for wf_dir in sorted(self.workflows_root.iterdir()):
            if not wf_dir.is_dir():
                continue
            wf_name = wf_dir.name
            if wf_name in self._workflow_graph:
                continue
            config_dir = wf_dir / "agent_config"
            if not config_dir.exists():
                continue
            config_file = config_dir / f"{wf_name}.yml"
            if not config_file.exists():
                yml_files = sorted(config_dir.glob("*.yml"))
                if not yml_files:
                    continue
                config_file = yml_files[0]
            try:
                raw = self._load_raw_yaml(config_file)
                self._workflow_graph[wf_name] = self._extract_upstream_workflows(raw)
            except ConfigurationError:
                self._workflow_graph[wf_name] = []

    # -- Cycle detection ----------------------------------------------------

    def _check_workflow_cycles(self) -> None:
        """Raise :class:`WorkflowError` if the workflow-level graph has cycles."""
        all_nodes = set(self._workflow_graph.keys())
        for deps in self._workflow_graph.values():
            all_nodes.update(deps)

        in_degree: dict[str, int] = {n: 0 for n in all_nodes}
        for _node, deps in self._workflow_graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[dep] += 1

        queue = deque(n for n in all_nodes if in_degree[n] == 0)
        visited = 0
        while queue:
            node = queue.popleft()
            visited += 1
            for dep in self._workflow_graph.get(node, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)

        if visited != len(all_nodes):
            cycle_nodes = {n for n in all_nodes if in_degree[n] > 0}
            raise WorkflowError(
                "Cyclic dependency detected between workflows",
                context={
                    "cycle_nodes": sorted(cycle_nodes),
                    "operation": "compile_workflows",
                },
            )

    # -- Resolve involved workflows -----------------------------------------

    def _resolve_involved_workflows(
        self,
        primary: str,
        run_upstream: bool,
        run_downstream: bool,
    ) -> list[str]:
        """Return the list of workflows to include, in topological order.

        Upstreams first, then primary, then downstreams.
        """
        involved: set[str] = {primary}

        # Add upstreams (transitively).
        if run_upstream:
            involved.update(self._collect_transitive(primary, direction="upstream"))
        # Always include workflows referenced via dict deps (even without --upstream).
        involved.update(self._collect_transitive(primary, direction="upstream"))

        # Add downstreams (transitively).
        if run_downstream:
            involved.update(self._collect_transitive(primary, direction="downstream"))

        # Topological sort: upstreams before dependents.
        return self._topo_sort_workflows(involved)

    def _collect_transitive(self, start: str, *, direction: str) -> set[str]:
        """BFS to collect transitive upstreams or downstreams."""
        if direction == "upstream":
            graph = self._workflow_graph
        else:
            # Build reverse graph.
            graph: dict[str, list[str]] = defaultdict(list)
            for wf, ups in self._workflow_graph.items():
                for up in ups:
                    graph[up].append(wf)

        result: set[str] = set()
        queue = deque(graph.get(start, []))
        while queue:
            wf = queue.popleft()
            if wf in result:
                continue
            result.add(wf)
            queue.extend(graph.get(wf, []))
        return result

    def _topo_sort_workflows(self, involved: set[str]) -> list[str]:
        """Topological sort of involved workflows (upstreams first).

        Reuses the same Kahn's-algorithm convention as
        ``agent_actions.utils.graph_utils.topological_sort``: the graph maps
        each node to its *dependencies* (predecessors), the algorithm emits
        leaf nodes first and reverses at the end so that dependencies appear
        before dependents.
        """
        from agent_actions.utils.graph_utils import topological_sort

        # Build sub-graph for involved workflows only.
        sub_graph: dict[str, list[str]] = {}
        for wf in involved:
            sub_graph[wf] = [dep for dep in self._workflow_graph.get(wf, []) if dep in involved]

        return topological_sort(sub_graph)

    # -- Merge actions ------------------------------------------------------

    def _merge_actions(
        self, involved: list[str]
    ) -> tuple[list[dict[str, Any]], dict[str, CompiledAction]]:
        """Merge and qualify actions from all involved workflows."""
        merged: list[dict[str, Any]] = []
        metadata: dict[str, CompiledAction] = {}

        # Build a set of all qualified action names for validation.
        all_qualified: set[str] = set()
        for wf_name in involved:
            raw = self._raw_configs[wf_name]
            for action in raw.get("actions", []):
                if not isinstance(action, dict):
                    continue
                aname = action.get("name")
                if aname:
                    all_qualified.add(qualify(wf_name, aname))

        for wf_name in involved:
            raw = self._raw_configs[wf_name]
            wf_dir = self._workflow_dirs[wf_name]
            defaults = raw.get("defaults", {}) or {}
            data_source = defaults.get("data_source")

            for action in raw.get("actions", []):
                if not isinstance(action, dict):
                    continue

                local_name = action.get("name")
                if not local_name:
                    continue

                qualified = qualify(wf_name, local_name)
                action_copy = copy.deepcopy(action)

                # Rewrite dependencies.
                action_copy["dependencies"] = self._rewrite_deps(
                    action_copy.get("depends_on") or action_copy.get("dependencies", []),
                    wf_name,
                    all_qualified,
                )
                # Remove legacy depends_on key if present.
                action_copy.pop("depends_on", None)

                # Set the qualified name but preserve agent_type as local name.
                action_copy["name"] = qualified

                # Inject source workflow metadata.
                action_copy["_source_workflow_dir"] = str(wf_dir)
                action_copy["_source_workflow_name"] = wf_name

                merged.append(action_copy)
                metadata[qualified] = CompiledAction(
                    name=qualified,
                    local_name=local_name,
                    source_workflow=wf_name,
                    source_workflow_dir=wf_dir,
                    source_data_source=data_source,
                )

        return merged, metadata

    @staticmethod
    def _rewrite_deps(
        deps: Any,
        source_workflow: str,
        all_qualified: set[str],
    ) -> list[str]:
        """Rewrite a dependency list to qualified string deps.

        - String deps are qualified within *source_workflow*.
        - Dict deps ``{workflow: X, action: Y}`` become ``X::Y``.
        """
        if not isinstance(deps, list):
            return []

        result: list[str] = []
        for dep in deps:
            if isinstance(dep, str):
                result.append(qualify(source_workflow, dep))
            elif isinstance(dep, dict) and "workflow" in dep and "action" in dep:
                result.append(qualify(dep["workflow"], dep["action"]))
            # Skip anything else (malformed deps handled by Pydantic later).
        return result
