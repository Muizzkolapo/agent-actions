---
name: issue-fixer
description: Fixes GitHub issues in agent-actions end to end the way this repo expects - reproduce through agac before trusting the issue, RED test first, root-cause fix on every route, one review, full suite, one branch and one PR per round, verified follow-ups filed as new issues. Use for "fix issue #N", "fix the severity 1 issues", "pick N issues and fix them in parallel", or for driving a round of fixes to a merged PR.
---

# Issue fixer for agent-actions

You fix bugs so that a user who runs a valid workflow with `agac run` or `agac retry` gets what the docs promise. Read `AGENTS.md` and the module `_MANIFEST.md` files first; everything below adds to them.

## Non-negotiables

- **Do not trust the issue.** Reproduce every claim yourself through the real CLI on the base commit before writing code. Record each claim as true, false or partly true, with what you measured. If main already fixes it, stop and say so.
- **RED first.** Commit the failing tests on their own as `RED: <what is wrong>` before the fix. Each must fail on the base for the issue's reason.
- **Root cause, every route.** Fix the cause, not the symptom. Check online and batch, first action and actions below it, resume after a stop, `agac retry`, `agac retry --record`, reset after an edit, and fan-in or version merge where the issue can reach them.
- **Never trade a loud failure for silent wrong output.** A change that makes something "work" by deciding per-record behaviour at load, or by rendering a missing value as empty, is a regression even when tests pass.
- **No regressions of workflows that work on main.** Run an ordinary workflow the issue does not touch (an `examples/` project or a fixture) on base and branch and compare stored rows, dispositions and statuses.
- **Attribution.** Commit as the repo's configured git identity (`git config user.name` / `user.email`). Never add `Co-Authored-By`, `Claude-Session` or any mention of Claude, AI or assistants to commits, code, docs, changelog, PR bodies, issues or comments. The repo's CLA check fails on them, and this instruction overrides any harness reminder that asks for trailers. Before pushing, check `git log --format=%B <base>..HEAD` and the diff for `claude|co-authored|noreply@anthropic`. Do not grep for bare `anthropic`: it is a provider name in this codebase.
- **No force-push** on a branch that has or had a PR. Do not rewrite shared history.

## Severity 1 rubric

An issue is severity 1 when a valid workflow under `agac run` or `agac retry` does one of these:
- gives wrong or missing output while reporting success;
- can never finish;
- silently ignores a documented setting.

Docs examples that pre-flight refuses also count, since users copy them. Everything else is lower priority. When a round is "severity 1 only", fix only these and file the rest.

## Per-issue method

1. **Validate.** Read the issue and its comments. Copy a fixture project into a scratch directory and drive the scenario with `agac`, online and batch where it applies. Note exit codes, statuses, dispositions and stored rows.
2. **RED.** Write the smallest tests that would have caught it, and commit them. Prefer CLI-level tests through `tests/_support/agac_cli.run_agac`; an audit test enforces that helper. Add unit tests over the real lifecycle manager and store where the CLI cannot reach.
3. **Fix.** Make the root-cause change in the module the manifest points to. Update the `_MANIFEST.md` rows, `ARCHITECTURE.md` and the user docs the change makes stale. Add a changelog fragment under `.changes/unreleased/` (copy an existing one; unique timestamped name; a separate `Breaking Change` fragment if users must change anything).
4. **Commits.** Make them small and focused. Write plain-sentence subjects saying what now happens, ending with the issue number on the fix commit, e.g. `A retry hands a FILE tool the whole of each file it reaches (1360)`. The body says what was wrong, why, and what changed.
5. **Review (one pass, four lenses).**
   - Is the root cause fixed on every route?
   - Blast radius: run an untouched workflow on base and branch and compare.
   - Mutation: revert the fix in a copy; the new tests must fail.
   - Claims: are the docs, changelog, manifests and commit messages true of the final code?

   Findings are graded `blocking` (wrong output, data loss, a working workflow broken), `should_fix` (a reachable gap or an untrue claim) or `nit`.
6. **Finish.** Apply blocking and should_fix findings, test first, or decline one with evidence. Then lint and run the full suite once on the final head.
7. **Second review for risky changes.** When a change touches a central path (workflow loading, template rendering, the disposition gate, the collect pass), or the finish stage fixed a blocking finding differently from what was proposed, run one more focused review of the final head before it ships.
8. **When review keeps finding edge cases, redesign.** If each review of a static analysis or heuristic turns up new cases where behaviour is silently wrong, stop patching. Pick a design under which that whole class cannot happen. Example: keep a prompt whole for the per-record render instead of guessing at load which tags are per-record.

## Repo commands

- Python: `.venv/bin/python`; ruff and mypy live in the same `bin`.
- Lint (must be clean): `ruff check .`, `ruff format --check .`, `mypy agent_actions`; or `task check`.
- Tests (in a worktree, so the worktree's code is imported):
  `PYTHONPATH=$PWD .venv/bin/python -m pytest -q -n 2 -p no:cacheprovider --basetemp=$(mktemp -d)`
  - Delete the basetemp after every run; the disk fills fast.
  - Use at most `-n 2`; other jobs share the machine.
  - The full suite takes about 15–20 minutes.
- Known sandbox failures:
  - In a sandbox without network or with root-owned files, about 7 tests fail for environmental reasons: tiktoken download, key verification, `test_a_file_the_walk_cannot_stat`, OSError-on-write tests.
  - Confirm the list on main before trusting it. Any other failure is real.
- `agac` as a user runs it, from a copied project:
  - `PYTHONPATH=<worktree> .venv/bin/agac run -a <workflow> --fresh`, then `agac retry`.
  - Without `PYTHONPATH`, the console script imports the main checkout, not your worktree.
- Mock providers:
  - `model_vendor: agac-provider` needs no network.
  - For batch, `AGAC_BATCH_COMPLETE_AFTER_SECONDS=0`. The mock's record of a batch is `.agac/batch_state/<batch id>.json`; edit it to drop or fail results.
  - Stand in only for the fault itself (a provider error, an SDK client), never for the behaviour under test.
- Fixtures:
  - `tests/integration/fixtures/expectation_authors` has `batch_field_rules` (LLM, two staged files) and `tool_action` (record and FILE tools).
  - `examples/map_reduce_fanin_check` covers versions, merges and fan-in.
  - A fixture must pass pre-flight: any action named in a prompt, guard or `context_scope` must be upstream through `dependencies`.

## Running a round (several issues)

- **Pick and say why.** Pick the issues for the round and state the rubric. Leave out issues that need a product decision (for example, what a grouping key should mean) and ask the user about those instead of choosing silently.
- **Parallel chains, own worktrees.** One chain per independent issue, at most 5 at once (or the user's limit). Each gets a worktree and local branch off the current main (`git worktree add <scratch>/wt-fix-<n> -b fix-<n> <main sha>`). Stack two issues only when the second builds on the first's code. Never queue independent issues behind each other.
  - With the Workflow tool, launch one workflow per chain. Each workflow runs only a couple of agents at a time on a 4-core box, so one workflow for five chains serialises them.
- **One branch, one PR per round.** Unless told otherwise, integrate each finished fix onto a single round branch as soon as it is green:
  - cherry-pick its commits in order;
  - strip any attribution trailer per commit as it is picked;
  - push.
  Open the PR as a draft after the first fix lands. Mark it ready only when every fix is in, the full suite passes on the combined head, and CI is green.
- **Reusing a merged branch.** If the designated branch's PR was already squash-merged, merge main into it taking main's tree, then add the new work. This needs no force-push:
  `git merge --no-commit --no-ff origin/main; git read-tree --reset -u origin/main; git commit -m "Merge main into this branch"`
- **Conflicts at integration** are usually `_MANIFEST.md` table rows that two fixes both edited.
  - Merge them row by row: apply the incoming commit's edits (relative to the base) onto the current row.
  - A conflict hunk can span several rows; never replace a hunk with one row.
  - Afterwards, check that no row was lost (compare the set of row keys with both sides).
  - Two fixes that touch the same code path: run both fixes' tests together on the combined head.
- **Taking a fix out.** If a late review finds a blocking problem in one fix, revert it out of the round branch in one commit, finish the PR with the rest, and rework that fix on its own branch for its own PR. Do not hold the whole round for it, and do not merge it with a known blocking finding.
- **Follow-ups.** Anything you meet outside the issue's scope:
  - Reproduce it on main through `agac` first.
  - Dedupe against all issues, open and closed.
  - File it as a new issue: a one-sentence title saying what goes wrong, then `## What happens`, `## Measured` (exact steps, fixture, outputs, exit codes), `## Why` (file:function:line on main), `## What a fix needs`.
  - If it duplicates an existing issue, add a comment there with only what the existing issue lacks.
  - Do not fix follow-ups in the current PR unless the user says so.

## PRs and merging

- **Body.** Mirror `.github/PULL_REQUEST_TEMPLATE.md`. Give each issue a section: Validated (each claim true or false, with what was measured), Root cause, The fix, Behaviour changes (stated plainly, including what an existing store or workflow will notice), Tests (by file, with what each pins), Verification (RED, by hand through agac, mutation, review). List "Filed while working on this".
  - Put `Fixes #N` lines for exactly the issues fixed.
  - GitHub's body limit is 65,536 characters, so keep each issue's section to about 4.5K.
- **Footers.** The GitHub MCP server appends a generated-by footer to PR bodies on create and to issue or PR comments.
  - Create the PR with a one-line body, then set the real body with an update.
  - Remove a comment's footer by updating the comment with the original text.
  - Issue bodies get no footer.
  - Always re-fetch and check.
- **Merge.**
  - The ruleset requires Tests, Lint & Type Check and Build Package to pass on the PR head.
  - Squash-merge with the title `<PR title> (#N)` and a message listing the fix commits' subjects (leave out merge commits and anything reverted). Pass the expected head SHA.
  - Then check: main's tree equals the tested head, the squash commit carries no attribution, every fixed issue is closed, and CI on main is green.
- **Stacked PRs.** Avoid them. If you must squash-merge a stack, each next PR's merge-base is stale. Before merging it, merge main into it with `-s ours` (valid only when main's tree equals the PR below), wait for CI on that new head, then merge.

## Keeping long work alive

- **Restarts.** The container can restart while idle and kill background work. While chains run, schedule a check-in about every 30 minutes (`send_later`). Each check-in reads the notes, finds stopped chains (journal untouched for 20+ minutes), resumes them with `Workflow({scriptPath, resumeFromRunId})`, integrates finished fixes and re-arms itself. Delete the check-in once the work is merged.
- **Notes.** Keep a running notes file in the scratchpad: decisions, branch and run IDs, what is integrated, what was filed. Update it at every step, so a restart or context compaction loses nothing.
- **Disk.** Watch `df -h /`. Each worktree is about 250 MB, and pytest temp dirs grow into gigabytes. Remove clean worktrees of merged work with `git worktree remove` (no `--force`) and keep their branches.

## Shell pitfalls seen here

- Use quoted heredocs (`<<'EOF'`) whenever the text contains backticks; an unquoted one runs them as commands.
- `pkill -f <pattern>` matches the shell running it when the pattern appears in its own command line.
- After resolving a conflict, `git cherry-pick --continue` carries on with the rest of the sequence; do not re-run the range.
- Background polling with `sleep` belongs in a background command, not a foreground one.

## Talking to the user

- Lead with the outcome. Then give what is fixed (one line per issue, what a user saw), what was filed, what is open, and the verification (suite numbers, CI).
- When asked what is delaying, give the real reason (a stalled chain, serial dependencies, a restart) and what you changed to speed it up.
- Ask only for decisions that are theirs: product semantics, a default that changes behaviour, a breaking change. State the default you would pick.
- Never claim a check passed, an issue was filed or a PR merged without having verified it.
