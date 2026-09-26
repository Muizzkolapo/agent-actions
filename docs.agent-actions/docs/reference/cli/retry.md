---
title: retry Command
description: Retry failed or exhausted records from a specific action forward
sidebar_position: 9
---

# retry Command

The `retry` command re-runs failed or exhausted records from an action forward, instead of re-running the whole workflow. Use [`dispositions`](./dispositions) first to see what is stuck and where.

```bash
agac retry -a <workflow-name> [options]
```

## Options

| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | Agent configuration file name without path or extension (required) |
| `--from TEXT` | Action to retry from. If omitted, retries from the earliest failure |
| `--record TEXT` | Restrict retry to a single record (by `source_guid`) at the `--from` action |
| `--dry-run` | Show what would be retried without executing |
| `--abandon-in-flight` | Retry even though a batch is still in flight, giving up its results |

## Examples

### See what would be retried

Always safe — nothing executes:

```bash
agac retry -a my_workflow --dry-run
```

When nothing is stuck it reports `No failed or exhausted records found. Nothing to retry.`

### Retry from the earliest failure

```bash
agac retry -a my_workflow
```

### Retry from a specific action

```bash
agac retry -a my_workflow --from extract_facts
```

### Retry a single record

```bash
agac retry -a my_workflow --from extract_facts --record 3f9a1c2e-...
```

`--record` takes the identifier shown in the **Record ID** column of [`dispositions --quarantined`](./dispositions) — retry matches against exactly that value.

## A retry runs the records it named, and only those

`retry` selects records by id — the ones that failed, or the single one given to
`--record`. Those are the records it processes at every action it re-runs, and
they are the only ones.

Nothing else in the input joins them. A record limit —
[`record_limit`](../configuration/defaults) or
[`AGAC_RECORD_LIMIT`](../configuration/) — keeps the first N records of an input
file, but deciding how much new work to take on is what a limit is for, and a
repair takes on none. A record the retry did not name is not work this run was
asked to do, however far inside the limit it sits.

[`file_limit`](../configuration/defaults) — and `--file-limit` or
`AGAC_FILE_LIMIT` — does not hold a retry back either. A retry resolves which
staged files hold the records it named and visits every one of them, instead of
walking the directory and stopping at N.

Being exempt from a limit is not being exempt from reading it. A value that
cannot be a limit at all — `AGAC_FILE_LIMIT=nonsense` — still fails a retry
while the workflow is assembled, as it fails any other command. An empty
variable is not such a value; it reads as unset.

Records the retry did not name keep what they already had. Their stored output
rows are carried into the rewritten file, and their dispositions are left alone —
a record that failed at an action the retry re-runs is still failed afterwards
unless the retry named it too.

This matters because `retry` clears a record's disposition before re-running it.
A retry that never reached the record would not leave it failed — it would leave
no record of the failure at all.

An action that turns one record into several gives the new rows fresh
identifiers, so a retry's ids match none of them. Those rows are resolved back
to the record they came from instead. A row is rewritten when the retry named a
record that is an input of that action, and the row either carries that
record's id or names it as its parent — the second only where no *other* input
of that action names the same record as its own parent. Every other row is
carried. So repairing a record whose row was split in two replaces both halves
rather than adding two more beside them.

Two shapes fall outside that, and both are carried rather than rewritten. A row
names the *original* staged record it descends from, not the record that
produced it directly, so where one such action feeds another the rows of the
second name a record that is no longer its input. And where an action reads
both a record and an expansion over that same record — `dependencies` naming
both — a row of the expansion names the record standing beside it in the input,
so which of the two produced it cannot be told apart.

In both, repairing one of that action's records leaves its previous rows in the
file beside the new ones. The run reports how many rows it could not place. It
carries them rather than guessing, because guessing wrong here deletes a row
that nothing will write again.

Dispositions are cleared by the ids the retry was given, so an id that names no
input of an action is simply not found there — nothing at that action is
re-run, and nothing it holds is removed.

## Retrying an action that runs in batch mode

An action configured [`run_mode: batch`](../configuration/run-mode) is repaired
the same way, with one difference in timing: the retry submits a new batch
holding only the records it named, then pauses and asks to be run again, and the
next run collects it. The records the retry did not name are not in that batch,
so nothing re-answers them.

A retry drops the action's record of the batches it has already collected —
those are spent, and keeping them would hand the repair a finished batch instead
of the one it just submitted.

That is also why a retry is refused while a batch is still out at the provider:

```
1 batch job(s) in flight (batch_abc123 (summarize)). Their results would be lost
to this repair's own submission. Collect them first — run the workflow again —
then retry. If the provider no longer has them, pass --abandon-in-flight.
```

The batch already out owns the records it was submitted for. Starting a repair
on top of it would put a second batch over the same file, and whichever came
back last would win while the other was paid for and discarded. Run the workflow
again to collect the batch in flight, then retry. Nothing is cleared when a
retry is refused, so the failures it would have repaired are still there to find.

`--dry-run` reports the refusal rather than raising it, so the plan you are shown
is the one that would actually run.

### When the batch cannot be collected

Collecting is the way forward whenever the provider can still answer about the
batch — including when it has finished, or failed, and the registry has not
caught up yet. The case it does not cover is a batch the provider no longer
recognises at all, usually because it expired. Then the entry reads in flight for
good and every remedy above needs an answer that is not coming.

`--abandon-in-flight` proceeds anyway, and says what it costs:

```
Abandoning 1 batch job(s) still in flight: batch_abc123 (summarize). Whatever
they return will not be collected. 3 record(s) waiting on them are marked failed
so a later retry can still reach them.
```

Those three are the rest of the batch. They were waiting on results that are
never arriving, and a record left waiting is not one `retry` can find — so they
are marked failed instead, which it can. They do not join the repair you asked
for: run `agac retry` again to pick them up.

Paired with `--dry-run`, the same figures are reported and nothing is written.

:::tip Run from Anywhere
You can run this command from any subdirectory within your project.
:::
