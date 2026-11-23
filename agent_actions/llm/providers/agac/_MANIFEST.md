# AGAC Provider Manifest

## Overview

Claude-branded provider adapter (AGAC) with non-blocking clients and test helpers.

## Project Surface

| Symbol | File | Interaction | Config Key |
|--------|------|-------------|------------|
| `AgacBatchClient._write_state()` | `.agac/batch_state/{batch_id}.json` | Writes | — |
| `AgacBatchClient._load_state()` | `.agac/batch_state/{batch_id}.json` | Reads | — |
| `AgacBatchClient.release_batch()` | `.agac/batch_state/{batch_id}.json` | Deletes | — |
| `AgacBatchClient.discard_partial_writes()` | `.agac/batch_state/*.tmp` | Deletes | — |
| `AgacBatchClient.reset()` | `.agac/batch_state/` | Deletes | — |
| `rules_for` | `agent_config/{workflow}.yml`, `schema/{workflow}/{action}.yml` | Reads (through the expectation suite the run resolves) | `actions[].expect` |
| `observed_refs` | `agent_config/{workflow}.yml` | Reads | `actions[].context_scope.observe` |
| `Contract._report` | `agent_io/logs/` | Writes (one warning per action and field) | — |

## Modules

| Name | Type | Description | Signals |
|------|------|-------------|---------|
| `batch_client.py` | Module | Offline batch client for testing batch without a vendor. `prepare_tasks` adds the action's `Contract.to_task()` to each task, so collecting answers each one with the same rules as online. Records a submitted batch under `.agac/batch_state/` in the project so the run that collects it — a separate process, because submitting pauses and asks to be run again — can find it. Answers each task from the schema and prompt that task carries. A task's `model_config` holds only the settings the action sets, never a null. The record outlives the read: collecting hands bytes to a caller that has yet to write and evaluate them, and a re-run must find the same batch. It dies with the registry entry that names it. A batch with no readable record is reported `unknown` and taken as failed: nothing will come back for it. A task whose user message ends by offering answer shapes, as a side call's request may (a judge's does), is answered with one of them, seeded by that message; nothing in it names a kind of side call. | `llm.batch`, `llm.providers` |
| `contract.py` | Module | What a mock answer must meet beyond its schema. `Contract.for_request` reads the action's rules with `rules_for`, through the same suite resolution the run uses (`create_expectation_service_from_config`), less `llm_judge` rules and unregistered types; the record's context as the request sends it; and the action's `context_scope.observe`. `Contract.generate` builds each top-level field a rule names to meet its schema and rules (`enum` ∩ `accepted_values`, `matches_regex` and schema `pattern` through `regex_gen`, a negated pattern, `word_count_between`, `item_count`, `not_null`/`no_null_fields`, `field[*]` element rules), checks each field with the real registered check, then checks the whole record with the real `run_suite` and builds it again up to `TRIES` (20) times. An output field that an observe reference names exactly (`ns.field`, never `ns.*`, which in a loop holds the field being rewritten) copies that input when it meets the field's schema and rules. What still fails is logged once per action and field (`reset_reports` clears that), naming the constraints, and the best attempt is returned. `to_task`/`from_task` carry the rules and observe list on a batch task; the task's `user_content` is the context. With no rules, the answer is the plain generator's, plus any copied inputs. | `llm.providers`, `expectations` |
| `regex_gen.py` | Module | `generate(pattern, rng)` builds a string from a bounded regex subset: literals and escapes, `.`, `\d \w \s` and negations, `[...]` with ranges and negation, `? * + {m} {m,} {m,n} {,n}` (an unbounded repeat adds at most `UNBOUNDED_EXTRA`, 3), groups `( )`, `(?: )`, `(?P<name> )`, `|`, `^ $`. Anything else raises `UnsupportedPattern`. Written by hand, not on `re._parser`, which is private. The caller checks each result with `re`. | `llm.providers` |
| `client.py` | Module | Online client for Claude Code/AGAC interactions. In JSON mode the answer comes from `Contract.for_request(...).generate`. In text mode (`json_mode: false`) a prompt whose last non-empty line is only two or more JSON objects joined by ` or ` gets one of those objects back (seeded choice, string values replaced by generated sentences); that is how an `llm_judge` gets a verdict. Any other text prompt gets prose. `VENDOR_PARAMS` accepts any key and reads none, so a workflow switched to it keeps its `vendor_params`. | `llm.realtime`, `llm.providers` |
| `fake_data.py` | Module | Test helpers that simulate Claude responses. `offered_answer_shapes` reads the answer shapes a prompt's last line offers; `generate_offered_answer` returns one of them. A string schema with a `pattern` is built by `from_pattern` (through `regex_gen`, kept only when `re.search` matches and it fits the length bound), else as before. `sentence_of(n, rng)` is a sentence of exactly n words. `generate_openai_response` takes an optional `contract` that builds the record. A declared `minimum`/`maximum` (or `exclusiveMinimum`/`exclusiveMaximum`) wins over the field-name rules: the value is drawn uniformly inside the bound, on a `multipleOf` step when one is declared (a whole-number step for an integer); a one-sided bound is completed from 0 or 1000 away; name rules apply only to an unbounded field. A string outside its `minLength`/`maxLength` is padded with sentences or cut at a word boundary, a field-name value such as an email included; one of `KNOWN_FORMATS` keeps its format. | `tests`, `llm.providers` |

## Dependencies

| Package | Direction | Why |
|---------|-----------|-----|
| `expectations` | outbound | `contract.py` resolves the action's suite with `create_expectation_service_from_config`, runs single checks from `registry`, and checks the whole record with `runner.run_suite` |
| `utils` | outbound | `contract.py` checks a value against its field schema with `jsonschema_cache.checked_validator` |
