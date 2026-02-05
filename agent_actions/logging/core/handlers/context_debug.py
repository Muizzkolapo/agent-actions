"""
Context debug handler for aggregating and displaying context debug information.

This handler collects context-related events during workflow execution and
provides a summary display for the --debug-context flag and inspect context command.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from agent_actions.logging.core.events import BaseEvent

from agent_actions.logging.core._compat import RICH_AVAILABLE, Console, Tree


@dataclass
class ActionContextInfo:
    """Aggregated context information for a single action."""

    action_name: str
    namespaces: Dict[str, List[str]] = field(default_factory=dict)
    dropped_fields: Dict[str, List[str]] = field(default_factory=dict)
    observe_fields: List[str] = field(default_factory=list)
    passthrough_fields: List[str] = field(default_factory=list)
    drop_fields: List[str] = field(default_factory=list)
    input_sources: List[str] = field(default_factory=list)
    context_sources: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    skipped_fields: List[Dict[str, str]] = field(default_factory=list)
    not_found_fields: List[Dict[str, Any]] = field(default_factory=list)


class ContextDebugHandler:
    """
    Handler that aggregates context events for debug display.

    Collects ContextNamespaceLoadedEvent, ContextFieldSkippedEvent,
    ContextScopeAppliedEvent, etc. and provides display_summary() for
    rich output.

    Usage:
        handler = ContextDebugHandler()
        manager.register(handler)
        # ... workflow execution ...
        handler.display_summary()
    """

    # Event codes we handle
    CONTEXT_EVENT_CODES = {"CX001", "CX002", "CX003", "CX005", "CX006"}

    def __init__(self, console: Optional[Any] = None) -> None:
        """
        Initialize the context debug handler.

        Args:
            console: Rich Console instance (creates new one if not provided)
        """
        self._actions: Dict[str, ActionContextInfo] = {}
        self._event_count = 0

        # Initialize Rich console if available
        if RICH_AVAILABLE and Console is not None:
            self._console = console or Console()
            self._use_rich = True
        else:
            self._console = None
            self._use_rich = False

    def _get_or_create_action(self, action_name: str) -> ActionContextInfo:
        """Get or create action context info."""
        if action_name not in self._actions:
            self._actions[action_name] = ActionContextInfo(action_name=action_name)
        return self._actions[action_name]

    def accepts(self, event: BaseEvent) -> bool:
        """
        Check if this is a context event we should collect.

        Args:
            event: Event to check

        Returns:
            True if this is a context introspection event
        """
        return event.code in self.CONTEXT_EVENT_CODES

    def handle(self, event: BaseEvent) -> None:
        """
        Collect context event data.

        Args:
            event: Context event to process
        """
        self._event_count += 1

        # Get action name from event data
        action_name = getattr(event, "action_name", "unknown")
        action_info = self._get_or_create_action(action_name)

        code = event.code

        if code == "CX001":  # ContextNamespaceLoadedEvent
            namespace = getattr(event, "namespace", "")
            fields = getattr(event, "fields", [])
            dropped = getattr(event, "dropped_fields", [])
            action_info.namespaces[namespace] = fields
            if dropped:
                action_info.dropped_fields[namespace] = dropped

        elif code == "CX002":  # ContextFieldSkippedEvent
            field_ref = getattr(event, "field_ref", "")
            reason = getattr(event, "reason", "")
            directive = getattr(event, "directive", "")
            action_info.skipped_fields.append(
                {
                    "field_ref": field_ref,
                    "reason": reason,
                    "directive": directive,
                }
            )
            action_info.warnings.append(f"Skipped {field_ref} in {directive}: {reason}")

        elif code == "CX003":  # ContextScopeAppliedEvent
            action_info.observe_fields = getattr(event, "observe_fields", [])
            action_info.passthrough_fields = getattr(event, "passthrough_fields", [])
            action_info.drop_fields = getattr(event, "drop_fields", [])

        elif code == "CX005":  # ContextDependencyInferredEvent
            action_info.input_sources = getattr(event, "input_sources", [])
            action_info.context_sources = getattr(event, "context_sources", [])

        elif code == "CX006":  # ContextFieldNotFoundEvent
            field_ref = getattr(event, "field_ref", "")
            namespace = getattr(event, "namespace", "")
            available = getattr(event, "available_fields", [])
            action_info.not_found_fields.append(
                {
                    "field_ref": field_ref,
                    "namespace": namespace,
                    "available_fields": available,
                }
            )
            action_info.warnings.append(f"Field '{field_ref}' not found in '{namespace}'")

    def flush(self) -> None:
        """Flush is a no-op for this handler."""
        pass

    def get_action_info(self, action_name: str) -> Optional[ActionContextInfo]:
        """Get context info for a specific action."""
        return self._actions.get(action_name)

    def get_all_actions(self) -> Dict[str, ActionContextInfo]:
        """Get all collected action context info."""
        return self._actions

    def get_event_count(self) -> int:
        """Get total number of context events processed."""
        return self._event_count

    def display_summary(self, action_name: Optional[str] = None) -> None:
        """
        Display collected context debug information.

        Args:
            action_name: If provided, only show info for this action
        """
        if self._use_rich and self._console:
            self._display_rich_summary(action_name)
        else:
            self._display_plain_summary(action_name)

    def _display_rich_summary(self, action_filter: Optional[str] = None) -> None:
        """Display summary using Rich formatting."""
        if not self._console:
            return

        actions_to_show = (
            {action_filter: self._actions[action_filter]}
            if action_filter and action_filter in self._actions
            else self._actions
        )

        if not actions_to_show:
            self._console.print("[yellow]No context events collected.[/yellow]")
            return

        for action_name, info in actions_to_show.items():
            self._console.print()
            self._console.print(
                f"[bold cyan]=== Context Debug for action '{action_name}' ===[/bold cyan]"
            )
            self._console.print()

            # Namespaces loaded
            if info.namespaces:
                tree = Tree("[bold]Namespaces loaded:[/bold]")
                for ns, fields in info.namespaces.items():
                    dropped = info.dropped_fields.get(ns, [])
                    dropped_str = (
                        f" [dim]({len(dropped)} dropped: {', '.join(dropped[:3])}{'...' if len(dropped) > 3 else ''})[/dim]"
                        if dropped
                        else ""
                    )
                    field_str = ", ".join(fields[:5])
                    if len(fields) > 5:
                        field_str += f"... (+{len(fields) - 5} more)"
                    tree.add(
                        f"[green]{ns}[/green]: {len(fields)} fields [{field_str}]{dropped_str}"
                    )
                self._console.print(tree)
                self._console.print()

            # Context scope applied
            if info.observe_fields or info.passthrough_fields or info.drop_fields:
                tree = Tree("[bold]Context scope applied:[/bold]")
                if info.observe_fields:
                    tree.add(f"[cyan]observe:[/cyan] {', '.join(info.observe_fields)}")
                if info.passthrough_fields:
                    tree.add(f"[cyan]passthrough:[/cyan] {', '.join(info.passthrough_fields)}")
                if info.drop_fields:
                    tree.add(f"[cyan]drop:[/cyan] {', '.join(info.drop_fields)}")
                self._console.print(tree)
                self._console.print()

            # Template variables
            if info.namespaces:
                tree = Tree("[bold]Template variables available:[/bold]")
                for ns, fields in info.namespaces.items():
                    vars_str = ", ".join(f"{{{{ {ns}.{f} }}}}" for f in fields[:3])
                    if len(fields) > 3:
                        vars_str += f", ... (+{len(fields) - 3} more)"
                    tree.add(f"[magenta]{vars_str}[/magenta]")
                self._console.print(tree)
                self._console.print()

            # Dependencies
            if info.input_sources or info.context_sources:
                tree = Tree("[bold]Dependencies:[/bold]")
                if info.input_sources:
                    tree.add(f"[green]input_sources:[/green] {', '.join(info.input_sources)}")
                if info.context_sources:
                    tree.add(f"[yellow]context_sources:[/yellow] {', '.join(info.context_sources)}")
                self._console.print(tree)
                self._console.print()

            # Warnings
            if info.warnings:
                self._console.print("[bold yellow]Warnings:[/bold yellow]")
                for warning in info.warnings:
                    self._console.print(f"  [yellow]! {warning}[/yellow]")
                self._console.print()

    def _display_plain_summary(self, action_filter: Optional[str] = None) -> None:
        """Display summary using plain text."""
        actions_to_show = (
            {action_filter: self._actions[action_filter]}
            if action_filter and action_filter in self._actions
            else self._actions
        )

        if not actions_to_show:
            print("No context events collected.")
            return

        for action_name, info in actions_to_show.items():
            print()
            print(f"=== Context Debug for action '{action_name}' ===")
            print()

            # Namespaces loaded
            if info.namespaces:
                print("Namespaces loaded:")
                for ns, fields in info.namespaces.items():
                    dropped = info.dropped_fields.get(ns, [])
                    dropped_str = f" ({len(dropped)} dropped)" if dropped else ""
                    print(f"  - {ns}: {len(fields)} fields [{', '.join(fields[:5])}]{dropped_str}")
                print()

            # Context scope applied
            if info.observe_fields or info.passthrough_fields or info.drop_fields:
                print("Context scope applied:")
                if info.observe_fields:
                    print(f"  - observe: {', '.join(info.observe_fields)}")
                if info.passthrough_fields:
                    print(f"  - passthrough: {', '.join(info.passthrough_fields)}")
                if info.drop_fields:
                    print(f"  - drop: {', '.join(info.drop_fields)}")
                print()

            # Dependencies
            if info.input_sources or info.context_sources:
                print("Dependencies:")
                if info.input_sources:
                    print(f"  - input_sources: {', '.join(info.input_sources)}")
                if info.context_sources:
                    print(f"  - context_sources: {', '.join(info.context_sources)}")
                print()

            # Warnings
            if info.warnings:
                print("Warnings:")
                for warning in info.warnings:
                    print(f"  ! {warning}")
                print()

    def to_dict(self, action_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Convert collected data to a dictionary for JSON output.

        Args:
            action_name: If provided, only include this action

        Returns:
            Dictionary representation of context debug info
        """
        actions_to_show = (
            {action_name: self._actions[action_name]}
            if action_name and action_name in self._actions
            else self._actions
        )

        return {
            "event_count": self._event_count,
            "actions": {
                name: {
                    "namespaces": {
                        ns: {
                            "fields": fields,
                            "field_count": len(fields),
                            "dropped_fields": info.dropped_fields.get(ns, []),
                        }
                        for ns, fields in info.namespaces.items()
                    },
                    "context_scope": {
                        "observe": info.observe_fields,
                        "passthrough": info.passthrough_fields,
                        "drop": info.drop_fields,
                    },
                    "dependencies": {
                        "input_sources": info.input_sources,
                        "context_sources": info.context_sources,
                    },
                    "warnings": info.warnings,
                    "skipped_fields": info.skipped_fields,
                    "not_found_fields": info.not_found_fields,
                }
                for name, info in actions_to_show.items()
            },
        }

    def reset(self) -> None:
        """Clear all collected data."""
        self._actions.clear()
        self._event_count = 0
