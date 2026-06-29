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
        kind = self._stringify(action_config.get("kind", DEFAULT_ACTION_KIND))
        model = action_config.get("model_name") or "—"
        granularity = action_config.get("granularity", get_default("granularity"))
        guard = action_config.get("guard")
        guard_label = guard.get("clause", "yes") if isinstance(guard, dict) else "none"
        run_mode = self._stringify(action_config.get("run_mode")) or "online"
        json_mode = "yes" if action_config.get("json_mode") else "no"
        reprompt_label = self._describe_reprompt(action_config.get("reprompt"))
        retry_label = self._describe_retry(action_config.get("retry"))

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
            ("Run mode", f"{run_mode}  ·  json mode: {json_mode}"),
        ]
        if reprompt_label:
            fields.append(("Reprompt", reprompt_label))
        if retry_label:
            fields.append(("Retry", retry_label))
        fields.append(("Guard", guard_label))
        fields.append(("Input", input_label))
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
            if i > 0 and (curr_is_list and not prev_was_list or curr_is_list and prev_was_list):
                self.console.print()
            self._print_field(label, value, label_width)

        # Full rendered prompt + schema — what the LLM actually sees.
        # ``{{ jinja }}`` placeholders remain visible because they're
        # substituted per-record at run time, not at preflight.
        self._print_prompt_section(action_config.get("prompt"))
        self._print_schema_section(action_config)

    def _print_prompt_section(self, prompt: object) -> None:
        if not isinstance(prompt, str) or not prompt.strip():
            return
        self.console.print()
        self._print_section_rule(
            "Prompt", subtitle="{{ jinja }} placeholders filled in per-record at run time"
        )
        for line in prompt.splitlines():
            self.console.print(f"    {line}", soft_wrap=True, highlight=False)
        self.console.print()

    def _print_schema_section(self, action_config: dict[str, Any]) -> None:
        # Prefer the compiled JSON output schema (what the LLM actually
        # gets); fall back to the raw `schema` dict for non-LLM kinds.
        schema = action_config.get("json_output_schema") or action_config.get("schema")
        if not schema or not isinstance(schema, dict):
            return
        import yaml

        self._print_section_rule("Schema")
        rendered = yaml.dump(schema, sort_keys=False, default_flow_style=False, allow_unicode=True)
        from rich.syntax import Syntax

        self.console.print(
            Syntax(
                rendered,
                "yaml",
                theme="ansi_dark",
                background_color="default",
                padding=(0, 4),
                line_numbers=False,
                word_wrap=True,
            )
        )

    def _print_section_rule(self, title: str, subtitle: str | None = None) -> None:
        from rich.text import Text

        width = self.console.width or 100
        head = Text()
        head.append("── ", style="dim")
        head.append(title, style="bold")
        head.append(" ", style="")
        rule_len = max(width - head.cell_len - 2, 8)
        head.append("─" * rule_len, style="dim")
        self.console.print(head)
        if subtitle:
            self.console.print(f"   [dim]{subtitle}[/dim]")
        self.console.print()

    @staticmethod
    def _stringify(value: object) -> str:
        if value is None:
            return ""
        # Enums: prefer the member's `value` over the noisy repr.
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)

    @staticmethod
    def _describe_reprompt(reprompt: object) -> str:
        if not isinstance(reprompt, dict):
            return ""
        bits = []
        if reprompt.get("max_attempts"):
            bits.append(f"max {reprompt['max_attempts']}")
        if reprompt.get("on_schema_mismatch"):
            bits.append(f"on_schema_mismatch={reprompt['on_schema_mismatch']}")
        if reprompt.get("on_exhausted"):
            bits.append(f"on_exhausted={reprompt['on_exhausted']}")
        if reprompt.get("use_self_reflection"):
            bits.append("self-reflection")
        return ", ".join(bits) or "yes"

    @staticmethod
    def _describe_retry(retry: object) -> str:
        if not isinstance(retry, dict) or not retry:
            return ""
        bits = []
        if retry.get("max_attempts"):
            bits.append(f"max {retry['max_attempts']}")
        if retry.get("backoff"):
            bits.append(f"backoff={retry['backoff']}")
        return ", ".join(bits) or "yes"

    def _find_consumers(self, inspector) -> list[str]:
        """Actions whose deps include this one, returned in execution order."""
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
        try:
            idx = list(inspector.execution_order).index(self.action_name)
        except ValueError:
            return self.agent_name
        return f"{self.agent_name} · level {idx + 1} of {len(inspector.execution_order)}"

    @staticmethod
    def _describe_input(input_sources: list[str], context_sources: list[str]) -> str:
        # `source` namespace is always-available — stripped so it
        # doesn't show as "(+ source)" on most rows.
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
        scope = info.get("context_scope") or {}
        reads: list[str] = []
        reads.extend(scope.get("observe") or [])
        reads.extend(scope.get("passthrough") or [])
        return reads

    def _print_field(self, label: str, value: object, label_width: int) -> None:
        # highlight=False — otherwise Rich repaints the `4` in `gpt-4`.
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

        # Scope as its own block — long observe/drop lists wrap awkwardly inline.
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

        # Copy-paste snippet — prompt authors get a concrete example
        # instead of having to know Jinja syntax themselves.
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
