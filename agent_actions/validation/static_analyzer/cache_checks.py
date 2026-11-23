"""Prompt-caching checks: record data in a cached prompt and `{% cache_point %}` tags."""

import logging
from typing import Any

from jinja2.exceptions import TemplateSyntaxError

from .errors import FieldLocation, StaticTypeError, StaticTypeWarning

# Logged under the analyzer's module name, so its records keep one logger.
logger = logging.getLogger("agent_actions.validation.static_analyzer.workflow_static_analyzer")


class PromptCacheChecksMixin:
    workflow_config: dict[str, Any]

    def _check_prompt_caching_on_record_data(self) -> list[StaticTypeWarning]:
        """Warn, once per action, when an Anthropic action caches a prompt that differs per record.

        A cache mark is placed only on a prompt that is the same text, after the same
        tools, for every record; any other prompt is sent unmarked. The versions of one
        action share its prompt and schema, so they warn once, under the action's name.
        """
        from agent_actions.errors import (
            ConfigurationError,
            PromptValidationError,
            SchemaValidationError,
        )
        from agent_actions.prompt.cache_scope import (
            cache_point_use,
            record_reads_in_prompt,
            schema_dispatches,
        )

        warnings: list[StaticTypeWarning] = []
        warned: set[str] = set()
        for action in self.workflow_config.get("actions", []):
            if not isinstance(action, dict) or action.get("enable_prompt_caching") is not True:
                continue
            if action.get("model_vendor") != "anthropic":
                continue
            name = action.get("name", "<unnamed>")
            if action.get("is_versioned_agent") and action.get("version_base_name"):
                name = action["version_base_name"]
            if name in warned:
                continue
            try:
                if cache_point_use(action).count:
                    # Marked at its cache points; _check_cache_points says what it reads.
                    continue
                reads = record_reads_in_prompt(action)
                dispatches = schema_dispatches(action)
            except (
                ConfigurationError,
                PromptValidationError,
                SchemaValidationError,
                TemplateSyntaxError,
                OSError,
                ValueError,
            ) as exc:
                # A prompt, schema or seed file that does not load or parse is reported by
                # the checks that read it.
                logger.debug("Cannot read the prompt or schema of action '%s': %s", name, exc)
                continue
            reasons = []
            if reads:
                reasons.append(f"its prompt reads record data ({', '.join(reads)})")
            if dispatches:
                reasons.append(
                    f"its schema, sent as tools before the prompt, calls {', '.join(dispatches)}"
                )
            if not reasons:
                continue
            warned.add(name)
            warnings.append(
                StaticTypeWarning(
                    message=(
                        f"Action '{name}' has enable_prompt_caching on, but "
                        f"{' and '.join(reasons)}. The request can differ per record, so "
                        "the prompt is sent without a cache mark and is not cached."
                    ),
                    location=FieldLocation(agent_name=name, config_field="enable_prompt_caching"),
                    referenced_agent=name,
                    referenced_field="enable_prompt_caching",
                    hint=(
                        "To cache the prompt, move the record data out of the prompt text "
                        "into context_scope.observe, and give the action a schema with no "
                        "dispatch_task call. Observed fields are sent in the separate user "
                        "content, after the prompt."
                    ),
                )
            )
        return warnings

    def _check_cache_points(self) -> tuple[list[StaticTypeError], list[StaticTypeWarning]]:
        """Check, once per action, the `{% cache_point %}` tags of its prompt.

        An error where an Anthropic request could not carry them; a warning where they are
        not sent, or where the text before one may differ between the records meant to
        share it. Whether two records of one source hold the same value of an upstream
        action's field is not known at load, so such a read is named and left to the author.
        """
        from agent_actions.errors import (
            ConfigurationError,
            PromptValidationError,
            SchemaValidationError,
        )
        from agent_actions.llm.providers.anthropic import MAX_CACHE_BREAKPOINTS
        from agent_actions.prompt.cache_point import MAX_CACHE_POINTS
        from agent_actions.prompt.cache_scope import cache_point_use, schema_dispatches

        errors: list[StaticTypeError] = []
        warnings: list[StaticTypeWarning] = []
        seen: set[str] = set()
        for action in self.workflow_config.get("actions", []):
            if not isinstance(action, dict):
                continue
            name = action.get("name", "<unnamed>")
            if action.get("is_versioned_agent") and action.get("version_base_name"):
                name = action["version_base_name"]
            if name in seen:
                continue
            try:
                use = cache_point_use(action)
                dispatches = schema_dispatches(action) if use.count else ()
            except (
                ConfigurationError,
                PromptValidationError,
                SchemaValidationError,
                TemplateSyntaxError,
                OSError,
                ValueError,
            ) as exc:
                logger.debug("Cannot read the prompt or schema of action '%s': %s", name, exc)
                continue
            if not use.count:
                continue
            seen.add(name)
            location = FieldLocation(agent_name=name, config_field="prompt")
            vendor = action.get("model_vendor")

            def warn(message: str, hint: str, name: str = name, at: Any = location) -> None:
                warnings.append(
                    StaticTypeWarning(
                        message=message,
                        location=at,
                        referenced_agent=name,
                        referenced_field="prompt",
                        hint=hint,
                    )
                )

            if vendor != "anthropic" or action.get("enable_prompt_caching") is not True:
                why = (
                    f"agac places no cache marks for the vendor '{vendor}'"
                    if vendor != "anthropic"
                    else "enable_prompt_caching is not on"
                )
                warn(
                    f"Action '{name}': its prompt holds a cache point, but {why}. The prompt "
                    "is sent without the tag and nothing is marked for caching.",
                    "A cache point marks a request only for an Anthropic action with "
                    "enable_prompt_caching: true. For a vendor that caches a prompt's "
                    "beginning by itself, keeping the shared text first is all it takes.",
                )
                continue

            problem = None
            if use.count > MAX_CACHE_POINTS:
                problem = (
                    f"its prompt holds {use.count} cache points; a prompt may hold at most "
                    f"{MAX_CACHE_POINTS}. Anthropic takes {MAX_CACHE_BREAKPOINTS} cache "
                    "breakpoints in a request, and one is kept for the end of a prompt that "
                    "every record shares"
                )
            elif use.repeats:
                problem = (
                    "a cache point sits inside a loop, a macro or a block that captures its "
                    "text ({% set %}...{% endset %}, {% filter %}), where it can render more "
                    f"than once; a request takes at most {MAX_CACHE_BREAKPOINTS} cache "
                    "breakpoints"
                )
            if problem:
                errors.append(
                    StaticTypeError(
                        message=f"Action '{name}': {problem}.",
                        location=location,
                        referenced_agent=name,
                        referenced_field="prompt",
                        hint=(
                            "Keep one cache point after each long part that many records "
                            "share, at the top level of the prompt or in an {% if %}."
                        ),
                    )
                )
                continue

            minimum = (
                "Anthropic caches a marked prefix only from a minimum length (512 to 4,096 "
                "tokens, by model); a shorter one is sent uncached, with no error."
            )
            if dispatches:
                warn(
                    f"Action '{name}': its schema, sent as tools before the prompt, calls "
                    f"{', '.join(dispatches)}, so each record's request can begin differently "
                    "and its cache points are not marked.",
                    "Give the action a schema with no dispatch_task call to cache what its "
                    "records share.",
                )
            elif use.changing:
                warn(
                    f"Action '{name}': the text before its cache point reads "
                    f"{', '.join(use.changing)}, which differs on every request, so the "
                    "cache entry written there is never read.",
                    f"Move that after the last cache point. {minimum}",
                )
            elif use.per_record:
                warn(
                    f"Action '{name}': the text before its cache point reads "
                    f"{', '.join(use.per_record)}. A cache point is read only by a request "
                    "whose text before it is the same; agac cannot tell at load whether the "
                    "records of one source share these values.",
                    "Keep before a cache point only what the records share, such as a "
                    f"source field, and move a field that differs per record after it. {minimum}",
                )
        return errors, warnings
