# Recovery Without Paying Twice

Use this page when an action produced bad output in a large run, and the actions before it were expensive.

## 1 The decision

| Situation | Do this |
|---|---|
| The prompt, schema or model of one action was wrong | Fix the config, then `agac run -w <workflow> -u tools --rerun <action>` |
| It was wrong for some records only (one category, one language, 100 of 500) | Fix the config, then `agac run -w <workflow> -u tools --rerun <action> --where '<guard expression>' --dry-run` to see the count, and the same command without `--dry-run`. Only the matching records are answered again; `--records ids.txt` takes a list of source_guids instead |
| Some records failed for a transient reason (rate limit, timeout) | `agac retry -w <workflow> --all` |
| One record can never succeed (input too large, input empty) | `agac retry -w <workflow> --filter <action>:<record_id> --reason "<why>"` |
| The output of an action is good, but the next action read the wrong field of it | Add a recovery tool action (section 2), then `--rerun` the recovery action |
| The staging input itself was wrong | `agac run -w <workflow> -u tools --fresh` (all output is lost; while a batch is open, add `--abandon-in-flight`, which drops the paid batch) |

A config edit alone runs nothing again. The edited action keeps its output until you give `--rerun`. See run (docs: `reference/cli/run#when-you-edit-the-workflow`).

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
3. Check the wiring of the fix offline: `agac run -w <workflow> -u tools --sandbox --rerun <action>`. It calls no model (section 5).
4. Run the fix on a small sample (`record_limit: N` on the first action, or a small staging file in a test project).
5. Run `scripts/run_health.py` after the rerun. Compare the bad share with the earlier run.

## 4 Stops in the middle of a run

| Stop | What stays | What to do |
|---|---|---|
| Crash, reboot, kill of the process | Every finished action. A submitted batch stays open at the provider | Run the same command again. agent-actions finds the open batch by its stored id and collects it |
| Out of memory or out of disk | The same, if the store write finished | Free memory or disk, then run again. Check the store with `sqlite3 <store> "pragma quick_check;"` if the disk was full during a write |
| Quota or credit used up (exit code 5) | Every finished record | Add credit, then run again |

Do not submit a provider batch by hand for a paused run. agent-actions does not know its id, so it never collects the results, and you pay twice.

## 5 Rehearse a recovery offline

A sandbox scenario makes the offline mock fail on purpose. Use it to see a recovery work before a real run needs it. Write the faults in a scenario file, or in `sandbox.<workflow>.yml` (else `sandbox.yml`) at the project root.

```yaml
# faults.yml
actions:
  classify_document:
    errors: {rate: 1.0, kinds: [server_error], heal_on_attempt: 3}
```

```bash
agac run -w <workflow> -u tools --sandbox --scenario faults.yml --fresh   # exits 1 or 3
agac retry -w <workflow> --sandbox --scenario faults.yml                  # heals, exits 0
```

1. `heal_on_attempt` is the attempt of a record from which the fault stops. The sandbox store counts the attempts, so `agac retry --sandbox` continues the count. With `retry: {max_attempts: 2}`, `heal_on_attempt: 3` fails the run and heals in the retry.
2. `records: [{match: {source.id: r7}, actions: {classify_document: {error: refusal}}}]` fails one record on each attempt. Use it to rehearse `agac retry --filter`.
3. For a batch action, `batch: {drop_rate: 0.5}` leaves results out of the first batch, and the retry batch gets them. `batch: {fail: [classify_document]}` fails the batch of that action at the provider.
4. `break_rules: {rules: all, rate: 1.0, heal_on_attempt: 2}` breaks a rule of each record once, so the repair round heals it.

A rehearsal checks that the recovery path is wired. It says nothing about cost, quota or real latency.
