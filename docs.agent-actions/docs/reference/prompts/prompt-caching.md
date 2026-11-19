---
title: Prompt Caching
sidebar_position: 3
---

# Prompt Caching

Prompt caching lowers the price of a prompt whose beginning is sent again and again. Agent Actions places cache marks for Anthropic actions that set `enable_prompt_caching: true`, online and in `run_mode: batch`. The model reads the same text with caching on or off. Caching changes the price and the latency only.

```yaml
defaults:
  model_vendor: anthropic
  enable_prompt_caching: true
```

## What Is Marked

Agent Actions marks a request in two places.

| Mark | Where | When |
|------|-------|------|
| The end of the prompt | After the last character of the rendered prompt, before the record content | The prompt is the same text for every record of the action |
| A cache point | Where the template holds `{% cache_point %}` | The template holds the tag |

A prompt that reads a per-record value, for example `{{ source.page_content }}`, is not the same text for every record. Without a cache point, such a prompt is sent unmarked and pre-flight warns about it. Fields listed in `context_scope.observe` are sent after the prompt and are never marked.

## Cache Points

Many records often share a long part of the prompt. For example, one source page produces one record for each question slot, and each record sends the whole page. Put `{% cache_point %}` after the shared part:

```markdown
{prompt Write_Question}
## PAGE
{{ source.page_content }}
{% cache_point %}
## THE SLOT
{{ slots.fact }}
{end_prompt}
```

Agent Actions sends the text before the tag as a separate content block with a cache mark. The records of one page send the same block. The first request writes the cache entry. A later request that begins with the same text reads the entry, at the cache price of the provider.

The rules of the tag:

- **The tag renders to no text.** A tag on a line of its own takes the line with it, as an `{% if %}` or `{% set %}` line does. A tag inside a line removes nothing else. `{%- cache_point -%}` strips whitespace as on any block tag. The rendered prompt is the text that the same template gives without the tag. `prompt_debug` and the prompt trace show that text.
- **A template may hold at most 3 cache points.** Anthropic accepts 4 cache breakpoints in a request. Agent Actions keeps one for the end of a prompt that every record shares. A fourth tag is a pre-flight error. A tag inside `{% for %}`, `{% macro %}`, `{% filter %}` or a `{% set %}...{% endset %}` block is also a pre-flight error, because it can render more than once. A tag inside `{% if %}` is accepted.
- **The tag works in an inline `prompt:` and in a prompt store file.** A tag inside markdown inline code (`` `{% cache_point %}` ``) or `{% raw %}` stays text.
- **Order the prompt from the most shared text to the least shared text.** A cache entry is read only by a request whose text before the mark is identical, byte for byte. The schema of the action is sent as tools, before the prompt, and is part of that text.
- **A tag with no text since the previous mark places no mark.** The API refuses an empty text block.

A prompt that every record shares can also hold a cache point. Such a prompt is marked at the tag and at its end.

### When the Tag Is Not Sent

| Case | Result |
|------|--------|
| `enable_prompt_caching` is `false` or unset | The tag is removed and nothing is marked. The request is the same request, byte for byte, as without the tag. Pre-flight warns. The tag does not turn caching on |
| The vendor is not `anthropic` | The tag is removed. The request is the same request, byte for byte, as without the tag. Pre-flight warns. A vendor that caches the beginning of a prompt by itself needs only the shared text first |
| The schema is chosen per record (`schema: dispatch_task(...)`) | The cache points are not marked, because the tools before the prompt can differ per record. Pre-flight warns |
| A repair call | The call keeps the marks of the first call when its prompt begins with the rendered prompt (`repair: auto`). A repair template that puts text before the prompt sends no mark |

### What Pre-flight Checks

Pre-flight reads the template, not the records. It reports:

- an error for more than 3 tags, or a tag in a loop, a macro or a block that captures its text;
- a warning when the tags are not sent (see the table above);
- a warning when the text before the last tag reads a value that differs on each request (`dispatch_task(...)`, `| random`, `lipsum()`);
- a warning when the text before the last tag reads a field of an upstream action or a per-record seed. Pre-flight cannot know if the records of one source share such a value. If they do not share it, the cache entry is never read. Pre-flight does not warn about `source` fields, seed data without `select_by`, or version variables.

## Limits of the Provider

These rules belong to Anthropic and can change. They were read on 2026-11-19 at [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) and [Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing).

- **A short prefix is not cached, and no error is returned.** The text before a mark, tools included, must reach a minimum length that depends on the model: 512, 1,024, 2,048 or 4,096 tokens. Look up your model's minimum on the provider's prompt caching page. A page of 4,000 to 5,000 characters is about 1,200 tokens, so it is cached on a model with a 512 or 1,024 token minimum and not on one with a 2,048 or 4,096 token minimum.
- **A cache entry lives 5 minutes.** Each read starts the 5 minutes again. Agent Actions does not send the 1-hour lifetime.
- **An entry can be read only after the response that writes it has started.** With `record_concurrency` above 1, requests of one page that start together each write the entry and none reads it. The requests that start later read it.
- **In a batch, cache hits are best effort.** Anthropic processes the requests of a batch at the same time and in any order, and reports hit rates from 30% to 98%. Agent Actions writes the records of one source next to each other in the batch file. Anthropic recommends the 1-hour lifetime for batches, which Agent Actions does not send.
- **A request accepts 4 cache breakpoints.** See [Cache Points](#cache-points).

## How to See That the Cache Is Read

An Anthropic response reports `cache_creation_input_tokens` (tokens written to the cache) and `cache_read_input_tokens` (tokens read from the cache). The first request of a page writes; a later request reads. If `cache_read_input_tokens` stays 0, the prefix is shorter than the minimum, or the text before the mark differs between the requests, or the requests are more than 5 minutes apart.
