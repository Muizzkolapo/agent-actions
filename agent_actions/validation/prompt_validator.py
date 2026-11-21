"""Prompt validation utilities for prompt files."""

import logging
import re
import time
from pathlib import Path
from typing import Any

from agent_actions.config.defaults import PromptDefaults
from agent_actions.logging.core.manager import fire_event
from agent_actions.logging.events import ValidationStartEvent
from agent_actions.prompt.handler import PromptLoader
from agent_actions.validation.base_validator import BaseValidator

logger = logging.getLogger(__name__)


class PromptValidator(BaseValidator):
    """Validates the prompt files it is given."""

    _PROMPT_SECTION_PATTERN = re.compile("^#+\\s+(.+?)$", re.MULTILINE)
    _MAX_PROMPT_SIZE = PromptDefaults.MAX_PROMPT_SIZE_BYTES

    @staticmethod
    def _find_prompt_sections_in_content(content: str) -> list[str]:
        """Find all prompt section titles in the content."""
        pattern = PromptValidator._PROMPT_SECTION_PATTERN
        return [match.group(1) for match in pattern.finditer(content)]

    @staticmethod
    def _find_prompt_ids_in_content(content: str) -> list[str]:
        """Find all prompt IDs in the content.

        Delegates to :meth:`PromptLoader.get_all_prompt_names` so the
        validator uses the same ``{prompt ID}`` pattern as the runtime
        loader — a single source of truth for prompt ID extraction.
        """
        return PromptLoader.get_all_prompt_names(content)

    @staticmethod
    def _find_duplicate_ids_in_list(ids: list[str]) -> set[str]:
        """Find duplicate IDs in a list."""
        seen = set()
        duplicates = set()
        for item_id in ids:
            if item_id in seen:
                duplicates.add(item_id)
            else:
                seen.add(item_id)
        return duplicates

    def _check_prompt_file_size(self, prompt_file: Path) -> bool:
        file_size = prompt_file.stat().st_size
        if file_size > self._MAX_PROMPT_SIZE:
            self.add_error(
                f"Prompt file '{prompt_file.name}' exceeds maximum size "
                f"({file_size} bytes > {self._MAX_PROMPT_SIZE} bytes)."
            )
            return False
        return True

    def _read_prompt_file(self, prompt_file: Path) -> str | None:
        try:
            return prompt_file.read_text(encoding="utf-8")
        except (OSError, ValueError, UnicodeDecodeError) as e:
            self.add_error(f"Failed to read prompt file '{prompt_file.name}': {e}.")
            return None

    def _check_prompt_id_duplicates(
        self, file_name: str, prompt_ids_in_file: list[str]
    ) -> set[str]:
        """Report IDs used twice in one file; a `$file.ID` reference lets other files reuse an ID."""
        duplicates = self._find_duplicate_ids_in_list(prompt_ids_in_file)
        if duplicates:
            id_list = ", ".join(duplicates)
            self.add_error(f"Duplicate prompt IDs found in file '{file_name}': {id_list}.")
        return duplicates

    def _run_prompt_format_check(self, content: str, file_name: str) -> None:
        try:
            format_error = self._validate_prompt_format_logic(content, file_name)
            if format_error:
                self.add_error(format_error)
        except (OSError, ValueError, TypeError) as e:
            self.add_error(
                f"PromptLoader validation or internal format check failed for '{file_name}': {e}."
            )

    def _validate_single_prompt_file(self, prompt_file: Path) -> int:
        """Validate a single prompt file and return the number of valid prompts found."""
        file_prompts_count = 0
        try:
            if not self._check_prompt_file_size(prompt_file):
                return 0
            content = self._read_prompt_file(prompt_file)
            if content is None:
                return 0
            sections = self._find_prompt_sections_in_content(content)
            prompt_ids_in_file = self._find_prompt_ids_in_content(content)
            if not sections:
                self.add_warning(f"No prompt sections found in file '{prompt_file.name}'.")
            duplicates = self._check_prompt_id_duplicates(prompt_file.name, prompt_ids_in_file)
            if not duplicates:
                file_prompts_count = len(prompt_ids_in_file)
            self._run_prompt_format_check(content, prompt_file.name)
            logger.debug("Prompt file validation processed for: %s", prompt_file.name)
        except (OSError, ValueError, TypeError) as e:
            self.add_error(f"Unexpected error validating prompt file '{prompt_file.name}': {e}.")
            logger.debug(
                "Unexpected error validating prompt file '%s': %s",
                prompt_file.name,
                e,
                exc_info=True,
            )
            return 0
        has_errors = bool(duplicates)
        return 0 if has_errors else file_prompts_count

    def _validate_prompt_format_logic(self, content: str, file_name: str) -> str | None:
        """Return an error message if prompt format is invalid, None otherwise.

        Uses the same ``{prompt ID}``/``{end_prompt}`` token pair as
        :class:`PromptLoader` to detect unclosed or empty blocks.
        """
        sections = self._find_prompt_sections_in_content(content)
        prompt_ids = self._find_prompt_ids_in_content(content)
        if not prompt_ids and sections:
            return f"No prompt IDs found in file '{file_name}' despite sections being present."
        if not prompt_ids and not sections:
            return None
        if not content.strip().startswith("{") and not content.strip().startswith("#") and sections:
            return (
                f"File '{file_name}' does not start with a markdown heading "
                f"but contains prompt sections."
            )
        from agent_actions.prompt.handler import PROMPT_PATTERN

        end_token = "{end_prompt}"
        for match in PROMPT_PATTERN.finditer(content):
            prompt_id = match.group(1)
            block_start_index = match.end()
            block_end_index = content.find(end_token, block_start_index)
            if block_end_index == -1:
                return f"Unclosed prompt block for ID '{prompt_id}' in file '{file_name}'."
            block_content = content[block_start_index:block_end_index].strip()
            if not block_content:
                return f"Empty prompt content for ID '{prompt_id}' in file '{file_name}'."
        return None

    def validate(self, data: Any, config: dict[str, Any] | None = None) -> bool:
        """Validate each prompt file in *data*, a list of paths, once per file; *config* is unused."""
        self.clear_errors()
        self.clear_warnings()
        self._validation_target = self.validator_name
        self._validation_start_time = time.time()

        if self._fire_events:
            fire_event(
                ValidationStartEvent(
                    target=self._validation_target,
                    validator=self.validator_name,
                )
            )

        if not isinstance(data, list) or not all(isinstance(path, Path) for path in data):
            self.add_error("Validation data must be a list of prompt file paths.")
            return self._complete_validation()
        unique: dict[Path, Path] = {}
        for path in data:
            unique.setdefault(path.resolve(), path)
        prompt_files = list(unique.values())
        stats = {"total_files_processed": 0, "files_with_errors": 0, "total_prompts_validated": 0}
        for prompt_file in prompt_files:
            stats["total_files_processed"] += 1
            errors_before_file = len(self.get_errors())
            prompts_in_file = self._validate_single_prompt_file(prompt_file)
            if len(self.get_errors()) > errors_before_file:
                stats["files_with_errors"] += 1
            stats["total_prompts_validated"] += prompts_in_file
        logger.debug("Prompt validation complete. Stats: %s", stats)
        return self._complete_validation()
