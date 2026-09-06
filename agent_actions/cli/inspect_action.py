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


def _escape_markup(text: str) -> str:
    """Escape `[` / `]` so a value embedded in a Rich f-string can't be
    misread as a markup tag. `metrics[0]` inside `[dim](…)[/dim]` would
    otherwise raise MarkupError or silently drop output."""
    return text.replace("[", "\\[").replace("]", "\\]")


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
        run_mode = self._stringify(action_config.get("run_mode")) or self._stringify(
            get_default("run_mode")
        )
        json_mode = "yes" if action_config.get("json_mode") else "no"
        retry_label = self._describe_retry(action_config.get("retry"))

        input_label = self._describe_input(info["input_sources"], info["context_sources"])
        reads = self._gather_reads(info)
        write_fields = self._get_output_fields(
            action_config, action_schema=self._get_action_schema(self.action_name)
        )
        # Show count + preview; the full list is in the Schema section below.
        if len(write_fields) > 3:
            preview = ", ".join(_escape_markup(f) for f in write_fields[:3])
            writes: object = f"{len(write_fields)} fields  [dim]({preview}, …)[/dim]"
        elif write_fields:
            writes = ", ".join(_escape_markup(f) for f in write_fields)
        else:
            writes = None
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
        if retry_label:
            fields.append(("Retry", retry_label))
        fields.append(("Guard", guard_label))
        fields.append(("Input", input_label))
        if reads:
            fields.append(("Reads", reads))
        if writes:
            fields.append(("Writes", writes))
        # Explicit terminal marker is clearer than an absent row.
        fields.append(("Used by", consumers if consumers else "— [dim](terminal action)[/dim]"))

        label_width = max(len(label) for label, _ in fields)
        for i, (label, value) in enumerate(fields):
            if i > 0 and isinstance(value, list):
                self.console.print()
            self._print_field(label, value, label_width)

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
        # Prefer the compiled JSON schema; fall back to the raw `schema:`
        # (dict or custom-fields list) so non-LLM kinds still show something.
        schema = action_config.get("json_output_schema") or action_config.get("schema")
        if not schema or not isinstance(schema, (dict, list)):
            return

        import yaml
        from rich.syntax import Syntax

        self.console.print()
        self._print_section_rule("Schema")
        try:
            rendered = yaml.safe_dump(
                schema, sort_keys=False, default_flow_style=False, allow_unicode=True
            )
        except yaml.YAMLError:
            # Non-safe type in schema (e.g. HITL-injected Enum) — repr, don't crash.
            rendered = repr(schema)
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
        """Downstream consumers, with the relationship type. An action can
        read this one either as a hard dependency (``dependencies:``) or as
        context-only (``context_scope.observe/passthrough``); both belong
        in the blast radius.

        Returns Rich-markup-ready strings like ``foo (×3)  (depends on)``
        and ``bar  (reads as context)``. Sorted, version-collapsed."""
        from agent_actions.cli.inspect_base import collapse_version_groups

        target = self.action_name
        dep_consumers: list[str] = []
        ctx_consumers: list[str] = []

        for name in inspector.execution_order:
            cfg = inspector.action_configs.get(name, {})
            deps = cfg.get("dependencies") or cfg.get("depends_on") or []
            if isinstance(deps, str):
                deps = [deps]
            if target in deps:
                dep_consumers.append(name)
                continue

            # Include `drop` — dropping a namespace still references it.
            scope = cfg.get("context_scope") or {}
            if isinstance(scope, dict):
                refs = (
                    list(scope.get("observe") or [])
                    + list(scope.get("passthrough") or [])
                    + list(scope.get("drop") or [])
                )
                for ref in refs:
                    if isinstance(ref, str) and ref.split(".", 1)[0] == target:
                        ctx_consumers.append(name)
                        break

        configs = inspector.action_configs
        dep_collapsed = collapse_version_groups(sorted(dep_consumers), configs)
        ctx_collapsed = collapse_version_groups(sorted(ctx_consumers), configs)

        # Direct deps first — they move records; context readers second.
        lines: list[str] = []
        for name in dep_collapsed:
            lines.append(f"{name}  [dim](depends on)[/dim]")
        for name in ctx_collapsed:
            lines.append(f"{name}  [dim](reads as context)[/dim]")
        return lines

    def _position_meta(self, inspector) -> str | None:
        """`action N of M` — N is position in execution_order. Not "level" —
        the default view already shows a distinct level count."""
        try:
            idx = list(inspector.execution_order).index(self.action_name)
        except ValueError:
            return self.agent_name
        return f"{self.agent_name} · action {idx + 1} of {len(inspector.execution_order)}"

    @staticmethod
    def _describe_input(input_sources: list[str], context_sources: list[str]) -> str:
        # `source` is always available — strip so it doesn't clutter every row.
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
        """One line per upstream namespace, with the fields observed from
        it. Wildcards collapse to `*`. Long explicit lists show a count
        + the names. Both are far easier to scan than the raw per-ref
        flat list."""
        scope = info.get("context_scope") or {}
        # YAML source — entries are Any before preflight; the `isinstance`
        # guard below is real, not dead.
        refs: list[Any] = list(scope.get("observe") or []) + list(scope.get("passthrough") or [])
        if not refs:
            return []

        grouped: dict[str, list[str]] = {}
        bare: set[str] = set()
        for ref in refs:
            if not isinstance(ref, str):
                continue
            ns, sep, field = ref.partition(".")
            if not sep:
                # Track bare-namespace refs (`foo` with no dot) separately so
                # a malformed entry doesn't collapse a real fields list to `*`.
                bare.add(ns)
                grouped.setdefault(ns, [])
                continue
            grouped.setdefault(ns, []).append(field)

        lines: list[str] = []
        for ns in sorted(grouped):
            fields = [f for f in grouped[ns] if f]
            if "*" in fields:
                lines.append(f"{ns}: [dim]*[/dim]")
                continue
            if not fields and ns in bare:
                lines.append(f"{ns}: [red](bare namespace — no field)[/red]")
                continue
            fields = sorted(set(fields))
            # Escape `[` in field names (e.g. `metrics[0]`) so Rich doesn't
            # eat them as markup.
            safe_ns = _escape_markup(ns)
            safe = [_escape_markup(f) for f in fields]
            if len(safe) <= 5:
                lines.append(f"{safe_ns}: {', '.join(safe)}")
            else:
                head = ", ".join(safe[:5])
                lines.append(f"{safe_ns}: {head}, … [dim](+{len(safe) - 5} more)[/dim]")
        return lines

    def _print_field(self, label: str, value: object, label_width: int) -> None:
        # highlight=False — otherwise Rich repaints digits like the `4` in `gpt-4`.
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
        # `source` is always available. Parens (not brackets) so Rich
        # doesn't parse the placeholder as markup.
        namespaces["source"] = ["(record fields)"]
        for dep in info["input_sources"]:
            dep_config = inspector.action_configs.get(dep, {})
            dep_fields = self._get_output_fields(
                dep_config, action_schema=self._get_action_schema(dep)
            )
            if dep_fields:
                namespaces[dep] = dep_fields

        for dep in info["context_sources"]:
            if dep in namespaces:
                continue
            dep_config = inspector.action_configs.get(dep, {})
            dep_fields = self._get_output_fields(
                dep_config, action_schema=self._get_action_schema(dep)
            )
            if dep_fields:
                namespaces[dep] = dep_fields

        # Source of truth: what the runtime actually populates at pipeline entry
        # (see build_workflow_metadata in prompt.context.scope_application).
        from agent_actions.prompt.context.scope_application import FRAMEWORK_FIELDS

        namespaces["workflow"] = list(FRAMEWORK_FIELDS["workflow"])
        namespaces["version"] = list(FRAMEWORK_FIELDS["version"])

        context_scope = action_config.get("context_scope") or {}

        # `seed.*` is populated by the `seed` directive.
        seed_keys = self._seed_namespace_keys(context_scope)
        # Don't shadow a user action literally named `seed`.
        if seed_keys and "seed" not in namespaces:
            namespaces["seed"] = seed_keys

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

    @staticmethod
    def _seed_namespace_keys(context_scope: dict[str, Any]) -> list[str]:
        """Keys exposed under the ``seed.*`` namespace, from the ``seed`` directive."""
        seed_entries = context_scope.get("seed")
        if not isinstance(seed_entries, dict):
            return []
        return list(dict.fromkeys(seed_entries.keys()))

    @staticmethod
    def _group_refs_by_namespace(refs: list[Any]) -> dict[str, list[str]]:
        """`["a.x", "a.y", "b.*"]` → `{"a": ["x", "y"], "b": ["*"]}`. Bare
        names fall into a `""` namespace. Non-string entries (raw YAML)
        are skipped."""
        grouped: dict[str, list[str]] = {}
        for ref in refs:
            if not isinstance(ref, str):
                continue
            ns, _, field = ref.partition(".")
            grouped.setdefault(ns, []).append(field if field else "")
        return {ns: sorted(fields) for ns, fields in sorted(grouped.items(), key=lambda kv: kv[0])}

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

        # Group by namespace so a long observe list reads as `foo: a, b, c, …`
        # rather than many single-field lines.
        scope_kinds = [(kind, scope.get(kind) or []) for kind in ("observe", "passthrough", "drop")]
        scope_kinds = [(k, refs) for k, refs in scope_kinds if refs]

        if scope_kinds:
            self.console.print("  [bold]Scope applied:[/bold]")
            for kind, refs in scope_kinds:
                grouped = self._group_refs_by_namespace(refs)
                count_label = (
                    f"{len(refs)} ref{'s' if len(refs) != 1 else ''} "
                    f"from {len(grouped)} namespace{'s' if len(grouped) != 1 else ''}"
                )
                self.console.print(f"    [cyan]{kind}[/cyan]  [dim]({count_label})[/dim]")
                # `default=0` — every ref could be non-string (e.g. `observe: [null]`).
                ns_width = max((len(n) for n in grouped), default=0) + 2
                for ns, fields in grouped.items():
                    field_str = ", ".join(fields) if fields else "[dim]*[/dim]"
                    self.console.print(
                        f"      [bright_white]{ns}[/bright_white]"
                        + " " * (ns_width - len(ns))
                        + field_str,
                        soft_wrap=True,
                    )
            self.console.print()
        else:
            self.console.print(
                "  [bold]Scope applied:[/bold]  [dim]none (all fields visible)[/dim]\n"
            )

        if namespaces:
            framework = {"source", "workflow", "version", "loop", "seed"}
            # User namespaces first, framework at the bottom.
            ordered = sorted(namespaces.items(), key=lambda kv: (kv[0] in framework, kv[0]))
            ns_width = max(len(ns) for ns, _ in ordered) + 2
            for ns, fields in ordered:
                is_framework = ns in framework
                colour = "bright_blue" if is_framework else "green"
                tag = "  [dim italic](framework)[/dim italic]" if is_framework else ""
                self.console.print(
                    f"  [{colour}]{ns}[/{colour}]"
                    + " " * (ns_width - len(ns))
                    + f"{', '.join(fields)}{tag}",
                    soft_wrap=True,
                )

        # Copy-paste snippet. Walk user namespaces first so the picker
        # prefers action-specific fields over framework ones like `workflow.name`.
        example: str | None = None
        snippet_walk = ordered if namespaces else []
        for ns, fields in snippet_walk:
            if not fields:
                continue
            first_field = fields[0]
            # Skip `(record fields)` / `[schema: …]` placeholders — they'd render
            # as `{{ ns. }}` with an empty field.
            if first_field.startswith("(") or first_field.startswith("["):
                continue
            example = f"{{{{ {ns}.{first_field} }}}}"
            break
        if example is not None:
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
