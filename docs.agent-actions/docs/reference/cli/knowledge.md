---
title: knowledge Command
description: List, build and search the knowledge bases of a project
sidebar_position: 9
---

# knowledge Command

The `knowledge` commands list, build and search the knowledge bases that `agent_actions.yml` declares under `knowledge:`. An action searches a knowledge base with `context_scope.retrieve`. See [Knowledge Bases and Retrieval](../../guides/knowledge.md).

```bash
agac knowledge list
agac knowledge build [NAME] [options]
agac knowledge search NAME TEXT [options]
```

Each command reads the `knowledge:` section of `agent_actions.yml` and checks it as a run does. A problem in a base stops the command, and the error names the base and the key. A `NAME` that is not a base stops the command, and the error lists the bases.

## `knowledge list`

Print each knowledge base, its sources, its indexes and whether each index is built:

```bash
agac knowledge list
```

```
help_center: 3 source(s), index: keyword, fuzzy
  14 file(s), 120 database row(s)
  keyword: 9c1f0e2a7b3d4c55 (built)
  fuzzy: 41d8a6e0c2b7f913 (not built)
```

The command reads the source files to compute the digest of each index. It also reads the workflows: when a `retrieve` entry of a workflow uses the method `key`, the command shows the `key` index of that base too. It builds nothing and connects to no database. It counts the rows of a database source from its snapshot. A base that cannot be read prints `not built:` and the reason, and the command continues with the next base.

The command takes no options.

## `knowledge build`

Build the indexes of each knowledge base, or of the base `NAME`:

```bash
agac knowledge build
agac knowledge build help_center
agac knowledge build help_center --refresh --prune
```

```
help_center keyword: 9c1f0e2a7b3d4c55 (up to date)
help_center fuzzy: 41d8a6e0c2b7f913 (built)
```

The command builds an index only when no index file holds the digest of the current sources. Otherwise it prints `up to date`. It writes each index to a temporary file and renames the file, under a lock for the project. Thus a run that starts at the same time waits for the build, and reads a complete index.

The first build of a database source reads its rows and keeps them as a snapshot. A later build reads the snapshot, not the database.

### Options

| Option | Description |
|--------|-------------|
| `NAME` | The knowledge base to build. Default: each base |
| `--refresh` | Read the query of each database source again, and replace its snapshot. This is the only command that reads the query of an existing snapshot again: `agac run --refresh-input` does not |
| `--prune` | After the build, remove the index files of earlier digests. It keeps the current file of each index kind that the base declares or that a `retrieve` entry uses, `key` included. Refused while a run of the project is in progress |

The index files are in `.agac/knowledge/<base>/`. Old files stay until `--prune` removes them, so the stored matches of earlier runs can still be compared with their index. The command builds each index that the base declares, and the `key` index when a `retrieve` entry of a workflow uses the method `key`. A workflow that does not load is not read.

## `knowledge search`

Search the knowledge base `NAME` for `TEXT`, as a `retrieve` entry does:

```bash
agac knowledge search help_center "charged twice"
agac knowledge search help_center "pasword reset" --method fuzzy -k 3
agac knowledge search help_center "charged twice" --method keyword --method fuzzy --json
```

```
query: "charged" OR "twice"  index: 9c1f0e2a7b3d4c55  count: 2
1. knowledge/help_center/billing/duplicate-charges.md#1  score 7.4210  Billing > Duplicate charges
   Billing > Duplicate charges If you see two charges for one invoice, the first charge is often a pending authorization...
2. A-204  score 3.1187  Refund timelines
   Refund timelines A refund goes back to the card that paid the invoice...
```

The command builds a missing or old index first, as a run does. It prints the compiled query, the index digest and the count, then one entry for each match: the rank, the `id`, the score, the title and the first 160 characters of the text.

### Options

| Option | Description |
|--------|-------------|
| `NAME` | The knowledge base to search (required) |
| `TEXT` | The query text (required). Quote it when it holds spaces |
| `-k N` | The number of matches, from 1 to 50. Default: 5 |
| `--method M` | A search method: `keyword`, `all_words`, `phrase`, `fuzzy` or `key`. Give it more than one time to merge methods with equal weights. Default: `keyword`. The base must have the index of each method. `key` needs `id:` on each source and cannot be merged |
| `--json` | Print the output as JSON, in the shape that a `retrieve` step stores: `matches`, `count`, `query` and `index` |

The command takes no `where` and no limits other than `-k`. To test those, run the workflow and read the step with [`agac records`](./records.md):

```bash
agac records -w support_desk -A write_reply__help
```

## See Also

- [Knowledge Bases and Retrieval](../../guides/knowledge.md): declare a base and search it from an action
- [run](./run.md): `--rerun` after a knowledge base changes
