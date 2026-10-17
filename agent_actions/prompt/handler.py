"""Prompt loading and validation from markdown files."""

import logging
import re
from collections import Counter
from pathlib import Path

import jinja2
from jinja2 import meta

from agent_actions.config.path_config import resolve_project_root
from agent_actions.config.paths import PathType
from agent_actions.utils.file_handler import FileHandler

logger = logging.getLogger(__name__)

# Compiled regex pattern for matching {prompt name} blocks.
# Supports dots in prompt names (e.g. {prompt file.block}) so that validate_prompt_blocks
# and get_all_prompt_names correctly handle dot-in-name references.
PROMPT_PATTERN = re.compile(r"\{prompt\s+([\w.]+)\}")

# A raw block, left as written, or a `{{ load_prompt("file.Prompt") }}` tag of its own.
_RAW_OR_LOAD_TAG = re.compile(
    r"(?P<raw>\{%-?\s*raw\s*-?%\}.*?\{%-?\s*endraw\s*-?%\})"
    r"|\{\{(?P<strip_before>-?)\s*load_prompt\(\s*(?P<q>['\"])(?P<name>[^'\"\n]+)(?P=q)\s*\)"
    r"\s*(?P<strip_after>-?)\}\}",
    re.S,
)


class PromptLoader:
    """Loads and validates prompts from markdown content."""

    @staticmethod
    def discover_prompt_files(project_root: Path | None = None) -> list[Path]:
        """Discover all prompt markdown files under ``prompt_store/``.

        Searches recursively so that prompts organised in subdirectories are
        found.  Returns a sorted list of ``.md`` file paths.
        """
        search_root = resolve_project_root(project_root)
        prompt_dir = search_root / PathType.PROMPT_STORE.value
        if not prompt_dir.exists():
            return []
        return sorted(prompt_dir.rglob("*.md"))

    @staticmethod
    def extract_prompt(content: str, prompt_name: str) -> str:
        """
        Extract a named prompt block from content.

        Raises:
            ValueError: If the prompt block is not found or unclosed.
        """
        start_token = f"{{prompt {prompt_name}}}"
        end_token = "{end_prompt}"
        start_index = content.find(start_token)
        if start_index == -1:
            raise ValueError(f"Prompt '{prompt_name}' not found in the content.")
        end_index = content.find(end_token, start_index + len(start_token))
        if end_index == -1:
            raise ValueError(f"Unclosed prompt block for '{prompt_name}'.")
        prompt_body = content[start_index + len(start_token) : end_index]
        return prompt_body.strip()

    @staticmethod
    def get_all_prompt_names(content: str) -> list[str]:
        """Return all prompt names found in the content."""
        return PROMPT_PATTERN.findall(content)

    @staticmethod
    def validate_unique_prompts(filename: str, content: str) -> None:
        """
        Raise ValueError if duplicate prompt names exist in content.
        """
        prompt_names = PromptLoader.get_all_prompt_names(content)
        duplicates = [item for item, count in Counter(prompt_names).items() if count > 1]
        if duplicates:
            raise ValueError(f"Duplicate prompt names found in {filename}: {', '.join(duplicates)}")

    @staticmethod
    def validate_prompt_blocks(filename: str, content: str) -> None:
        """Ensure every prompt block is properly closed with an end token."""
        end_token = "{end_prompt}"
        opens = [(m.start(), m.end(), m.group(1)) for m in PROMPT_PATTERN.finditer(content)]
        ends = []
        search_start = 0
        while True:
            idx = content.find(end_token, search_start)
            if idx == -1:
                break
            ends.append(idx)
            search_start = idx + len(end_token)

        end_iter = iter(ends)
        next_end = next(end_iter, None)

        for i, (open_pos, _open_end, name) in enumerate(opens):
            # Advance past any end_prompt that appears before this open
            while next_end is not None and next_end < open_pos:
                next_end = next(end_iter, None)

            next_open_pos = opens[i + 1][0] if i + 1 < len(opens) else len(content)

            if next_end is None or next_end > next_open_pos:
                raise ValueError(f"Unclosed prompt block for '{name}' in {filename}.")

            next_end = next(end_iter, None)

    @staticmethod
    def load_prompt(prompt_name: str, project_root: Path | None = None) -> str:
        """
        Load a prompt by name ('filename.prompt_key') from .md files in the project tree.

        Raises:
            ValueError: If the prompt file or prompt format is invalid.
        """
        if "." not in prompt_name:
            raise ValueError(
                f"Invalid prompt format: '{prompt_name}'. Expected 'filename.prompt_key' (with a dot separator)."
            )

        prompt_file_name, prompt_key = prompt_name.split(".", 1)
        target_filename = f"{prompt_file_name}.md"

        search_root = resolve_project_root(project_root)
        prompt_file_str = FileHandler.find_file_in_directory(str(search_root), target_filename)

        if not prompt_file_str:
            raise ValueError(
                f"Prompt file '{target_filename}' not found. "
                f"Searched recursively from {search_root}. "
                f"Ensure the .md file exists anywhere in your project tree."
            )

        logger.debug("Found prompt file at: %s", prompt_file_str)
        prompt_file_path = Path(prompt_file_str)
        content = prompt_file_path.read_text(encoding="utf-8")
        PromptLoader.validate_unique_prompts(prompt_file_path.name, content)
        PromptLoader.validate_prompt_blocks(prompt_file_path.name, content)
        return PromptLoader.extract_prompt(content, prompt_key)

    @staticmethod
    def load_prompt_expanded(
        prompt_name: str, project_root: Path | None = None, _chain: tuple[str, ...] = ()
    ) -> str:
        """Load a prompt with each `{{ load_prompt("...") }}` tag in it replaced by that prompt.

        The per-record render has no `load_prompt`, and Jinja would not render the text a
        call returns, so the loaded text goes in as written for that render to fill.

        Raises:
            ValueError: If a prompt cannot be loaded, the prompts load each other in a
                cycle, or a prompt calls `load_prompt` other than in a tag of its own.
        """
        chain = (*_chain, prompt_name)
        if prompt_name in _chain:
            raise ValueError(f"Prompts load each other in a cycle: {' -> '.join(chain)}.")
        text = PromptLoader.load_prompt(prompt_name, project_root=project_root)

        out = ""
        strip_next = False
        pos = 0
        for match in _RAW_OR_LOAD_TAG.finditer(text):
            literal = text[pos : match.start()]
            out += literal.lstrip() if strip_next else literal
            pos = match.end()
            if match.group("raw"):
                out += match.group("raw")
                strip_next = False
                continue
            if match.group("strip_before"):
                out = out.rstrip()
            out += PromptLoader.load_prompt_expanded(
                match.group("name"), project_root=project_root, _chain=chain
            )
            strip_next = bool(match.group("strip_after"))
        rest = text[pos:]
        out += rest.lstrip() if strip_next else rest

        _refuse_unexpanded_load_prompt(prompt_name, out)
        return out


def _refuse_unexpanded_load_prompt(prompt_name: str, text: str) -> None:
    outside_raw = _RAW_OR_LOAD_TAG.sub(lambda m: "" if m.group("raw") else m.group(0), text)
    try:
        names = meta.find_undeclared_variables(jinja2.Environment().parse(outside_raw))
    except jinja2.TemplateSyntaxError:
        # The per-record render reports the prompt's syntax error.
        return
    if "load_prompt" in names:
        raise ValueError(
            f"Prompt '{prompt_name}' calls load_prompt in a form the load cannot expand. "
            "Write each call as a tag of its own with the prompt's name as a quoted "
            'string: {{ load_prompt("file.Prompt") }}.'
        )
