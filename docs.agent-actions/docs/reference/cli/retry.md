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
they are the only ones. The exception is a retry that
[resumes a halted action](#a-retry-resumes-a-halted-action-in-full).

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

Dispositions are cleared by the ids the retry was given, at every action it
re-runs, and the re-run decides them again wherever it reaches the record. An id
that names no input of an action is simply not found there — nothing at that
action is re-run.

A record the re-run never repairs at the action it starts from is reached
nowhere: a failure an earlier release recorded under a batch record's target id,
one written by hand, a record whose input file is gone, one in a file the action
failed to process, or any of them when the action fails before it finishes.
Cleared and never decided again, it would lose its failures without being
repaired. So the retry puts back what it cleared for such a record at every
action that did not decide the record again itself, reads an action it had left
complete again as a run reads it, and names the records (the first ten, and how
many more):

```
1 record(s) named at 'summarize' were not in its input, so nothing repaired them
and their failures stand: t-3f9a1c2e. Retry selects a record by the source_guid
it arrives with. Where a record's input is gone, restore it as it was; an id no
input carries, such as a target id an earlier release recorded or one set by
hand, is cleared only by starting over with `agac run --fresh`.
```

Where the record was in a file the action failed to process, or the action did
not finish, the retry says so instead, and the remedy is to fix that error and
run the retry again.

A record the re-run found, in a file it processed to the end, is not put back,
even where the action wrote nothing under its id: a file tool that rolls its
input into rows no single record produced answers it that way.

A record that reaches an action without a `source_guid` — from an upstream file
edited by hand, say — has no id to name. In either run mode it is refused: it
gets no disposition, and is stored as a failed row that keeps its target id but
has no `source_guid`, so `retry` neither lists nor repairs it. An answer that
expands into several rows is the exception: each row gets an identity of its
own. If the action's other records succeeded, it reads complete, and the failed
row and the run log say what was refused; if nothing succeeded, the action
fails. The remedy is upstream: give the record its `source_guid` back where it
is produced. A batch run that sends nothing at all refuses it the same way, and
since nothing in such a run succeeds, the action fails.

## A retry needs every action it runs to hold an answer for every record

Carrying what an action holds for the records the retry did not name is only
right when that is an answer for each of them. An action that did not finish its
last run — added since then, put back to pending because something it reads was
edited, or stopped partway through its records by an interrupt, a kill or an
error — holds none for the records that run had not reached. Nor does a
completed action whose stored output is gone. A retry that narrowed it would
complete it without them, and nothing would run it again.

That covers every action the retry runs, not only those from its starting point:
the run behind it executes whatever is not complete, wherever it sits, so an
action added beside the one that failed, which may run before it, counts too.

So a retry that names records refuses, before it changes anything, when such an
action is in the workflow:

```
1 action(s) hold no current answer for some of their records (enrich
(interrupted)). A retry answers only the records it names and carries what each
action holds for the rest, so it would complete them without those answers. Run
the workflow first — agac run -a my_workflow — then retry.
```

Run the workflow, which finishes those actions, then retry. `--dry-run` reports
the refusal instead of raising it.

A failed action is not refused when its last run reached every record and every
one failed: each holds its failure, which is what a retry is for. That is known
when every record it was given failed, when every input file failed on all of its
records, or, for a batch action, when every record its batches were sent with a
`source_guid` holds an answer or a failure. It is refused even then if it still
holds a row for a record that run did not reach: a reset keeps an action's rows
until it writes again, and one that failed on everything wrote nothing, so a row
for a record its input no longer has, or now filters, would be carried for good.
A failure that stopped partway — an error that ends a file at one record, or one
recorded before this release, which cannot say — is refused.

Not refused either: an action left unfinished by a retry that was itself
interrupted had finished before that retry, so running `retry` again resumes it,
as long as no run has reset it since. An action holding a batch nobody has
collected, and one that reads it, are left to the batch's own refusal below,
which `--abandon-in-flight` gets past. An action halted by `on_exhausted: raise`
has its own way on, below.

## A retry resumes a halted action in full

An action halted by
[`on_exhausted: raise`](../validation/expectations.md#repairing-instead-of-observing)
stopped partway through its records, and `agac run` leaves it halted. `retry` is
the way on. The halted action holds no answer, and no failure, for the records
past the halt, so a retry narrowed to the records it names would complete it
without them.

A retry that starts at the halted action and is not given `--record` names no
record: it runs that action, and every action after it, on each record they hold
no answer for — the ones past the halt and the ones that failed — and says so in
its plan. A plain `retry` does this when the halt is the earliest failure.

```bash
agac retry -a my_workflow --from extract_facts
```

A retry that names records and would clear a halt — one starting before the
halted action, or given `--record` — is refused before it changes anything, and
names the retry that resumes it:

```
1 action(s) hold no current answer for some of their records (extract_facts
(halted)). A retry answers only the records it names and carries what each
action holds for the rest, so it would complete them without those answers.
First resume extract_facts with a retry from it, which names no record and runs
it in full — agac retry -a my_workflow --from extract_facts — then retry.
```

Run that retry, then the one you wanted. `--dry-run` reports the refusal
instead of raising it. A halted action before the retry's starting point is not
refused: the retry leaves its halt in place, so it stays halted.

## When a retry is interrupted

A retry writes down the failures it is about to clear before it clears them. If it
is stopped before its run reaches the end, the next `retry` puts them back and
starts where the stopped one did, so the records it named are answered again from
there.

What has moved on since keeps what it holds. Nothing goes back once every action
the stopped retry put back to pending has completed, nor on an action a run has
reset since. The exception is a retry stopped while putting back the failures it
could not repair: those go back though every action has completed, since nothing
decided them again. And an action the stopped retry completed never gets back a
failure recorded against the action as a whole, which would make the next
`agac run` run it again.

`--dry-run` puts nothing back and leaves the record of the stopped retry where it
is. The plan it shows counts what a retry would put back.

## Retrying an action that runs in batch mode

An action configured [`run_mode: batch`](../execution/run-modes.md) is repaired
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
