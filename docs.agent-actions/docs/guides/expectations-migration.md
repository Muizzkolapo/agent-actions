---
title: Migrate a Check Chain to expect
description: Replace a hand-built verify, collect and rewrite chain with an expect block, and know when to keep the chain
sidebar_position: 6
---

# Migrate a Check Chain to `expect:`

Many workflows check an LLM output with a chain of actions. One action checks the output. A tool collects the verdicts. A third action rewrites the records that failed. This guide moves such a chain onto an `expect:` block. It also tells you when to keep the chain.

This guide uses only the keys that the [AI Expectations](../reference/validation/expectations.md) reference describes. Read that page for the full definition of each key.

## The Example Workflow {/* #the-example */}

The workflow extracts five fields from invoices. Each staging record has an `invoice_text` field. A tool action, `load_invoice`, cleans the text and writes it to its own output. The two versions of the workflow below both start with this tool. [The judge reads an upstream action](#the-judge-reads-an-upstream-action) tells you why.

```yaml
- name: load_invoice
  kind: tool
  impl: load_invoice_text
  intent: "Read and clean the invoice text"
  schema: invoice_text
  context_scope:
    observe: [source.invoice_text]
```

The `extract` action writes this schema in the two versions:

```yaml
# schema/invoice_fields.yml
name: invoice_fields
fields:
  - id: vendor_name
    type: string
    description: "The name of the company that issued the invoice."
  - id: invoice_number
    type: string
  - id: invoice_date
    type: string
    description: "The issue date, as YYYY-MM-DD."
  - id: total_amount
    type: number
  - id: currency
    type: string
    description: "The ISO 4217 code, for example EUR."
```

## Before: A Hand-Built Check Chain {/* #before */}

```yaml
- name: extract
  dependencies: [load_invoice]
  intent: "Extract the invoice fields from the invoice text"
  schema: invoice_fields
  prompt: $invoice.Extract
  context_scope:
    observe: [load_invoice.invoice_text]

- name: verify
  dependencies: [extract]
  intent: "Judge each extracted field against the invoice text"
  schema: field_verdicts
  prompt: $invoice.Verify
  context_scope:
    observe: [load_invoice.invoice_text, extract.vendor_name, extract.invoice_number, extract.total_amount]

- name: collect
  dependencies: [verify]
  kind: tool
  impl: collect_failures
  intent: "Gather the fields that failed the check"
  schema: failure_list
  context_scope:
    observe: [verify.*]

- name: rewrite
  dependencies: [collect]
  intent: "Extract the failed fields again"
  schema: invoice_fields
  prompt: $invoice.Rewrite
  context_scope:
    observe: [load_invoice.invoice_text, extract.*, collect.failed_fields]
  guard:
    condition: "collect.has_failures == true"
    on_false: skip
```

The `verify` prompt asks the model for one boolean for each field (`vendor_name_supported`, `invoice_number_supported`, `total_amount_supported`) and a `reason`. The `collect` tool turns these booleans into a list:

```python
from typing import Any

from agent_actions import udf_tool

CHECKED = ("vendor_name", "invoice_number", "total_amount")


@udf_tool()
def collect_failures(data: dict[str, Any]) -> dict[str, Any]:
    verdicts = data["verify"]
    failed = [name for name in CHECKED if not verdicts.get(f"{name}_supported")]
    return {"failed_fields": failed, "has_failures": bool(failed)}
```

This chain works, but it has these problems:

- **Four places name the same fields.** The `verify` prompt, the `field_verdicts` schema, the tool and the `rewrite` prompt each name them. If you add a field, you must change all four.
- **The rewrite has one attempt only.** Nothing checks the output of `rewrite`. A bad rewrite goes downstream.
- **The good output is in two actions.** A downstream action must read `rewrite` for some records and `extract` for the other records.
- **The verdict has no standard shape.** [`agac expect report`](../reference/cli/expect.md#expect-report) cannot count it, and CI cannot gate on it.
- **A model checks what code can check.** The date format and the currency code do not need a model call.

## After: One Action with an `expect:` Block {/* #after */}

```yaml
- name: extract
  dependencies: [load_invoice]
  intent: "Extract the invoice fields from the invoice text"
  schema: invoice_fields
  prompt: $invoice.Extract
  context_scope:
    observe: [load_invoice.invoice_text]
  expect:
    repair: auto
    max_iterations: 3
    on_exhausted: fail
    judge_budget: 300
    expectations:
      - id: vendor_name_present
        type: not_null
        field: vendor_name
      - id: invoice_number_present
        type: not_null
        field: invoice_number
      - id: total_amount_present
        type: not_null
        field: total_amount
      - id: date_is_iso
        type: matches_regex
        field: invoice_date
        params:
          pattern: '^\d{4}-\d{2}-\d{2}$'
        hint: "Write invoice_date as YYYY-MM-DD."
      - id: currency_is_known
        type: accepted_values
        field: currency
        params:
          values: [EUR, GBP, USD]
        hint: "Write currency as one of EUR, GBP or USD."
      - id: fields_match_invoice
        type: llm_judge
        field: [vendor_name, invoice_number, total_amount]
        params:
          votes: 3
          context: [load_invoice.invoice_text]
          rule: >
            The list holds the vendor name, the invoice number and the total
            amount, in that order. The invoice text states each value. An
            amount written in another format, such as 1,250.00 for 1250.0,
            passes.
        hint: "Copy the vendor name, the invoice number and the total from the invoice text."
```

The `verify`, `collect` and `rewrite` actions go away. Their schemas, their prompts and the tool also go away.

This is what each part does:

- **The `not_null` rules** stop an empty field before the judge sees it. See [the checklist](#checklist-before-you-switch).
- **`matches_regex` and `accepted_values`** are code rules. They cost no model call. They replace the parts of the old `verify` prompt that code can decide.
- **The `llm_judge` rule** replaces the `verify` action. The selector `[vendor_name, invoice_number, total_amount]` gives the judge one input: a list of the three values, in that order. The selector does not send the field names, so the rule text names the order. `votes: 3` runs three judge calls and takes the majority. A tie fails.
- **`context:`** sends the invoice text to the judge as grounding text.
- **`hint:`** tells the model how to correct a failed rule. `repair: auto` puts each failed rule, its detail and its hint in the repair prompt.
- **`repair: auto`** replaces the `rewrite` action. It generates the output of `extract` again, and runs all the rules again on each attempt.
- **`max_iterations: 3`** sets the total number of generations, with the first. Thus a record gets a maximum of two repairs.
- **`on_exhausted: fail`** stores a record that still fails as `exhausted`. Downstream actions do not get it, and `agac retry` can run it again. To keep the last attempt and filter it downstream, use `return_last` and a [guard](../reference/execution/guards.md) on `extract.expect.overall_pass == true`.
- **`judge_budget: 300`** sets the maximum number of real judge calls for this action in one run.

| Before | After |
|---|---|
| The `verify` action, its prompt and the `field_verdicts` schema | The `llm_judge` rule, and code rules for the checks that code can decide |
| The `collect` tool and the `failure_list` schema | The verdict that Agent Actions writes on the record under `expect` (`overall_pass`, `failed`, `outcomes`) |
| The `rewrite` action and its guard | `repair: auto`, with a `hint:` on each rule |
| One rewrite attempt | `max_iterations` |
| No decision for a failed rewrite | `on_exhausted` |
| Downstream reads `extract` or `rewrite` | Downstream reads `extract` only |

### The Judge Reads an Upstream Action {/* #the-judge-reads-an-upstream-action */}

A `context:` reference has the form `action.field`. The action must be upstream of the judged action, and the field must be in its declared output. A `context:` reference cannot name `source`. Preflight refuses it:

```
extract: fields_match_invoice: context reference 'source.invoice_text' names unknown action 'source'
```

For this reason, the example puts the invoice text in the output of `load_invoice`. If an upstream action already holds the text, reference that action. You do not need a new tool.

Agent Actions adds each `context:` reference of an inline list to the `context_scope.observe` of the action. In the example, the prompt also reads the text, so `observe:` lists it.

### Optional: Move the Rules to a Named Suite {/* #named-suite */}

Several actions can use the same rules. Put the rules in a file in the schema path:

```yaml
# schema/invoice_rules.yml
name: invoice_rules
expectations:
  - id: vendor_name_present
    type: not_null
    field: vendor_name
  - id: invoice_number_present
    type: not_null
    field: invoice_number
  - id: total_amount_present
    type: not_null
    field: total_amount
  - id: date_is_iso
    type: matches_regex
    field: invoice_date
    params:
      pattern: '^\d{4}-\d{2}-\d{2}$'
    hint: "Write invoice_date as YYYY-MM-DD."
  - id: currency_is_known
    type: accepted_values
    field: currency
    params:
      values: [EUR, GBP, USD]
    hint: "Write currency as one of EUR, GBP or USD."
  - id: fields_match_invoice
    type: llm_judge
    field: [vendor_name, invoice_number, total_amount]
    params:
      votes: 3
      context: [load_invoice.invoice_text]
      rule: >
        The list holds the vendor name, the invoice number and the total
        amount, in that order. The invoice text states each value. An
        amount written in another format, such as 1,250.00 for 1250.0,
        passes.
    hint: "Copy the vendor name, the invoice number and the total from the invoice text."
```

Then name the suite in place of the inline list:

```yaml
- name: extract
  dependencies: [load_invoice]
  intent: "Extract the invoice fields from the invoice text"
  schema: invoice_fields
  prompt: $invoice.Extract
  context_scope:
    observe: [load_invoice.invoice_text]
  expect:
    repair: auto
    max_iterations: 3
    on_exhausted: fail
    judge_budget: 300
    suite: invoice_rules
```

Obey these two rules:

- **The suite file holds the rules only.** `repair`, `max_iterations`, `on_exhausted` and `judge_budget` stay on the `expect:` block of the action.
- **List the `context:` references of a suite in `observe:` yourself.** Agent Actions does not add them for a named suite. The example already lists `load_invoice.invoice_text`.

You can also declare the rules on the fields of `invoice_fields.yml`. See [Rules in the schema file](../reference/validation/expectations.md#rules-in-the-schema-file).

### Check the Result {/* #check-the-result */}

1. Run `agac inspect -w invoice_extraction`. Preflight checks each rule, each parameter and each `context:` reference before any model call.
2. Run `agac expect list -w invoice_extraction -A extract`. The command prints the rules that will run. The inline list and the named suite print the same rules.
3. After a run, run `agac expect report -w invoice_extraction`. The report shows which rule fails most often.

## When Not to Migrate {/* #when-not-to-migrate */}

An expectation judges the output of one record against a written rule. Use this test: can a careful reader decide the rule from this one record and the rule text? If yes, use an expectation. If no, keep the tool or the chain of actions.

### A Comparison of Two Groups {/* #two-groups */}

A rule cannot measure the difference between a control group and a test group. No single field of one record holds that signal. Keep the actions that run each group and the tool that compares them.

### A Rule Across Records {/* #across-records */}

Duplicates, uniqueness in a file and coverage of a set are properties of a set of records. A rule sees one record only. Keep a tool at `granularity: file`. See [File-Level Tools](./custom-tools.md#file-level-tools).

### A Judge That Must Not See Part of the Record {/* #blind-judge */}

An expectation reads the record as it is. The judge can see each field that the selector and `context:` give it. If the judge must not see a reference value, or ids that show the reference value, build the hidden view in a tool first. Keep the tool and the check action after it. The bundled `agac-blind-verification` skill describes this pattern (see [`agac skills`](../reference/cli/skills.md)).

### A Check That a Tool Already Does Well {/* #tool-does-well */}

A deterministic tool that already gives the correct verdict needs no change. Keep it. To move its logic into a rule, use an [`@expectation_check`](../reference/validation/expectations.md#extending-with-your-own-checks).

### A Payload That Several Actions Compile {/* #compiled-payload */}

Some checks need a payload that several actions make together. For example, a tool joins the invoice header from `extract`, the line items from a second action and the vendor record from a third action. A rule reads one field selector from the output of its own action. A `context:` reference reads one field of one upstream action, with one level only. Neither of them builds a payload. Also, a repair generates only the action that holds the `expect:` block. If the defect is in the output of a different action, the repair cannot correct it. Keep the tool that compiles the payload and the check action after it.

### Cascading Repairs {/* #cascading-repairs */}

Sometimes a correction to one field makes other fields stale. For example, a `reconcile` action finds that the line items do not add up to `total_amount`. The correction can need a new run of the line-item action, and then a new run of `reconcile` and its check. A repair does not do this. It generates one action again, and it does not enter the DAG again. The dependencies, the guards and the `context_scope` of the action do not run again. Use a [loop](../reference/configuration/loops.md#loop-or-repair). A loop runs a branch of several actions again, and the next attempt reads what the checks found. You can also keep the hand-built chain.

## Checklist Before You Switch {/* #checklist-before-you-switch */}

1. **Calibrate the judge on known-good outputs in `warn` mode.** Collect 5 to 20 invoices whose extraction people already accept. Add 3 to 10 extractions that you know are bad for the reason that the rule targets. Run the rule with `repair: none` and `severity: warn` on these records:

   ```yaml
   - name: extract
     dependencies: [load_invoice]
     intent: "Extract the invoice fields from the invoice text"
     schema: invoice_fields
     prompt: $invoice.Extract
     context_scope:
       observe: [load_invoice.invoice_text]
     expect:
       repair: none
       judge_budget: 100
       expectations:
         - id: invoice_number_present
           type: not_null
           field: invoice_number
         - id: fields_match_invoice
           type: llm_judge
           field: [vendor_name, invoice_number, total_amount]
           severity: warn
           params:
             votes: 5
             context: [load_invoice.invoice_text]
             rule: >
               The list holds the vendor name, the invoice number and the total
               amount, in that order. The invoice text states each value.
   ```

   `repair: none` makes no repair round, so the calibration costs only the judge votes. Do not set `max_iterations` or `on_exhausted` with `repair: none`. Agent Actions refuses them. Read the results with `agac expect report`. Read the vote count in the `detail` of each outcome, for example `3/5 judge votes passed`. Change the rule to `error` only when the known-good outputs pass by a clear majority. If a known-good output fails, the rule is wrong. Change the rule text, not the outputs. Also run the old `verify` action on the same records. The two checks must fail the same records, or you must know why. The bundled `agac-expectations` skill has the full procedure in its `references/calibration.md` file. [`agac skills install`](../reference/cli/skills.md) copies it into your project.

2. **Put `not_null` before an `llm_judge` on the same field.** A missing field fails `not_null` with a clear reason. An empty field that has no `not_null` goes to the judge. The judge votes FAIL, and each repair round repeats the same failure at the cost of the judge votes. With a list selector, put a `not_null` rule on each field in the list. Note that `not_null` accepts a string of only spaces. To refuse it, add `matches_regex` with `pattern: '\S'`.

3. **Count the cost of the repair rounds.** Each judge rule can make `votes` × `max_iterations` judge calls for one record. In the example, that is 3 × 3 = 9 judge calls. Each repair round also makes one more call of the `extract` model. The old chain made one `verify` call for each record, and one `rewrite` call for each record that failed. Set `judge_budget` to about records × votes × `max_iterations`, plus a margin. Do not set it too low. When the budget is used up, Agent Actions marks each next judge outcome `skipped`. A skipped rule with `error` severity does not pass, so the record fails. To lower the cost, give the judge a less expensive model with the `model` parameter of `llm_judge`.

## See Also {/* #see-also */}

- [AI Expectations](../reference/validation/expectations.md): each key of the `expect:` block, and the [migration from `reprompt:`](../reference/validation/expectations.md#migrating-from-reprompt)
- [Loops](../reference/configuration/loops.md#loop-or-repair): when to run several actions again
- [`agac expect`](../reference/cli/expect.md): list the rules and report the verdicts
- [Guards](../reference/execution/guards.md): gate a downstream action on the verdict
- [Custom Tools](./custom-tools.md): tools for checks that stay hand-built
