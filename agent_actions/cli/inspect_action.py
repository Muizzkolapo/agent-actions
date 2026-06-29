"""Inspect action and context subcommands."""

import json as json_lib
import logging
from pathlib import Path
from typing import Any

import click

from agent_actions.cli.cli_decorators import handles_user_errors, requires_project
from agent_actions.output.response.config_fields import get_default
from agent_actions.services.workflow_inspector import WorkflowInspector
from agent_actions.utils.constants import DEFAULT_ACTION_KIND

from .inspect_base import BaseInspectCommand
from .workflow_loader import validate_action_exists

logger = logging.getLogger(__name__)


class ActionCommand(BaseInspectCommand):
    """Show detailed information about a single action."""

    def __init__(
        self,
        agent: str,
        user_code: str | None,
        json_output: bool,
        action_name: str,
    ):
        super().__init__(agent, user_code, json_output)
        self.action_name = action_name

    def execute(self, project_root: Path | None = None) -> None:
        inspector = self._load_inspector(project_root=project_root)
        validate_action_exists(self.action_name, inspector.action_configs)

        action_config = inspector.action_configs[self.action_name]
        dependency_info = self._analyze_dependencies(inspector)
        info = dependency_info[self.action_name]

        if self.json_output:
            self._output_json(action_config, info)
        else:
            self._output_rich(action_config, info, inspector)

    def _output_json(self, action_config: dict[str, Any], info: dict[str, Any]) -> None:
        output = {
            "workflow": self.agent_name,
            "action": self.action_name,
            "type": self._get_action_type(info["input_sources"], info["context_sources"]),
            "kind": action_config.get("kind", DEFAULT_ACTION_KIND),
            "model": action_config.get("model_name"),
            "input_sources": info["input_sources"],
            "context_sources": info["context_sources"],
            "context_scope": info["context_scope"],
            "output_fields": self._get_output_fields(
                action_config,
                action_schema=self._get_action_schema(self.action_name),
            ),
        }
        click.echo(json_lib.dumps(output, indent=2))

    def _output_rich(
        self, action_config: dict[str, Any], info: dict[str, Any], inspector=None
    ) -> None:
        """Definition-list layout.

        Top block (Kind, Model, Granularity, Guard) is the action's
        identity. Input/Reads/Writes/Used-by form the data-flow block:
        what feeds this action, what it observes, what it produces,
        who consumes its output.
        """
        kind = action_config.get("kind", DEFAULT_ACTION_KIND)
        model = action_config.get("model_name") or "—"
        granularity = action_config.get("granularity", get_default("granularity"))
        guard = action_config.get("guard")
        guard_label = guard.get("clause", "yes") if isinstance(guard, dict) else "none"

        input_label = self._describe_input(info["input_sources"], info["context_sources"])
        reads = self._gather_reads(info)
        writes = self._get_output_fields(
            action_config, action_schema=self._get_action_schema(self.action_name)
        )
        consumers = self._find_consumers(inspector) if inspector else []
        right_meta = self._position_meta(inspector) if inspector else None

        from agent_actions.cli.inspect_base import render_title_row

        self.console.print()
        render_title_row(
            self.console,
            self.action_name,
            section="action detail",
            right_meta=right_meta,
        )
        self.console.print()

        fields: list[tuple[str, object]] = [
            ("Kind", kind),
            ("Model", model),
            ("Granularity", granularity),
            ("Guard", guard_label),
            ("Input", input_label),
        ]
        if reads:
            fields.append(("Reads", reads))
        if writes:
            fields.append(("Writes", writes))
        # Always include Used by — explicit "no downstream" is more
        # informative than absence (the user knows whether it's a leaf).
        fields.append(("Used by", consumers if consumers else "— [dim](terminal action)[/dim]"))

        label_width = max(len(label) for label, _ in fields)
        for i, (label, value) in enumerate(fields):
            prev_was_list = i > 0 and isinstance(fields[i - 1][1], list)
            curr_is_list = isinstance(value, list)
            # Breathing room: metadata block → first list (Reads), and
            # between two adjacent list blocks (Reads → Writes).
            if i > 0 and (curr_is_list and not prev_was_list or curr_is_list and prev_was_list):
                self.console.print()
            self._print_field(label, value, label_width)

    def _find_consumers(self, inspector) -> list[str]:
        """Find every action whose dependencies include this one.

        Iterates `inspector.action_configs` — handles both the
        ``dependencies: [...]`` field and ``depends_on``, matching the
        codebase's two conventions. Returns names in execution order so
        the user sees the natural reading sequence.
        """
        target = self.action_name
        consumers: list[str] = []
        for name in inspector.execution_order:
            cfg = inspector.action_configs.get(name, {})
            deps = cfg.get("dependencies") or cfg.get("depends_on") or []
            if isinstance(deps, str):
                deps = [deps]
            if target in deps:
                consumers.append(name)
        return consumers

    def _position_meta(self, inspector) -> str | None:
        """`qanalabs_quiz_gen · level 3 of 36` — right-side title meta.

        Gives the bookmarkable output a workflow root and a position
        anchor. Lets the user re-find this action in the pipeline view.
        """
        try:
            idx = list(inspector.execution_order).index(self.action_name)
        except ValueError:
            return self.agent_name  # action not in order — show parent only
        total = len(inspector.execution_order)
        return f"{self.agent_name} · level {idx + 1} of {total}"

    @staticmethod
    def _describe_input(input_sources: list[str], context_sources: list[str]) -> str:
        """Render the Input row.

        Names the upstream action(s) feeding this one. For source
        actions (no upstream), shows the placeholder ``source data``.
        Type tag (``transform`` / ``merge``) appended in dim parens.
        """
        # Strip the always-available `source` namespace from contexts —
        # it'd otherwise show as "(+ source)" on most rows.
        contexts = [c for c in context_sources if c != "source"]
        if not input_sources:
            return "source data  [dim](source action)[/dim]"
        if len(input_sources) == 1:
            value = input_sources[0]
            tag = "transform"
        else:
            value = ", ".join(input_sources)
            tag = f"merge of {len(input_sources)}"
        if contexts:
            tag += f" + {len(contexts)} context"
        return f"{value}  [dim]({tag})[/dim]"

    @staticmethod
    def _gather_reads(info: dict[str, Any]) -> list[str]:
        """Flatten observed / passthrough / dropped field references
        into one ordered list — what the action SEES.
        """
        scope = info.get("context_scope") or {}
        reads: list[str] = []
        reads.extend(scope.get("observe") or [])
        reads.extend(scope.get("passthrough") or [])
        return reads

    def _print_field(self, label: str, value: object, label_width: int) -> None:
        # ``highlight=False`` keeps Rich from re-coloring values that
        # look like numbers, paths, URLs, etc. — e.g. ``gpt-4`` would
        # otherwise have the ``4`` painted cyan as if it were a literal.
        padded_label = f"[bold]{label}[/bold]" + " " * (label_width - len(label))
        if isinstance(value, list):
            if not value:
                self.console.print(f"  {padded_label}  [dim]—[/dim]", highlight=False)
                return
            self.console.print(f"  {padded_label}  {value[0]}", soft_wrap=True, highlight=False)
            hang = " " * (2 + label_width + 2)
            for item in value[1:]:
                self.console.print(f"{hang}{item}", soft_wrap=True, highlight=False)
        else:
            self.console.print(f"  {padded_label}  {value}", soft_wrap=True, highlight=False)


@click.command(name="action")
@click.option("-a", "--agent", required=True, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.argument("action_name", metavar="ACTION_NAME")
@handles_user_errors("inspect action")
@requires_project
def action(
    agent: str,
    user_code: str | None,
    json_output: bool,
    action_name: str,
    project_root: Path | None = None,
) -> None:
    """
    Show details for a specific action.

    Displays configuration, dependencies, and context scope.

    ACTION_NAME is a positional argument (not a flag). Pass it as a positional
    argument alongside the options.

    \b
    Examples:
      agac inspect action -a my_workflow extract_facts
      agac inspect action -a my_workflow generate_question --json
    """
    ActionCommand(
        agent=agent, user_code=user_code, json_output=json_output, action_name=action_name
    ).execute(project_root=project_root)


class ContextCommand(BaseInspectCommand):
    """Show context debug information for a specific action."""

    def __init__(
        self,
        agent: str,
        user_code: str | None,
        json_output: bool,
        action_name: str,
    ):
        super().__init__(agent, user_code, json_output)
        self.target_action_name = action_name

    def execute(self, project_root: Path | None = None) -> None:
        inspector = self._load_inspector(project_root=project_root)
        validate_action_exists(self.target_action_name, inspector.action_configs)

        action_config = inspector.action_configs[self.target_action_name]
        dependency_info = self._analyze_dependencies(inspector)
        info = dependency_info[self.target_action_name]

        context_data = self._build_context_data(inspector, action_config, info)

        if self.json_output:
            self._output_json(context_data)
        else:
            self._output_rich(context_data)

    def _build_context_data(
        self,
        inspector: WorkflowInspector,
        action_config: dict[str, Any],
        info: dict[str, Any],
    ) -> dict[str, Any]:
        namespaces: dict[str, list[str]] = {}
        for dep in info["input_sources"]:
            dep_config = inspector.action_configs.get(dep, {})
            dep_fields = self._get_output_fields(
                dep_config, action_schema=self._get_action_schema(dep)
            )
            if dep_fields:
                namespaces[dep] = dep_fields

        for dep in info["context_sources"]:
            dep_config = inspector.action_configs.get(dep, {})
            dep_fields = self._get_output_fields(
                dep_config, action_schema=self._get_action_schema(dep)
            )
            if dep_fields:
                namespaces[dep] = dep_fields

        # Always-available special namespaces.
        namespaces["workflow"] = ["name", "run_id"]
        namespaces["version"] = ["i", "idx", "length", "first", "last"]

        context_scope = action_config.get("context_scope", {})
        return {
            "action_name": self.target_action_name,
            "workflow": self.agent_name,
            "namespaces": namespaces,
            "context_scope": {
                "observe": context_scope.get("observe", []),
                "passthrough": context_scope.get("passthrough", []),
                "drop": context_scope.get("drop", []),
            },
            "total_template_variables": sum(len(fs) for fs in namespaces.values()),
        }

    def _output_json(self, context_data: dict[str, Any]) -> None:
        click.echo(json_lib.dumps(context_data, indent=2))

    def _output_rich(self, context_data: dict[str, Any]) -> None:
        """Namespace table — each namespace gets one row with its fields.

        The user knows the ``{{ ns.field }}`` syntax; we show the
        building blocks (namespace → fields) rather than enumerating
        every combination as boilerplate template syntax.
        """
        action_name = context_data["action_name"]
        namespaces = context_data["namespaces"]
        scope = context_data["context_scope"]

        from agent_actions.cli.inspect_base import render_title_row

        self.console.print()
        render_title_row(
            self.console,
            action_name,
            section="template context",
            right_meta=self.agent_name,
        )
        self.console.print()

        # Scope on its own indented block — avoids the awkward
        # mid-line wrap that happens when observe/drop lists are long.
        scope_lines: list[str] = []
        for kind in ("observe", "passthrough", "drop"):
            items = scope.get(kind) or []
            if items:
                scope_lines.append(f"    [cyan]{kind}[/cyan]: {', '.join(items)}")
        if scope_lines:
            self.console.print("  [bold]Scope applied:[/bold]")
            for line in scope_lines:
                self.console.print(line, soft_wrap=True)
            self.console.print()
        else:
            self.console.print(
                "  [bold]Scope applied:[/bold]  [dim]none (all fields visible)[/dim]\n"
            )

        if namespaces:
            ns_width = max(len(ns) for ns in namespaces) + 2
            for ns, fields in namespaces.items():
                self.console.print(
                    f"  [green]{ns}[/green]" + " " * (ns_width - len(ns)) + f"{', '.join(fields)}",
                    soft_wrap=True,
                )

        # Concrete `{{ ns.field }}` snippet so a prompt author can copy
        # one verbatim. Picks the first observed namespace's first
        # field — most likely to be the one driving the prompt.
        # Split onto two lines so the parenthetical count never wraps
        # mid-phrase on narrow terminals.
        if namespaces:
            example_ns, example_fields = next(iter(namespaces.items()))
            if example_fields:
                example = f"{{{{ {example_ns}.{example_fields[0]} }}}}"
                self.console.print(f"\n  [dim]Use in prompts as[/dim]  [cyan]{example}[/cyan]")
                self.console.print(
                    f"  [dim]({context_data['total_template_variables']} variables "
                    f"across {len(namespaces)} namespaces)[/dim]"
                )


@click.command(name="context")
@click.option("-a", "--agent", required=True, help="Workflow name")
@click.option("-u", "--user-code", required=False, help="Path to user code directory")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON")
@click.argument("action_name", metavar="ACTION_NAME")
@handles_user_errors("inspect context")
@requires_project
def context(
    agent: str,
    user_code: str | None,
    json_output: bool,
    action_name: str,
    project_root: Path | None = None,
) -> None:
    """
    Show context debug information for a specific action.

    Displays available namespaces, context scope rules, and template variables
    that would be available during template rendering.

    ACTION_NAME is a positional argument (not a flag). Pass it as a positional
    argument alongside the options.

    \b
    Examples:
      agac inspect context -a my_workflow extract_facts
      agac inspect context -a my_workflow generate_question --json
    """
    ContextCommand(
        agent=agent, user_code=user_code, json_output=json_output, action_name=action_name
    ).execute(project_root=project_root)
