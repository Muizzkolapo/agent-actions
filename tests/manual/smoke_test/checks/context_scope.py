from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from tests.manual.smoke_test.checks import Check
from tests.manual.smoke_test.context import CheckResult, RunContext


@dataclass
class ContextScope(Check):
    """Verify a dropped field never reached the declaring action's LLM context.

    That is what `drop` guarantees and the whole of it — the field stays on the bus, so
    checking a downstream action's *output* for its absence asserts a redaction the
    framework does not perform. Point `action` at the action that DECLARES the drop, and
    give `dropped_fields` its `namespace.field` refs. The action's `observe` must reach
    them, normally through a wildcard over the same namespace; where `observe` names
    fields explicitly the field was never in the context and the check cannot fail.
    """

    action: str
    dropped_fields: list[str] = field(default_factory=list)

    def verify(self, ctx: RunContext) -> list[CheckResult]:
        label = f"context_scope({self.action}): dropped fields absent from llm_context"

        if ctx.exit_code != 0:
            return [
                CheckResult(
                    False,
                    f"context_scope({self.action}): pipeline completed",
                    f"exit code {ctx.exit_code} — cannot verify context scope",
                )
            ]
        if ctx.db_path is None:
            return [CheckResult(False, label, "no storage DB found")]

        refs: list[tuple[str, str]] = []
        for ref in self.dropped_fields:
            namespace, _, leaf = ref.rpartition(".")
            if not namespace or not leaf:
                return [CheckResult(False, label, f"ref '{ref}' names no namespace")]
            refs.append((namespace, leaf))
        if not refs:
            return [CheckResult(False, label, "check declares no dropped_fields")]
        # `ns.*` deletes the namespace outright at runtime. Without this the leaf "*" is
        # looked up as a literal key, never found, and the check passes having proved
        # nothing — the silent-pass shape this check was rewritten to remove.

        with sqlite3.connect(str(ctx.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='prompt_trace'"
            )
            if cursor.fetchone() is None:
                return [CheckResult(False, label, "prompt_trace table does not exist")]
            # A versioned action stores under its expanded names, so match the base.
            cursor.execute(
                """
                SELECT record_id, attempt, llm_context FROM prompt_trace
                WHERE action_name = ? OR action_name LIKE ? || '_%'
                """,
                (self.action, self.action),
            )
            rows = cursor.fetchall()

        if not rows:
            # Not a pass: no trace means nothing was verified. A guard-filtered action is
            # the usual cause, and that needs saying rather than counting green.
            return [
                CheckResult(
                    False, label, f"no prompt_trace rows for '{self.action}' — nothing verified"
                )
            ]

        violations: list[str] = []
        inspected = 0
        truncated = 0
        for row in rows:
            raw = row["llm_context"]
            if not raw:
                continue
            try:
                context = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                violations.append(f"{row['record_id']}@{row['attempt']}: llm_context unparseable")
                continue
            if not isinstance(context, dict):
                continue
            if context.get("__truncated__"):
                # sqlite_backend swaps an over-1MB context for a stub. It parses and it
                # is a dict, so counting it inspected would report green on no evidence.
                truncated += 1
                continue
            inspected += 1
            for namespace, leaf in refs:
                namespace_data = context.get(namespace)
                if leaf == "*":
                    if namespace in context:
                        violations.append(f"{row['record_id']}@{row['attempt']}: {namespace}.*")
                    continue
                if isinstance(namespace_data, dict) and leaf in namespace_data:
                    violations.append(f"{row['record_id']}@{row['attempt']}: {namespace}.{leaf}")
                elif leaf in context:
                    # Observed fields are also flattened to their bare names.
                    violations.append(f"{row['record_id']}@{row['attempt']}: {leaf} (flat)")

        if violations:
            return [
                CheckResult(
                    False, label, f"{len(violations)} violations: {'; '.join(violations[:5])}"
                )
            ]
        if not inspected:
            detail = (
                f"all {truncated} llm_context(s) were truncated at write time"
                if truncated
                else "no trace carried an llm_context"
            )
            return [CheckResult(False, label, f"{detail} — nothing verified")]
        return [
            CheckResult(
                True,
                label,
                f"checked {inspected} llm_context(s)"
                + (f" ({truncated} skipped as truncated)" if truncated else "")
                + f" — none carry {[f'{ns}.{leaf}' for ns, leaf in refs]}",
            )
        ]
