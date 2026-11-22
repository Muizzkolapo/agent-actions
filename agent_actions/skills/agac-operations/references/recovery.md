# Recovery Without Paying Twice

Use this page when an action produced bad output in a large run, and the actions before it were expensive.

## 1 The decision

| Situation | Do this |
|---|---|
| The prompt, schema or model of one action was wrong | Fix the config, then `agac run -w <workflow> -u tools --rerun <action>` |
| Some records failed for a transient reason (rate limit, timeout) | `agac retry -w <workflow> --all` |
| One record can never succeed (input too large, input empty) | `agac retry -w <workflow> --filter <action>:<record_id> --reason "<why>"` |
| The output of an action is good, but the next action read the wrong field of it | Add a recovery tool action (section 2), then `--rerun` the recovery action |
| The staging input itself was wrong | `agac run -w <workflow> -u tools --fresh` (all output is lost) |

A config edit alone runs nothing again. The edited action keeps its output until you give `--rerun`. See [run](https://docs.runagac.com/docs/reference/cli/run#when-you-edit-the-workflow).

## 2 The recovery tool action

The paid output is in the store, but in a shape that the next action cannot use. Example: an invoice-extraction action wrote its line items into an extra field, and its declared field `items_text` is empty. The actions after it read `items_text`.

Do not run the expensive action again. Add a tool action that rebuilds the field from what the store already holds, and point the readers at it.

1. Add the tool action after the expensive action:

    ```yaml
    - name: extract_invoice_fixed
      dependencies: [extract_invoice]
      kind: tool
      impl: rebuild_items_text
      intent: Rebuild items_text from the stored output of extract_invoice
      schema:
        items_text: string
      context_scope:
        observe:
          - extract_invoice.*
    ```

2. Write the tool so that it always returns the same keys:

    ```python
    import json
    from typing import Any

    from agent_actions import udf_tool


    @udf_tool()
    def rebuild_items_text(data: dict[str, Any]) -> dict[str, Any]:
        out = data.get("extract_invoice") or {}
        items = out.get("line_items")
        if isinstance(items, list) and items:
            return {"items_text": json.dumps({"line_items": items})}
        return {"items_text": str(out.get("items_text") or "")}
    ```

3. Change each reader to depend on and observe `extract_invoice_fixed` in place of `extract_invoice`.
4. Run `agac run -w <workflow> -u tools --rerun extract_invoice_fixed`. The tool runs on every record, and every action after it runs again. `extract_invoice` keeps its paid output.
5. Remove the recovery action when the cause is fixed, and give `--rerun` to the first reader.

## 3 Before you run again

1. Find the cause on a few records first: `agac records -w <workflow> -A <action>` and `agac traces -w <workflow> -A <action>`.
2. Fix the cause in the config or the tool, not only the symptom.
3. Run the fix on a small sample (`record_limit: N` on the first action, or a small staging file in a test project).
4. Run `scripts/run_health.py` after the rerun. Compare the bad share with the earlier run.

## 4 Stops in the middle of a run

| Stop | What stays | What to do |
|---|---|---|
| Crash, reboot, kill of the process | Every finished action. A submitted batch stays open at the provider | Run the same command again. agent-actions finds the open batch by its stored id and collects it |
| Out of memory or out of disk | The same, if the store write finished | Free memory or disk, then run again. Check the store with `sqlite3 <store> "pragma quick_check;"` if the disk was full during a write |
| Quota or credit used up (exit code 5) | Every finished record | Add credit, then run again |

Do not submit a provider batch by hand for a paused run. agent-actions does not know its id, so it never collects the results, and you pay twice.
