# Calibrating a Rule

A rule that blocks good outputs costs money twice: the repair rounds, and the records you lose. Calibrate each new rule before it may block.

## 1 Collect known-good outputs

1. Take 5 to 20 outputs that people already accept as good. Examples: support-ticket summaries that an agent approved, invoice extractions that match the invoice, catalog descriptions already published.
2. Add 3 to 10 outputs that you know are bad for the reason the rule targets.
3. Keep them in a small staging file of a test workflow, not in the production staging folder.
4. Use real outputs only. A sandbox run (`agac run --sandbox`) generates fake outputs and fake judge verdicts. It shows that the rule is wired, not that the rule is right.

## 2 Run the rule in warn mode

```yaml
expect:
  repair: none
  expectations:
    - id: summary_states_only_ticket_facts
      type: llm_judge
      field: summary
      severity: warn
      params:
        votes: 5
        rule: >
          Every fact in the summary is stated in the ticket.
        context: [load_ticket.ticket_text]
```

`repair: none` checks and reports. It makes no repair round, so the calibration costs only the judge votes.

## 3 Read the votes

| Known-good outputs | Known-bad outputs | Decision |
|---|---|---|
| All pass with a clear majority | Most fail | Make it `error` |
| Some fail | — | The rule is wrong for your data. Read the dissent in `detail`, then change the rule text |
| All pass | Most also pass | The rule does not find the problem. Make it more specific, or use a code rule |

Look at the vote counts, not only pass or fail. A known-good output with 3 of 5 votes passes, but it is close to the line. Change the rule until the known-good outputs pass by a clear margin.

## 4 Only then let it block

1. Set `severity: error` and `repair: auto`.
2. Set `judge_budget` to about records × judge rules × `max_iterations`, plus a margin. One unit is one judged value; `votes` does not change the count.
3. After the first full run, compare the pass rate with the calibration. A much lower pass rate means that the production data differs from the samples, or that the field the judge reads is empty or wrong (Rule 3 of the skill).

## 5 Keep the samples

Run the calibration again after you change the rule text, the judge model or the action's prompt. A rule that passed the samples once can drift when the model changes.
