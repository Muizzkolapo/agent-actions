---
title: Prompt Caching
description: Send cache marks so that Anthropic reads a shared prompt prefix from its cache
sidebar_position: 3
---

# Prompt Caching

Prompt caching lowers the price of a prompt that starts with text that other requests also send. Agent Actions places cache marks for Anthropic actions that set `enable_prompt_caching: true`, online and in `run_mode: batch`. The model reads the same text with caching on or off. Caching changes the price and the latency only.

```yaml
defaults:
  model_vendor: anthropic
  enable_prompt_caching: true
```

A cache mark is the point at the end of a text block that the provider can cache. Anthropic calls it a cache breakpoint.

## What Is Marked {/* #what-is-marked */}

Agent Actions puts a cache mark in two places.

| Cache mark | Where | When |
|------------|-------|------|
| The end of the prompt | After the last character of the rendered prompt, before the record content | The prompt is the same text for every record of the action |
| A cache point | Where the template holds `{% cache_point %}` | The template holds the tag |

A prompt that reads a per-record value, for example `{{ source.page_content }}`, is not the same text for every record. Without a cache point, Agent Actions sends such a prompt with no cache mark, and pre-flight warns about it. Agent Actions sends the fields of `context_scope.observe` after the prompt, and never puts a cache mark on them.

:::warning[CAUTION]
A cache write costs more than a normal input token. For example, an Anthropic model can cost 1.25 times the input price for each token written to the cache (`cache_write` in [prices](../cli/usage.md)). A cache mark lowers the price only when other requests read the entry. Pre-flight does not warn about `source` fields. In an action where each source gives one record, a tag after `{{ source.page_content }}` writes one cache entry for each record, and no request reads it. The price goes up.
:::

## Cache Points {/* #cache-points */}

Many records often share a long part of the prompt. For example, one source page gives one record for each question slot, and each record sends the full page. Put `{% cache_point %}` after the shared part:

```markdown
{prompt Write_Question}
## PAGE
{{ source.page_content }}
{% cache_point %}
## THE SLOT
{{ slots.fact }}
{end_prompt}
```

Agent Actions sends the text before the tag as a separate content block with a cache mark. The records of one page send the same block. The first request writes the cache entry. A later request that starts with the same text reads the entry, at the cache price of the provider.

The rules of the tag:

- **The tag renders to no text.** The model reads the text that the same template gives without the tag:
  - A tag on a line of its own removes that line, as an `{% if %}` or `{% set %}` line does.
  - A tag after text on a line keeps the line break after it. `Page {{ fact }} {% cache_point %}` on one line, then `Slot` on the next line, gives `Page It rained. ` and `Slot` on two lines.
  - A tag inside a line removes no other text.
  - `{%- cache_point -%}` removes the whitespace on each side, as any block tag with `-` does.

  `prompt_debug` and the prompt trace show the text that the model reads.
- **A template may hold at most 3 cache points.** Anthropic accepts 4 cache marks in a request. Agent Actions keeps one for the end of a prompt that every record shares. A fourth tag is a pre-flight error. A tag inside `{% for %}`, `{% macro %}`, `{% filter %}` or a `{% set %}...{% endset %}` block is also a pre-flight error, because it can render more than one time. Pre-flight accepts a tag inside `{% if %}`.
- **The tag works in an inline `prompt:` and in a prompt store file.** A tag inside markdown inline code (`` `{% cache_point %}` ``) or `{% raw %}` stays text. The word `cache_point` without `{% %}` is text.
- **Order the prompt from the most shared text to the least shared text.** The provider reads a cache entry only for a request whose text before the cache mark is identical, byte for byte. Agent Actions sends the schema of the action as tools, before the prompt. The schema is part of that text.
- **A tag with no text after the previous cache mark puts no cache mark.** The API refuses an empty text block.
- **Record text cannot make a cache mark.** Agent Actions finds the cache points only when the template holds the tag. Record text is sent as it is.
- **A tag is not an edit.** Agent Actions removes the tag before it compares the action with the completed run. Thus, if you add or remove a tag, `agac run` does not run the action again. See [When you edit the workflow](../cli/run.md#when-you-edit-the-workflow).

A prompt that every record shares can also hold a cache point. Agent Actions puts a cache mark at the tag and at the end of such a prompt.

### When the Tag Is Not Sent {/* #when-the-tag-is-not-sent */}

| Case | Result |
|------|--------|
| `enable_prompt_caching` is `false` or unset | Agent Actions removes the tag and puts no cache mark. The request is the same request, byte for byte, as without the tag. Pre-flight warns. The tag does not enable caching |
| The vendor is not `anthropic` | Agent Actions removes the tag. The request is the same request, byte for byte, as without the tag. Pre-flight warns. A vendor that caches the start of a prompt automatically needs only the shared text first |
| The schema is selected per record (`schema: dispatch_task(...)`) | Agent Actions puts no cache mark at the cache points, because the tools before the prompt can be different for each record. Pre-flight warns |
| A repair call | The call keeps the cache marks of the first call when its prompt starts with the rendered prompt (`repair: auto`). A repair template that puts text before the prompt sends no cache mark |

### What Pre-flight Checks {/* #what-pre-flight-checks */}

Pre-flight reads the template, not the records. It reports:

- An error for more than 3 tags, or for a tag in a loop, a macro or a block that captures its text.
- A warning when Agent Actions does not send the tags (see the table above).
- A warning when the text before the last tag reads a value that is different for each request (`dispatch_task(...)`, `| random`, `lipsum()`).
- A warning when the text before the last tag reads a field of an upstream action or a per-record seed. Pre-flight cannot know if the records of one source share such a value. If they do not share it, no request reads the cache entry. Pre-flight does not warn about `source` fields, seed data without `select_by`, or version variables.

## Limits of the Provider {/* #limits-of-the-provider */}

These rules belong to Anthropic and can change. They were read on 2026-11-19 at [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) and [Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing).

- **The provider does not cache a short prefix, and it returns no error.** The text before a cache mark, tools included, must have a minimum length. The minimum is 512, 1,024, 2,048 or 4,096 tokens, as a function of the model. Find the minimum of your model on the prompt caching page of the provider. A page of 4,000 to 5,000 characters is about 1,200 tokens. A model with a minimum of 512 or 1,024 tokens caches it. A model with a minimum of 2,048 or 4,096 tokens does not.
- **A cache entry lives 5 minutes.** Each read starts the 5 minutes again. Agent Actions does not send the 1-hour lifetime.
- **A request can read an entry only after the response that writes it has started.** With `record_concurrency` above 1, the requests of one page that start at the same time each write the entry, and none reads it. The requests that start later read it.
- **In a batch, cache hits are best effort.** Anthropic processes the requests of a batch at the same time and in any order. It reports hit rates from 30% to 98%. Agent Actions writes the records of one source next to each other in the batch file. Anthropic recommends the 1-hour lifetime for batches. Agent Actions does not send it.
- **A request accepts 4 cache marks.** See [Cache Points](#cache-points).

## How to See That the Cache Is Read {/* #how-to-see-that-the-cache-is-read */}

`agac usage` shows the tokens of each action in the `Cache read` and `Cache write` columns. See [agac usage](../cli/usage.md). An Anthropic response also reports `cache_creation_input_tokens` (tokens written to the cache) and `cache_read_input_tokens` (tokens read from the cache). The first request of a page writes. A later request reads.

If `Cache read` or `cache_read_input_tokens` stays 0, find the cause in this list:

- The prefix is shorter than the minimum of the model.
- The text before the cache mark is different between the requests.
- The requests are more than 5 minutes apart.

## See Also {/* #see-also */}

- [Prompt Store](./prompt-store.md) - Write prompt templates
- [agac usage](../cli/usage.md) - See the tokens and the cost of a run
- [agac run](../cli/run.md) - Which changes are edits of a completed action
