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
    """Validates all prompt files in a given directory."""

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
        self, file_name: str, prompt_ids_in_file: list[str], all_prompt_ids_seen: set[str]
    ) -> tuple[set[str], list[str]]:
        duplicates = self._find_duplicate_ids_in_list(prompt_ids_in_file)
        if duplicates:
            id_list = ", ".join(duplicates)
            self.add_error(f"Duplicate prompt IDs found in file '{file_name}': {id_list}.")
        cross_file = [
            pid
            for pid in prompt_ids_in_file
            if pid in all_prompt_ids_seen and pid not in duplicates
        ]
        if cross_file:
            id_list = ", ".join(cross_file)
            self.add_error(
                f"Prompt IDs in file '{file_name}' duplicate IDs from other files: {id_list}."
            )
        return (duplicates, cross_file)

    def _run_prompt_format_check(self, content: str, file_name: str) -> None:
        try:
            format_error = self._validate_prompt_format_logic(content, file_name)
            if format_error:
                self.add_error(format_error)
        except (OSError, ValueError, TypeError) as e:
            self.add_error(
                f"PromptLoader validation or internal format check failed for '{file_name}': {e}."
            )

    def _validate_single_prompt_file(self, prompt_file: Path, all_prompt_ids_seen: set[str]) -> int:
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
            duplicates, cross_file = self._check_prompt_id_duplicates(
                prompt_file.name, prompt_ids_in_file, all_prompt_ids_seen
            )
            if not duplicates and not cross_file:
                all_prompt_ids_seen.update(prompt_ids_in_file)
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
        has_errors = bool(duplicates or cross_file)
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
        """Validate all prompt files in the directory specified by data (Path)."""
        self.clear_errors()
        self.clear_warnings()
        self._validation_target = str(data) if isinstance(data, Path) else self.validator_name
        self._validation_start_time = time.time()

        if self._fire_events:
            fire_event(
                ValidationStartEvent(
                    target=self._validation_target,
                    validator=self.validator_name,
                )
            )

        if not isinstance(data, Path):
            self.add_error(
                "Validation data must be a Path object pointing to the prompt directory."
            )
            return self._complete_validation()
        prompt_dir: Path = data
        logger.debug("Starting prompt validation for directory: %s", prompt_dir)
        if not self._ensure_path_exists(prompt_dir):
            self.add_error(f"Prompt directory not found: {prompt_dir}.")
            return self._complete_validation()
        if not self._is_directory(prompt_dir):
            self.add_error(f"Prompt path is not a directory: {prompt_dir}.")
            return self._complete_validation()
        all_prompt_ids_seen: set[str] = set()
        stats = {"total_files_processed": 0, "files_with_errors": 0, "total_prompts_validated": 0}
        prompt_files = list(prompt_dir.glob("*.md"))
        if not prompt_files:
            self.add_warning(f"No .md files found in prompt directory: {prompt_dir}")
            return self._complete_validation()
        for prompt_file in prompt_files:
            stats["total_files_processed"] += 1
            errors_before_file = len(self.get_errors())
            prompts_in_file = self._validate_single_prompt_file(prompt_file, all_prompt_ids_seen)
            if len(self.get_errors()) > errors_before_file:
                stats["files_with_errors"] += 1
            stats["total_prompts_validated"] += prompts_in_file
        logger.debug("Prompt validation complete for directory: %s. Stats: %s", prompt_dir, stats)
        return self._complete_validation()
