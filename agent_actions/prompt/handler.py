"""Prompt loading and validation from markdown files."""

import logging
import re
from collections import Counter
from pathlib import Path

import jinja2
from jinja2 import meta

from agent_actions.config.path_config import resolve_project_root
from agent_actions.config.paths import PathType

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


_WORKFLOWS_DIR = "agent_workflow"


def _prompt_store_dirs(root: Path) -> list[Path]:
    """The prompt folders that exist: the project's, then each workflow's."""
    store = PathType.PROMPT_STORE.value
    dirs = [root / store]
    workflows = root / _WORKFLOWS_DIR
    if workflows.is_dir():
        dirs.extend(wf / store for wf in sorted(workflows.iterdir()) if wf.is_dir())
    return [d for d in dirs if d.is_dir()]


def _searched_places(root: Path) -> str:
    store = PathType.PROMPT_STORE.value
    return f"{root / store} and {root / _WORKFLOWS_DIR / '*' / store}"


class PromptLoader:
    """Loads and validates prompts from markdown content."""

    @staticmethod
    def discover_prompt_files(project_root: Path | None = None) -> list[Path]:
        """Every ``.md`` file in the project's ``prompt_store/`` and each workflow's, recursively."""
        root = resolve_project_root(project_root)
        found: list[Path] = []
        seen: set[tuple[str, Path]] = set()
        for prompt_dir in _prompt_store_dirs(root):
            for md_file in sorted(prompt_dir.rglob("*.md")):
                # One file reached twice under one name (a workflow folder linked to the
                # shared one) is not a copy; a link under another name is its own prompt file.
                key = (md_file.name, md_file.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(md_file)
        return found

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
        Load a prompt by name ('filename.prompt_key') from the prompt folders.

        Raises:
            ValueError: If the prompt format is invalid, or no file or more than one
                file in the prompt folders has the name.
        """
        if "." not in prompt_name:
            raise ValueError(
                f"Invalid prompt format: '{prompt_name}'. Expected 'filename.prompt_key' (with a dot separator)."
            )

        prompt_file_name, prompt_key = prompt_name.split(".", 1)
        target_filename = f"{prompt_file_name}.md"

        root = resolve_project_root(project_root)
        matches = [
            path
            for path in PromptLoader.discover_prompt_files(root)
            if path.name == target_filename
        ]
        if not matches:
            raise ValueError(
                f"Prompt file '{target_filename}' not found. "
                f"Searched {_searched_places(root)}, with their subfolders."
            )
        if len(matches) > 1:
            listed = "\n    ".join(str(path) for path in matches)
            raise ValueError(
                f"Prompt file '{target_filename}' is in {len(matches)} places. A prompt file "
                f"name must be unique across {_searched_places(root)}. "
                f"Rename or remove all but one:\n    {listed}"
            )

        prompt_file_path = matches[0]
        logger.debug("Found prompt file at: %s", prompt_file_path)
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
