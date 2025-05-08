"""
Prompt validation utilities.

This module provides utilities for validating prompt files and
ensuring they meet the required format and constraints.
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Match

from agent_actions.handlers.prompt_handler import PromptLoader
from agent_actions.cli.exceptions import (
    PromptValidationError,
    FileNotFoundError,
    ValidationError
)

logger = logging.getLogger(__name__)


class PromptValidator:
    """Handles prompt validation operations."""
    
    # Regular expression to match prompt sections
    PROMPT_SECTION_PATTERN = re.compile(r'^#+\s+(.+?)$', re.MULTILINE)
    
    # Regular expression to match prompt identifiers
    PROMPT_ID_PATTERN = re.compile(r'^```prompt:(\w+)$', re.MULTILINE)
    
    # Maximum prompt size in bytes
    MAX_PROMPT_SIZE = 1024 * 100  # 100 KB
    
    @classmethod
    def validate_prompts(cls, prompt_dir: Path) -> None:
        """
        Validate that all prompts in the prompt store directory are unique
        and properly formatted.

        Args:
            prompt_dir: Path to the prompt_store directory.
            
        Raises:
            PromptValidationError: If the prompt directory does not exist or if prompt validation fails.
            ValidationError: If the prompt path is not a directory.
        """
        logger.info("Starting prompt validation", extra={
            'prompt_dir': str(prompt_dir)
        })
        
        # Check if directory exists
        if not prompt_dir.exists():
            error_msg = f"Prompt directory not found: {prompt_dir}"
            logger.error(error_msg)
            raise PromptValidationError(error_msg)
        
        if not prompt_dir.is_dir():
            raise ValidationError(f"Prompt path is not a directory: {prompt_dir}")
            
        # Track all prompt IDs across files to check for duplicates
        all_prompt_ids: Set[str] = set()
        errors: List[str] = []
        warnings: List[str] = []
        
        # Track stats for reporting
        stats = {
            'total_files': 0,
            'valid_files': 0,
            'files_with_errors': 0,
            'total_prompts': 0
        }
        
        # Validate each prompt file
        for prompt_file in prompt_dir.glob('*.md'):
            stats['total_files'] += 1
            
            try:
                # Check file size
                file_size = prompt_file.stat().st_size
                if file_size > cls.MAX_PROMPT_SIZE:
                    error_msg = (f"Prompt file '{prompt_file.name}' exceeds maximum size "
                                f"({file_size} bytes > {cls.MAX_PROMPT_SIZE} bytes)")
                    logger.error(error_msg)
                    errors.append(error_msg)
                    stats['files_with_errors'] += 1
                    continue
                
                # Read file content
                try:
                    content = prompt_file.read_text(encoding='utf-8')
                except Exception as e:
                    error_msg = f"Failed to read prompt file '{prompt_file.name}': {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    stats['files_with_errors'] += 1
                    continue
                
                # Check for valid prompt sections and IDs
                sections = cls._find_prompt_sections(content)
                prompt_ids = cls._find_prompt_ids(content)
                
                # Validate sections
                if not sections:
                    warning_msg = f"No prompt sections found in file '{prompt_file.name}'"
                    logger.warning(warning_msg)
                    warnings.append(warning_msg)
                
                # Validate prompt IDs
                
                # Check duplicates within file
                duplicate_ids = cls._find_duplicate_ids(prompt_ids)
                if duplicate_ids:
                    id_list = ", ".join(duplicate_ids)
                    error_msg = f"Duplicate prompt IDs found in file '{prompt_file.name}': {id_list}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    stats['files_with_errors'] += 1
                    continue
                
                # Check for previously seen prompt IDs (duplicates across files)
                cross_file_duplicates = [id for id in prompt_ids if id in all_prompt_ids]
                if cross_file_duplicates:
                    id_list = ", ".join(cross_file_duplicates)
                    error_msg = (f"Prompt IDs in file '{prompt_file.name}' duplicate IDs "
                                f"from other files: {id_list}")
                    logger.error(error_msg)
                    errors.append(error_msg)
                    stats['files_with_errors'] += 1
                    continue
                
                # Add IDs to the set of all IDs
                all_prompt_ids.update(prompt_ids)
                
                # Use the existing PromptLoader validator as a final check
                try:
                    PromptLoader.validate_unique_prompts(prompt_file.name, content)
                except Exception as e:
                    error_msg = f"PromptLoader validation failed for '{prompt_file.name}': {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    stats['files_with_errors'] += 1
                    continue
                
                # File passed validation
                stats['valid_files'] += 1
                stats['total_prompts'] += len(prompt_ids)
                logger.debug(f"Prompt file validation successful for: {prompt_file.name}")
                
            except Exception as e:
                error_msg = f"Unexpected error validating prompt file '{prompt_file.name}': {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
                stats['files_with_errors'] += 1
        
        # Report validation results
        logger.info("Prompt validation complete", extra={
            'prompt_dir': str(prompt_dir),
            'total_files': stats['total_files'],
            'valid_files': stats['valid_files'],
            'files_with_errors': stats['files_with_errors'],
            'total_prompts': stats['total_prompts']
        })
        
        # If there were errors, raise an exception with details
        if errors:
            error_summary = (f"Prompt validation failed with {len(errors)} errors "
                           f"across {stats['files_with_errors']} files:\n" + "\n".join(errors))
            if warnings:
                error_summary += f"\n\nWarnings:\n" + "\n".join(warnings)
                
            raise PromptValidationError(error_summary)
        
        # Log warnings
        if warnings:
            warning_summary = "\n".join(warnings)
            logger.warning(f"Prompt validation warnings:\n{warning_summary}")
    
    @classmethod
    def _find_prompt_sections(cls, content: str) -> List[str]:
        """
        Find all prompt section titles in the content.
        
        Args:
            content: The file content to search.
            
        Returns:
            List of section titles.
        """
        return [match.group(1) for match in cls.PROMPT_SECTION_PATTERN.finditer(content)]
    
    @classmethod
    def _find_prompt_ids(cls, content: str) -> List[str]:
        """
        Find all prompt IDs in the content.
        
        Args:
            content: The file content to search.
            
        Returns:
            List of prompt IDs.
        """
        return [match.group(1) for match in cls.PROMPT_ID_PATTERN.finditer(content)]
    
    @staticmethod
    def _find_duplicate_ids(ids: List[str]) -> Set[str]:
        """
        Find duplicate IDs in a list.
        
        Args:
            ids: List of IDs to check.
            
        Returns:
            Set of duplicate IDs.
        """
        seen = set()
        duplicates = set()
        
        for id in ids:
            if id in seen:
                duplicates.add(id)
            else:
                seen.add(id)
                
        return duplicates
    
    @classmethod
    def validate_prompt_format(cls, content: str, file_name: str) -> Optional[str]:
        """
        Validate the format of a prompt file.
        
        Args:
            content: The file content to validate.
            file_name: Name of the file for error reporting.
            
        Returns:
            Error message if validation fails, None if successful.
        """
        # Check for prompt sections
        sections = cls._find_prompt_sections(content)
        if not sections:
            return f"No prompt sections found in file '{file_name}'"
        
        # Check for prompt IDs
        prompt_ids = cls._find_prompt_ids(content)
        if not prompt_ids:
            return f"No prompt IDs found in file '{file_name}'"
        
        # Check for proper markdown formatting
        if not content.strip().startswith('#'):
            return f"File '{file_name}' does not start with a markdown heading"
        
        # Check for balanced code blocks
        code_block_starts = content.count('```prompt:')
        code_block_ends = content.count('```', code_block_starts)
        if code_block_starts != code_block_ends / 2:
            return f"Unbalanced prompt code blocks in file '{file_name}'"
        
        # Check for proper prompt format (each ID should be followed by text and a closing ```)
        for match in cls.PROMPT_ID_PATTERN.finditer(content):
            prompt_id = match.group(1)
            start_pos = match.end()
            
            # Find the next ```
            end_marker = content.find('```', start_pos)
            if end_marker == -1:
                return f"Unclosed prompt block for ID '{prompt_id}' in file '{file_name}'"
            
            # Check if there's content between the ID and end marker
            prompt_content = content[start_pos:end_marker].strip()
            if not prompt_content:
                return f"Empty prompt content for ID '{prompt_id}' in file '{file_name}'"
        
        return None  # No errors found