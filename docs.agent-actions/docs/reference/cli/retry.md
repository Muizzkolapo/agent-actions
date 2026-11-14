---
title: retry Command
description: Retry the failed or exhausted records, from one action through the actions after it
sidebar_position: 9
---

# retry Command

The `retry` command runs the failed or exhausted records again, from one action through the actions after it. The command does not run the whole workflow again. Before you retry, use [`dispositions`](./dispositions) to see which records are stuck, and at which action.

```bash
agac retry -a <workflow-name> [options]
```

A retry takes the same lock as [`run`](./run.md#concurrent-runs). If a run or another retry of the workflow is in progress, the retry exits 1 with `Another run of workflow '<workflow>' is in progress`. `--filter` also takes the lock, because `--filter` rewrites dispositions, stored rows, the status file and the retry manifest. `--dry-run` writes nothing and does not take the lock.

## Options

| Option | Description |
|--------|-------------|
| `-a, --agent TEXT` | The name of the agent configuration file, without the path or the extension (required) |
| `--from TEXT` | The action to start the retry from. If you do not give this option, the retry starts from the earliest failure. |
| `--record TEXT` | Limit the retry to a single record (by `source_guid`) at the `--from` action |
| `--dry-run` | Show what the command would retry, and do not execute |
| `--abandon-in-flight` | Retry even when a batch was not collected, and abandon the results of that batch |
| `--filter ACTION:RECORD_ID` | Mark a failed record as filtered at `ACTION`, in place of a retry. Thus no retry selects the record again. You can give this option more than one time. The command records the exclusion and exits. The command runs nothing again and calls no LLM. See [Keep a record out for good](#keep-a-record-out-for-good) |
| `--reason TEXT` | The reason why the `--filter` records are filtered (required with `--filter`). The command stores this reason as the disposition reason of the records. |

## Examples

### See what would be retried

This command is always safe. Nothing executes:

```bash
agac retry -a my_workflow --dry-run
```

Nothing is stuck when there is no failed record, no failed action, and no batch that waits for collection. In this case, the command reports `No failed or exhausted records found. Nothing to retry.`

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

`--record` takes the identifier in the **Record ID** column of [`dispositions --quarantined`](./dispositions). The retry matches exactly that value.

## Exclude a record permanently {/* #keep-a-record-out-for-good */}

Some records fail in the same way on each attempt. Examples are a prompt that is too large
for the context window of the model, and a source record with nothing to extract. Each
`retry` selects such a record again. `--filter` removes the record from the workflow in
place of a retry. `--filter` does not change the other records:

```bash
agac retry -a my_workflow --filter extract_facts:3f9a1c2e-... --reason "scanned page, no text"
```

```
Filtered 1 record(s); no retry selects them again:
  extract_facts / 3f9a1c2e-...
Removed 1 tombstone row(s) their failure left in the actions below.
```

The command marks the record `filtered` at that action. This disposition is the same
disposition that the `on_false: filter` of a guard gives a record. The disposition has your
reason, and a detail that names `agac retry --filter` and the date.

After this, `retry` does not list the record, and the downstream actions treat the record
as absent. The command removes what the failure of the record cascaded into the downstream
actions: their `unprocessed` row and their tombstone. Thus the downstream actions hold
nothing for the record, which is what they would hold under the guard. The action where the
record failed keeps its tombstone. Thus a later run of that action carries the record as it
is, and does not answer the record again.

`--filter` only records the exclusion. To retry the records that are still failed, run
`agac retry` after `--filter`. Give `--filter` one time for each record. Use the action in
the **Action** column of [`dispositions --quarantined`](./dispositions), and the ID in its
**Record ID** column. `--dry-run` lists the records that the command would filter, and
writes nothing.

Each record must be failed or exhausted at the action that you name. If a record is not
failed or exhausted there, the command filters nothing. If the workflow does not have the
action, the command also filters nothing. The command names each target that it refused, and tells you where to find the
correct ID:

```
Error: Nothing was filtered:
  Record '3f9a1c2e-...' is unprocessed at 'summarize', and only a failed or exhausted record can be filtered. `agac dispositions -a my_workflow --action summarize --quarantined` lists those.
```

`--filter` does not accept `--from`, `--record` or `--abandon-in-flight`. `--filter` needs
`--reason`.

A filter stays until the action is reset. `agac run --fresh` answers the record again.

If each record of the input file of the record failed at that action, the action never
wrote the file. Thus the action holds no row to carry. The filter still applies to a retry
of other records. But a run that processes that file again answers the record again.
`agac run` and `agac retry` do this while the action is failed as a whole. In this case,
`--filter` shows a warning. To exclude the record permanently, remove the record from the
input in `agent_io/staging/`.

If a [retry was interrupted](#when-a-retry-is-interrupted), `--filter` also changes the
list of failures that the interrupted retry must restore. Thus the retry that resumes the
interrupted retry keeps the filter, and does not restore the failure.

## A retry runs the records it named, and only those

`retry` selects records by ID: the records that failed, or the single record that you give
to `--record`. The retry processes these records at each action that it runs again. The
retry processes no other records. These are the exceptions:

- A [file-granularity tool](#a-file-tool-runs-over-the-whole-file). The tool gets the whole
  of each file that the retry reaches. Downstream of the tool, the actions answer again each
  record whose row the tool wrote differently.
- A retry that [resumes a halted action](#a-retry-resumes-a-halted-action-in-full).
- An action that [failed as a whole](#an-action-that-failed-as-a-whole).

No other record of the input joins these records. A record limit
([`record_limit`](../configuration/defaults) or
[`AGAC_RECORD_LIMIT`](../configuration/)) keeps the first N records of an input file. But
the purpose of a limit is to decide how much new work to accept, and a repair accepts no new
work. A record that the retry did not name is not work that this run must do, even if the
record is far inside the limit.

[`file_limit`](../configuration/defaults), `--file-limit` and `AGAC_FILE_LIMIT` also do not
limit a retry. A retry finds the staged files that hold the records that it named, and
visits each of these files. The retry does not walk the directory and stop at N.

A retry is exempt from a limit, but the retry is not exempt from reading the limit. A value
that cannot be a limit at all, for example `AGAC_FILE_LIMIT=nonsense`, still fails a retry
while the workflow is assembled. The value fails any other command in the same way. An empty
variable is not such a value. An empty variable reads as unset.

The records that the retry did not name keep what they already had. The retry carries their
stored output rows into the rewritten file, and does not change their dispositions. Thus a
record that failed at an action that the retry runs again stays failed after the retry,
unless the retry also named it.

This rule is important because `retry` clears the disposition of a record before it runs the
record again. Without this rule, a retry that never reached a record would not leave the
record failed. The retry would leave no trace of the failure at all.

An action that turns one record into several records gives new identifiers to the new rows.
Thus the IDs of a retry match none of these rows. In place of an ID match, the retry resolves
these rows back to the record that they came from. The retry rewrites a row if the retry
named a record that is an input of that action, and one of these conditions is true:

1. The row carries the ID of that record.
2. The row lists only records that the retry named, as the inputs that produced the row
   (`producer_source_guids`).
3. The row names the record as its parent. This condition applies only if no *other* input
   of that action names the same record as its own parent.

The retry carries each other row. Thus, when the retry repairs a record whose row was split
in two, the retry replaces the two halves. The retry does not add two more rows next to them.

Such an action writes rows for a record that the retry repairs. Each downstream action gets
these rows for that record. Thus the retry also names these rows at the downstream actions.
Each downstream action answers each of these rows, in online mode or in batch mode, and
through any number of further splits. The retry takes these rows from what the action wrote
in this run, not from the record that a row names as its parent.

A downstream action can hold data for the rows that the new rows replaced. The data is the
tombstone of the record from the run that failed it. Or the data is the rows that the
downstream action built from the split rows that are gone. Before the downstream action runs, the retry
removes this data and its dispositions from the file of the downstream action. The retry
does not carry this data next to the new answers. Thus, after the retry, the downstream
actions hold an answer for each new row and nothing else for that record. The next
`agac run` has nothing left to do.

The producer list places a row when the parent of the row gives no useful information. A row
names the *original* staged record that it descends from, not the record that produced it
directly. Thus, when one such action feeds another, the rows of the second action name a
record that is no longer its input.

An action that reads a record and also an expansion over that same record has this shape
too. In this case, `dependencies` names both. The fan-in pairs each row of the expansion with
the record, so the input of the action is the rows of the expansion. In the two shapes, a
retry of one row of the first action replaces the rows that the second action made from it.

If the retry still cannot place a row, the retry carries the row and does not rewrite it.
These rows are:

- A row that lists no producers. A row that an earlier release stored may list no producers.
- A row made from a record that the retry named together with records that the retry did
  not name.

A file-granularity tool is not one of these cases. A retry rewrites the whole of a file that
it reaches ([below](#a-file-tool-runs-over-the-whole-file)). If the retry regenerates a row
that it carried, the file holds the previous row next to the new row.

The run reports how many rows it could not place. The run carries these rows and does not
guess, because a wrong guess here deletes a row that nothing will write again. The run
reports a carried row when a record that the run is repairing may have made it. The run also
reports a carried row that names no producer. The run carries a row that names other records as its producers
in the same way, but does not report that row.

The retry clears dispositions by the IDs that it got, at each action that it runs again. The
run decides the dispositions again at each action where it reaches the record. If an ID
names no input of an action, the retry does not find the ID there. Thus the retry runs
nothing again at that action. The exception is downstream of an action that split the record in this run.
There, the retry finds the new rows in place of the record, as described above.

If the run never repairs a record at its start action, the run reaches that record at no
action. These records are:

- A failure that an earlier release recorded under the target ID of a batch record.
- A failure written by hand.
- A record whose input file is gone.
- A record in a file that the action failed to process.
- Any of these records, when the action fails before it finishes.

If such a record was cleared and never decided again, it would lose its failures without a
repair. Thus the retry does these things for such a record:

- The retry restores what it cleared, at each action that did not decide the record again.
- The retry reads again an action that it had left complete, in the same way as a run reads
  it.
- The retry names the records (the first ten, and how many more):

```
1 record(s) named at 'summarize' were not in its input, so nothing repaired them
and their failures stand: t-3f9a1c2e. Retry selects a record by the source_guid
it arrives with. Where a record's input is gone, restore it as it was; an id no
input carries, such as a target id an earlier release recorded or one set by
hand, is cleared only by starting over with `agac run --fresh`.
```

The record can be in a file that the action failed to process, or the action did not
finish. In these cases, the retry tells you this cause in place of the message above. To
correct the cause, fix that error and run the retry again.

The run can find a record in a file that the run processed to the end. The retry does not
restore such a record, even if the action wrote nothing under the ID of the record. For
example, a file tool that rolls its input into rows that no single record produced answers
the record in that way.

A record can reach an action without a `source_guid`, for example from an upstream file that
someone edited by hand. This record has no ID to name. In the two run modes, the action
refuses the record before it sends the record to the model or to a record-level tool. The
record gets no disposition. The action stores the record as a failed row with no
`source_guid`. Thus `retry` does not list the record and does not repair it. The row keeps
the target ID of the record, unless the guard of the action skipped the record in an online
run.

If the other records of the action succeeded, the action reads complete. The failed row and
the run log tell what was refused. If nothing succeeded, the action fails. In the two run
modes, a retry of the other records of the action keeps that row as it was. To correct the
problem, go upstream: give the record its `source_guid` again where the record is produced.
A batch run that sends nothing at all refuses the record in the same way. Nothing in such a
run succeeds, so the action fails.

### A FILE tool runs over the whole file

A tool with `granularity: File` gets all records of a file at the same time. Thus each row
that the tool writes can depend on all of these records. Examples are a roll-up of the file,
a count or a rank across the file, and a dedupe. The unit of work of the tool is the file,
not the record.

Thus, when a retry reaches any record of a file at such a tool, the tool gets that whole file
again. The record can be a record that failed at the tool, or a record that the retry
repaired upstream of the tool. The tool gets each record of the file that the guard passes
and that is not still failed upstream. The retry replaces all of what the action held for
that file, which includes roll-up rows. The dispositions of the rows that the tool does not
write again go with them. The action decides each record of the file again, as a run decides
it.

If the retry names no record of a file, the file keeps what it holds, with no change. A
record that is still failed upstream stays quarantined, as in a run.

If the tool writes a row again exactly as it was, the row is the same row. The row keeps the
identifiers that it was stored under. What the downstream actions hold for the row stays.

Each downstream action of the tool answers a file that the tool rewrote, as a run answers
it. The downstream action answers each record whose row changed, whether the retry named
the record or not. The reason is that the downstream rows were computed from what the tool
wrote before. Also, no record that the retry names leads to the new row of a roll-up.

A record whose row the tool wrote again with no change keeps its downstream answer. Thus a
dedupe, or a tool that writes one row for each record, can write most of its rows as they
were. Then the only cost to the downstream actions is the records that changed.

A row that keeps the identity of its record is matched to the row stored under that
identity. Some rows get a new identity of their own in each run. Each row of a file gets a
new identity when the tool writes more rows for the file than the records that it answered.
A roll-up row also gets a new identity. Such a row is matched to the stored row that holds
the same content, which includes the records that the row was made from. The row then takes
back the identity of that stored row. Two rows of a file that hold the same content are never
matched, because nobody can tell which row was which. The downstream actions answer these
rows again.

A downstream FILE tool is the exception. Each of its rows may depend on all records of the
file. Thus the downstream FILE tool keeps its data only if the file was written again as the
rows that it held, all unchanged. In all other cases, the downstream FILE
tool gets the file again. The plain `agac run` that finishes a retry that stopped part-way
through does the same.

The plan tells you this before the retry clears anything. For each FILE tool that the retry
reaches, the plan prints this note after the listed records:

```
  Note: 'roll_up' is a File tool, so the retry hands it every record of each file holding a record listed above, and what reads it (finalize, grand) answers again every record whose row it writes differently.
```

Some tools write each row from the whole file, for example a count across the file or a
roll-up. When one record changes, such a tool changes each row, and the downstream actions
answer the whole file again. Put such a tool as early in the workflow as the data allows.
Put it upstream of the actions that cost the most.

A record limit admits these records:

- The records that a run of the same config admits.
- The records that the retry names.
- Each record that a stored row of the file names, by its identity or as its parent.

Thus a retry under a smaller limit than the run that it repairs drops no record that holds a
row of its own there. A roll-up row names no record. Thus, under a limit, the roll-up that a
retry writes is the same as the roll-up that a run of the same config writes. The plain
`agac run` that finishes an interrupted retry gives the tool the whole file in the same way.

A human-in-the-loop (HITL) review also takes a whole file, but a retry shows the reviewer
only the records that the retry names. The row of a review belongs to the reviewed record.
The other records of the file already hold a decision of a reviewer. Thus these records keep
that decision, and the retry does not ask the reviewer about them again. Downstream of a FILE
tool that rewrote the file, the retry asks the reviewer again about each record whose row the
tool changed. The reason is that the data that the reviewer decided on is gone.

## A retry after a config edit

A retry answers the records that it names under the config as it is now. The retry does not
change the answers of the other records. An action that the retry runs again can be
[edited](./run#when-you-edit-the-workflow) after the action completed. In this case, the
retry does not answer all records under the edit, and tells you this:

```
extract_facts was edited since it completed (model). A retry answers only the records it
names and leaves the rest as they are: run again with --rerun extract_facts to answer every
record under the edit
```

The action keeps the stamp of its earlier answers. Thus each later `agac run` names the edit
again, until `agac run --rerun extract_facts` answers each record under the edit.

## An action that failed as a whole

Some failures belong to an action, not to a record of the action. These failures are:

- The action could not read its input.
- The store did not answer as the action started its work: when the action counted the rows
  that it held, or was set running.
- The store did not answer when the action counted those rows before it checked a batch that
  it submitted.
- The store did not answer when the rows that the action wrote were counted, after the action
  ran.

In online mode, if the store refuses to record the failure of a record, the action also
fails. No disposition says that the record failed. Thus the retry finds the failure of the
action itself (see [`run`](./run#parallel-execution)). A store error ends the run (see
[`run`](./run#parallel-execution)). The action is failed even if it stored its rows. Thus
nothing reads these rows before the action runs again.

In all of these cases, the action reads `failed`. The status file
(`agent_io/.agent_status.json`) records the error under its `error_message`, and
[`agac status`](./utilities#status) shows the error. If the action runs again and does not
fail, the action no longer carries the error.

`retry` runs such an action again in full, and each action after it. No record of the action
failed, so the retry has no records to narrow the action to. The plan of the retry names the
error and tells you this:

```
Retry Plan
  From action: note_direct
  Actions to re-run: note_direct → merge_direct → fanin_consumer → fanin_asymmetric → reduce_summary
  Action status: failed — disk I/O error
  Records to retry: 0
  The failure is note_direct's own, so the retry re-runs it without narrowing it to
  particular records.
```

This retry does the same work that `agac run` does to resume the action. Each of the two
commands finishes the workflow. Before you run either command, fix the error. If the store
could not record the failure at the time, the retry records it before the action runs again. The retry does this as the action would have, with the error from
its status. `--dry-run` shows the plan and writes nothing.

An action whose batch is still owed is the exception. The retry refuses to run until the
batch is collected ([below](#retrying-an-action-that-runs-in-batch-mode)).

## A retry needs every action it runs to hold an answer for every record

A retry carries what an action holds for the records that the retry did not name. This is
correct only when the action holds an answer for each of these records. Some actions did not
finish their last run. These actions hold no answer for the records that the run did not
reach:

- An action that was added after the last run.
- An action that `agac run --rerun` of something that it reads set back to pending.
- An action that an interrupt, a kill or an error stopped partway through its records.

A completed action whose stored output is gone also holds no answer. A retry that narrowed
such an action would complete the action without those answers. Then nothing would run the
action again.

This rule covers each action that the retry runs, not only the actions from its starting
point. The run behind the retry executes each action that is not complete, at any position.
Thus the rule also covers an action added next to the action that failed, which may run
before it.

Thus, if such an action is in the workflow, a retry that names records refuses to run, before
it clears anything:

```
1 action(s) hold no current answer for some of their records (enrich
(interrupted)). A retry answers only the records it names and carries what each
action holds for the rest, so it would complete them without those answers. Run
the workflow first — agac run -a my_workflow — then retry.
```

Run the workflow to finish those actions. Then retry. `--dry-run` reports the refusal, and
does not raise it.

The retry does not refuse a failed action if its last run reached each record and each record
failed. Each record holds its failure, and a retry exists to repair failures. The retry knows
this in these cases:

- Each record that the action got failed.
- Each input file failed on all of its records.
- For a batch action, each record that its batches sent with a `source_guid` holds an answer
  or a failure.

The retry refuses the action even then if the action still holds a row for a record that the
run did not reach. The reason is that a reset keeps the rows of an action until the action
writes again. Also, a file that failed before it was processed is not written. Thus a row in
that file would be carried permanently if its input no longer has the record, or now filters
it. A file in which each record failed is written with those failures after a reset, and
keeps no such row.

The retry refuses a failure that stopped partway. Examples are an error that ends a file at
one record, and a failure recorded before this release, which cannot say if it stopped
partway.

This check also does not refuse these actions:

- An action that an interrupted retry left unfinished. This action finished before that
  retry. Thus a new `retry` resumes the action, if no run has reset it since then.
- An action that holds a batch that nobody collected, and an action that reads it. The batch
  refusal below applies to these actions, and `--abandon-in-flight` gets past that refusal.

An action halted by `on_exhausted: raise` has its own way to continue, below.

## A retry resumes a halted action in full

An action halted by
[`on_exhausted: raise`](../validation/expectations.md#repairing-instead-of-observing)
stopped partway through its records. `agac run` leaves the action halted. To continue, use
`retry`. The halted action holds no answer, and no failure, for the records after the halt.
Thus a retry narrowed to the records that it names would complete the action without those
records.

A retry that starts at the halted action, with no `--record`, names no record. The retry runs
that action, and each action after it, on each record for which they hold no stored answer.
These records are the records after the halt and the records that failed. The plan of the
retry tells you this.

The retry keeps what the halted action answered in the file where it halted. The file was
never stored, but each answer was written down when it was given. The retry carries those
records, and does not ask for them again. A plain `retry` does this when the halt is the
earliest failure.

A retry clears the written-down answers only for the records whose failures it clears. A
record that keeps its `success` keeps its answer. Thus a record that was answered after a
`--rerun` replaced the stored file is answered again, as a plain run answers it. The retry
does not carry that record from the stored file that the rerun made stale.

```bash
agac retry -a my_workflow --from extract_facts
```

A retry that names no record obeys the limits as `agac run` does. Each action obeys
[`record_limit`](../configuration/defaults), `file_limit` and any value that overrides them.
If the stored limit of an action differs from the current limit, the action executes again
under the current limit.

Some retries name records and would clear a halt: a retry that starts before the halted
action, or a retry with `--record`. Such a retry refuses to run before it clears anything.
The retry names the retry that resumes the halted action:

```
1 action(s) hold no current answer for some of their records (extract_facts
(halted)). A retry answers only the records it names and carries what each
action holds for the rest, so it would complete them without those answers.
First resume extract_facts with a retry from it, which names no record and runs
it in full — agac retry -a my_workflow --from extract_facts — then retry.
```

Run that retry. Then run the retry that you wanted. `--dry-run` reports the refusal, and does
not raise it.

The retry does not refuse a halted action before the starting point of the retry, and leaves
that action halted. An action in the range of the retry that reads the halted action cannot
run while that action is halted. In this case:

- The retry skips the action, and the retry exits 1.
- The retry restores the failures that it cleared there, unrepaired.
- The notice names the halted action and the retry that resumes it
  (`agac retry --from <halted>`). That retry runs the skipped action again.

Before you run this retry, resume the halted action.

## When a retry is interrupted

Before a retry clears failures, the retry writes a snapshot of the failures that it will
clear. If the retry stops before its run reaches the end, the next `retry` restores these
failures. The next retry starts where the stopped retry started. Thus the records that the
stopped retry named are answered again from there.

The next retry restores the failures before it does anything else. Thus a retry that is then
refused has already restored them. The next retry keeps the snapshot of the stopped retry
until it writes its own snapshot. Thus a retry that is refused, or finds nothing to do,
leaves the stopped retry for the next `retry` to resume.

While the stopped retry is unfinished, a retry with `--from` below the start action of the
stopped retry refuses to run. The retry refuses before it restores anything. The reason is
that this retry would never reach the failures that it restores. The retry would also leave
the records that the stopped retry named unanswered, below what it ran again.

```
A retry from extract_facts was stopped before it finished, and a retry from summarize
starts below it, so it would not answer what that one named. Resume it first — agac
retry -a my_workflow — then retry from summarize if anything is still failed there.
```

An action that a later run moved forward keeps what it holds. Nothing is restored after each
action that the stopped retry set back to pending has completed. Nothing is restored on an
action that a run has reset since then. The exception is a retry that stopped while it
restored the failures that it could not repair. Those failures are restored even when each
action has completed, because nothing decided them again. An action that the stopped retry
completed never gets back a failure recorded against the action as a whole. Such a failure
would make the next `agac run` run the action again.

On any other action, the restored value replaces the row that the action holds. This is true
whoever wrote the row: the run of the stopped retry, or you by hand. Before the retry restores a value, the
retry lists each row that it will change. For each row, the list shows the value that the row
holds, and then the restored value. The retry also names the file that it reads the values
from. `--dry-run` also lists these rows.

```
The interrupted retry's snapshot replaces 1 row(s) changed since it was taken, each shown as live then restored:
  label / 9873aae5-ffca-5e5e-bf5c-daee1ed053b6: filtered (excluded_by_hand) -> failed (Error executing UDF 'mp_label': ValueError: mp_label refuses row-bad)
To keep a live value, edit its entry in .../agent_io/store/my_workflow/_retry_manifest.json before you retry.
```

To keep a row that you changed, give its entry in that file the same `disposition` and
`reason` as the live row. Then run `agac retry --dry-run` again. The row no longer shows in
the list, and the plan no longer counts it. A record excluded with
[`--filter`](#keep-a-record-out-for-good) does not need these steps. `--filter` changes that
file to match.

A retry can stop after an action that [splits records](#a-retry-runs-the-records-it-named-and-only-those)
wrote, but before the downstream actions ran. In this case, the retry has not yet removed
what the downstream actions held for the rows that the split replaced. An example is the
tombstone of the record. The next `retry` runs the split again over the rows that the
stopped retry wrote. Thus the next retry cannot see the replaced rows go.

The stopped retry keeps a note of the replaced rows next to its snapshot of the failures
(`_retry_repair_notes.json` in the store folder of the workflow). The next `retry` removes
these rows from each action that the stopped retry never completed, as the stopped retry
would have.

`--dry-run` restores nothing, and does not change the snapshot of the stopped retry. The plan
that `--dry-run` shows counts what a retry would restore.

## Retrying an action that runs in batch mode

The retry repairs an action configured with [`run_mode: batch`](../execution/run-modes.md)
in the same way, with one difference in timing. The retry submits a new batch that holds only
the records that it named. Then the retry pauses and asks to be run again. The next run
collects the batch. The records that the retry did not name are not in that batch. Thus
nothing answers them again.

A retry discards the list of the batches that the action already collected. These batches
are spent. If the retry kept them, the repair would get a finished batch. The repair would
not get the batch that the retry just submitted.

For the same reason, a retry refuses to run while a batch is still out at the provider:

```
1 batch job(s) not collected yet (batch_abc123 (summarize, in flight)). Their results
would be lost to this repair's own submission. Collect them first — run the workflow again —
then retry. If the provider no longer has them, pass --abandon-in-flight.
```

The batch that is already out owns the records that it was submitted for. A repair on top of
that batch would put a second batch over the same file. The batch that came back last would
win, and you would pay for the other batch, which is discarded. Run the workflow again to
collect the batch in flight. Then retry. A refused retry clears nothing. Thus the failures
that it would have repaired are still there to find.

`--dry-run` reports the refusal, and does not raise it. Thus the plan that you see is the plan
that would actually run.

The batch does not have to be out at the provider. The retry also refuses to run for a batch
that finished but whose results were never collected. A collect pass leaves this state when
it stops on an error. An example is when the provider drops the connection while the run
reads the results of a file. Then the action reads `failed`, the records of the file still
wait, and the finished batch is still in the registry. `retry` does not report this state as
nothing to retry. Run the workflow again to collect the batch. Then retry the records that are
still failed.

### A record left deferred after its batch was collected

A record waits as `deferred` while its batch is out. The run that collects the batch stores
the row of the record, and then writes its outcome. If the store refuses that write, the
record stays `deferred`. The run shows a warning that the record is still deferred after the
batch completed. The answer or the failure of the record is in the row that the run stored.

The next `agac run` or `agac retry` writes the outcome that the row shows, and submits nothing
again. The outcome is `success` for an answer, or `failed` or `exhausted` for a failure, with
the reason that the run gave. If its row holds the attempt count, an exhausted record reads as
collection writes it. The record reads `exhausted_after_{N}_attempts`, with the error as its
detail.

The system sends nothing for a record that the guard filtered, and the record does not wait
as `deferred`. The system marks the record `filtered` when its batch is submitted. Thus a
store that refuses the writes of the collect pass does not leave the record with nothing.

`agac run` and `agac retry` write a deferred outcome only after each batch of the action is
collected, and only for a record whose row is stored. Then a failure written in this way is
retried like any other failure. `retry` finds the failure in the same command. An action
whose batch is settled with a failure reads `completed_with_failures`. `--dry-run` writes
nothing, and counts those failures in its plan.

### When the batch cannot be collected

If the provider can still answer about the batch, collection is the way forward. This
includes when the batch has finished or failed, and the registry is not yet up to date.
Collection does not cover a batch that the provider no longer recognises at all, usually
because the batch expired. In this case, the entry reads in flight permanently. Each remedy
above needs an answer that will not come.

`--abandon-in-flight` continues anyway, and tells you what it costs:

```
Abandoning 1 batch job(s) not collected yet: batch_abc123 (summarize, in flight).
Whatever they return will not be collected. 3 record(s) waiting on them are marked failed
so a later retry can still reach them.
```

Those three records are the rest of the batch. They waited for results that will never
arrive. `retry` cannot find a record that is left waiting, but `retry` can find a failed
record. Thus the command marks these records failed. They do not join the repair that you
asked for. To retry them, run `agac retry` again.

With `--dry-run`, the command reports the same figures and writes nothing.

:::note[Run from Anywhere]
You can run this command from any subdirectory of your project.
:::
