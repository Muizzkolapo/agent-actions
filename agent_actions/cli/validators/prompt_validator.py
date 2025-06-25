"""
Prompt validation utilities.

This module provides utilities for validating prompt files and
ensuring they meet the required format and constraints.
"""

import re
import logging
from pathlib import Path
from typing import Dict, List, Set, Any, Optional, Tuple

# Assuming your BaseValidator is now in validators.base_validator
from .base_validator import BaseValidator
# Assuming PromptLoader and custom exceptions exist.
# PromptValidationError will no longer be raised by validate(), but its message format can inspire error strings.
# from agent_actions.cli.exceptions import (
#     PromptValidationError,
#     FileNotFoundError,
#     ValidationError
# )

logger = logging.getLogger(__name__)


class PromptValidator(BaseValidator):
    """
    Handles prompt validation operations by inheriting from BaseValidator.
    Validates all prompts in a given directory.
    """

    # Regular expression to match prompt sections
    _PROMPT_SECTION_PATTERN = re.compile(r'^#+\s+(.+?)$', re.MULTILINE)

    # Regular expression to match prompt identifiers
    _PROMPT_ID_PATTERN = re.compile(r'^```prompt:(\w+)$', re.MULTILINE)

    # Maximum prompt size in bytes
    _MAX_PROMPT_SIZE = 1024 * 100  # 100 KB

    # Helper methods can be static if they don't need cls or self
    @staticmethod
    def _find_prompt_sections_in_content(content: str) -> List[str]:
        """Find all prompt section titles in the content."""
        return [match.group(1) for match in PromptValidator._PROMPT_SECTION_PATTERN.finditer(content)]

    @staticmethod
    def _find_prompt_ids_in_content(content: str) -> List[str]:
        """Find all prompt IDs in the content."""
        return [match.group(1) for match in PromptValidator._PROMPT_ID_PATTERN.finditer(content)]

    @staticmethod
    def _find_duplicate_ids_in_list(ids: List[str]) -> Set[str]:
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

    def _read_prompt_file(self, prompt_file: Path) -> Optional[str]:
        try:
            return prompt_file.read_text(encoding="utf-8")
        except Exception as e:
            self.add_error(f"Failed to read prompt file '{prompt_file.name}': {e}.")
            return None

    def _check_prompt_id_duplicates(
        self,
        file_name: str,
        prompt_ids_in_file: List[str],
        all_prompt_ids_seen: Set[str],
    ) -> Tuple[Set[str], List[str]]:
        duplicate_ids_within_file = self._find_duplicate_ids_in_list(prompt_ids_in_file)
        if duplicate_ids_within_file:
            id_list = ", ".join(duplicate_ids_within_file)
            self.add_error(f"Duplicate prompt IDs found in file '{file_name}': {id_list}.")

        cross_file_duplicates = [
            pid for pid in prompt_ids_in_file if pid in all_prompt_ids_seen and pid not in duplicate_ids_within_file
        ]
        if cross_file_duplicates:
            id_list = ", ".join(cross_file_duplicates)
            self.add_error(
                f"Prompt IDs in file '{file_name}' duplicate IDs from other files: {id_list}."
            )
        return duplicate_ids_within_file, cross_file_duplicates

    def _run_prompt_format_check(self, content: str, file_name: str) -> None:
        try:
            format_error = self._validate_prompt_format_logic(content, file_name)
            if format_error:
                self.add_error(format_error)
        except Exception as e:
            self.add_error(f"PromptLoader validation or internal format check failed for '{file_name}': {e}.")

    def _validate_single_prompt_file(self, prompt_file: Path, all_prompt_ids_seen: Set[str]) -> int: # Returns num_prompts_in_file
        """
        Validates a single prompt file and adds errors/warnings to the instance.
        Updates all_prompt_ids_seen with IDs from this file if valid.
        Returns the number of valid prompts found in this file.
        """
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

            duplicate_ids_within_file, cross_file_duplicates = self._check_prompt_id_duplicates(
                prompt_file.name, prompt_ids_in_file, all_prompt_ids_seen
            )

            if not duplicate_ids_within_file and not cross_file_duplicates:
                all_prompt_ids_seen.update(prompt_ids_in_file)
                file_prompts_count = len(prompt_ids_in_file)

            self._run_prompt_format_check(content, prompt_file.name)

            logger.debug("Prompt file validation processed for: %s", prompt_file.name)

        except Exception as e:
            self.add_error(f"Unexpected error validating prompt file '{prompt_file.name}': {e}.")
            logger.error(
                f"Unexpected error validating prompt file '{prompt_file.name}': {e}",
                exc_info=True,
            )
            return 0

        return file_prompts_count if not (duplicate_ids_within_file or cross_file_duplicates) else 0


    def _validate_prompt_format_logic(self, content: str, file_name: str) -> Optional[str]:
        """
        Validates the format of a prompt file content.
        Returns an error message string if validation fails, None otherwise.
        (This is based on the original static method `validate_prompt_format`)
        """
        sections = self._find_prompt_sections_in_content(content)
        if not sections:
            # This might be a warning rather than an error depending on strictness
            # self.add_warning(f"No prompt sections found in file '{file_name}'.")
            pass # Covered by warning in _validate_single_prompt_file

        prompt_ids = self._find_prompt_ids_in_content(content)
        if not prompt_ids and sections: # Only an error if there are sections but no IDs
            return f"No prompt IDs found in file '{file_name}' despite sections being present."
        if not prompt_ids and not sections: # Empty or non-prompt file
             return None # Not an error, just nothing to validate

        if not content.strip().startswith('#') and sections: # Check only if sections imply it should be a prompt file
            return f"File '{file_name}' does not start with a markdown heading but contains prompt sections."

        # Check for balanced code blocks for prompts
        # A more robust check focuses on each prompt block:
        for match in self._PROMPT_ID_PATTERN.finditer(content):
            prompt_id = match.group(1)
            block_start_index = match.end()
            # Find the next '```' that closes this block
            block_end_index = content.find('```', block_start_index)
            if block_end_index == -1:
                return f"Unclosed prompt block for ID '{prompt_id}' in file '{file_name}'."
            
            prompt_content_inside_block = content[block_start_index:block_end_index].strip()
            if not prompt_content_inside_block:
                return f"Empty prompt content for ID '{prompt_id}' in file '{file_name}'."
        return None


    def validate(self, data: Any, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Validates all prompt files in the specified directory.

        Args:
            data (Path): The path to the prompt_store directory.
            config: Optional configuration (not used by this validator).

        Returns:
            bool: True if all prompt validations pass, False otherwise.
        """
        self.clear_errors()
        self.clear_warnings()

        if not isinstance(data, Path):
            self.add_error("Validation data must be a Path object pointing to the prompt directory.")
            return False
        
        prompt_dir: Path = data

        logger.info("Starting prompt validation for directory: %s", prompt_dir)

        if not self._ensure_path_exists(prompt_dir):
            self.add_error(f"Prompt directory not found: {prompt_dir}.")
            return False
        if not self._is_directory(prompt_dir):
            self.add_error(f"Prompt path is not a directory: {prompt_dir}.")
            return False

        all_prompt_ids_seen: Set[str] = set()
        stats = {
            'total_files_processed': 0,
            'files_with_errors': 0, # This will be implicitly len(self.get_errors()) related files
            'total_prompts_validated': 0
        }

        prompt_files = list(prompt_dir.glob('*.md'))
        if not prompt_files:
            self.add_warning(f"No .md files found in prompt directory: {prompt_dir}")
            # No files means no errors from file processing, so return True
            return True

        for prompt_file in prompt_files:
            stats['total_files_processed'] += 1
            # Store current error/warning count to see if this file added any
            errors_before_file = len(self.get_errors())
            
            prompts_in_file = self._validate_single_prompt_file(prompt_file, all_prompt_ids_seen)
            
            if len(self.get_errors()) > errors_before_file:
                stats['files_with_errors'] +=1 # Not a perfect count, but an indicator.
            
            stats['total_prompts_validated'] += prompts_in_file


        logger.info("Prompt validation complete for directory: %s. Stats: %s", prompt_dir, stats)
        # Errors and warnings are already added to self._errors and self._warnings

        return not self.has_errors()