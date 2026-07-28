"""Unified pre-flight resolution service.

Performs a single comprehensive resolution pass across all actions:
- API key environment variable presence
- Seed file ($file:) reference existence and field validation
- Provider capability / run_mode compatibility

Uses the same resolution utilities that runtime uses, ensuring no divergence.
"""

import json
import logging
import os
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agent_actions.utils.path_security import resolve_seed_path
from agent_actions.validation.static_analyzer.errors import (
    FieldLocation,
    StaticTypeError,
    StaticTypeWarning,
    StaticValidationResult,
)

logger = logging.getLogger(__name__)

# Vendor name → config class mapping.  Built lazily on first access to
# avoid importing all vendor configs (and transitively their SDKs) at
# module level.
_VENDOR_CONFIG_MAP: dict[str, type[BaseModel]] | None = None

# Sentinel substrings in api_key_env_name that indicate no real key is needed.
_NO_KEY_SENTINELS = ("NO_KEY_REQUIRED",)


def _get_vendor_config_map() -> dict[str, type[BaseModel]]:
    """Build vendor → config class map on first call (lazy)."""
    global _VENDOR_CONFIG_MAP  # noqa: PLW0603
    if _VENDOR_CONFIG_MAP is not None:
        return _VENDOR_CONFIG_MAP

    from agent_actions.llm.config.vendor import (
        AgacProviderConfig,
        AnthropicConfig,
        CohereConfig,
        GeminiConfig,
        GroqConfig,
        HitlVendorConfig,
        OllamaCloudConfig,
        OllamaLocalConfig,
        OpenAIConfig,
        ToolVendorConfig,
    )

    _VENDOR_CONFIG_MAP = {
        "openai": OpenAIConfig,
        "anthropic": AnthropicConfig,
        "gemini": GeminiConfig,
        "google": GeminiConfig,
        "groq": GroqConfig,
        "cohere": CohereConfig,
        "ollama_local": OllamaLocalConfig,
        "ollama_cloud": OllamaCloudConfig,
        "tool": ToolVendorConfig,
        "hitl": HitlVendorConfig,
        "agac-provider": AgacProviderConfig,
    }
    return _VENDOR_CONFIG_MAP


def _get_api_key_env_name(vendor: str) -> str | None:
    """Resolve API key env var name from vendor config class (single source of truth)."""
    config_cls = _get_vendor_config_map().get(vendor.lower())
    if config_cls is None:
        return None
    field_info = config_cls.model_fields.get("api_key_env_name")
    if field_info is None:
        return None
    default = field_info.default
    return str(default) if default is not None else None


def _nested_key_exists(data: Any, path: str) -> bool:
    """Walk nested dict keys along *path*.  Stop at array boundaries."""
    current = data
    for part in path.split("."):
        if isinstance(current, list):
            return True  # Can't validate past array boundary
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


class WorkflowResolutionService:
    """Performs unified pre-flight resolution checks."""

    def __init__(
        self,
        action_configs: dict[str, dict[str, Any]],
        workflow_config_path: str | None = None,
        project_root: Path | None = None,
        verify_keys: bool = False,
    ):
        self.action_configs = action_configs
        self.workflow_config_path = workflow_config_path
        self.project_root = project_root
        self.verify_keys = verify_keys

    def resolve_all(self) -> StaticValidationResult:
        """Run all resolution checks and return aggregated result."""
        result = StaticValidationResult()

        if os.environ.get("AA_SKIP_ENV_VALIDATION") != "1":
            errors, warnings, vendor_keys = self._check_api_keys()
            for error in errors:
                result.add_error(error)
            for warning in warnings:
                result.add_warning(warning)

            # Probe vendor endpoints when --verify-keys is set and keys exist.
            if self.verify_keys and vendor_keys and not result.errors:
                self._verify_api_keys(vendor_keys, result)

        seed_errors, seed_warnings = self._check_seed_file_references()
        for error in seed_errors:
            result.add_error(error)
        for warning in seed_warnings:
            result.add_warning(warning)

        for error in self._check_vendor_run_mode_compatibility():
            result.add_error(error)

        return result

    def _verify_api_keys(
        self,
        vendor_keys: dict[str, str],
        result: StaticValidationResult,
    ) -> None:
        """Probe vendor endpoints to verify keys are valid (not just present)."""
        from agent_actions.validation.preflight.key_verifier import verify_keys

        for probe_result in verify_keys(vendor_keys):
            if not probe_result.ok:
                result.add_error(
                    StaticTypeError(
                        message=(
                            f"API key for vendor '{probe_result.vendor}' is invalid: "
                            f"{probe_result.error}"
                        ),
                        location=FieldLocation(
                            agent_name="(workflow)",
                            config_field="api_key",
                            raw_reference=probe_result.vendor,
                        ),
                        referenced_agent="(workflow)",
                        referenced_field="api_key",
                        hint=(
                            f"The {probe_result.vendor} API rejected the key. "
                            f"Check that it is not expired or revoked."
                        ),
                    )
                )

    # ── API key checks ─────────────────────────────────────────────────

    def _check_api_keys(
        self,
    ) -> tuple[list[StaticTypeError], list[StaticTypeWarning], dict[str, str]]:
        """Check that all required API key env vars are set.

        Returns (errors, warnings, vendor_keys).  Missing keys are errors.
        vendor_keys maps each resolved vendor to its key value (deduplicated)
        for optional downstream probing.
        """
        errors: list[StaticTypeError] = []
        warnings: list[StaticTypeWarning] = []
        # Deduplicated vendor → resolved key value (first seen wins).
        vendor_keys: dict[str, str] = {}

        for action_name, config in self.action_configs.items():
            vendor = (config.get("model_vendor") or "").lower()
            if not vendor:
                continue

            # Resolve the expected env var name from vendor config
            env_var_name = _get_api_key_env_name(vendor)
            if env_var_name is None:
                continue

            # Skip vendors that don't need real keys (tool, hitl)
            if any(sentinel in env_var_name for sentinel in _NO_KEY_SENTINELS):
                continue

            # If the action config specifies a custom api_key, use that
            custom_key = config.get("api_key")
            is_literal = False
            if custom_key:
                custom_str = str(custom_key)
                if custom_str.startswith("$"):
                    env_var_name = custom_str[1:]
                else:
                    is_literal = True

            if is_literal:
                key_value = str(custom_key)
            else:
                key_value = os.environ.get(env_var_name, "")

            # Presence check (errors) — literal keys are always "present".
            if not key_value:
                errors.append(
                    StaticTypeError(
                        message=(
                            f"API key environment variable '{env_var_name}' is not set "
                            f"(required by action '{action_name}', vendor '{vendor}')"
                        ),
                        location=FieldLocation(
                            agent_name=action_name,
                            config_field="api_key",
                            raw_reference=env_var_name,
                        ),
                        referenced_agent=action_name,
                        referenced_field="api_key",
                        hint=f"Set the environment variable: export {env_var_name}=your_key_here",
                    )
                )
                continue

            # Track for downstream probing (first vendor occurrence wins).
            if vendor not in vendor_keys:
                vendor_keys[vendor] = key_value

        return errors, warnings, vendor_keys

    # ── Seed file checks ───────────────────────────────────────────────

    def _check_seed_file_references(
        self,
    ) -> tuple[list[StaticTypeError], list[StaticTypeWarning]]:
        """Check $file: references and validate seed field references.

        Phase 1: Validate file existence, path security, and load JSON content.
        Phase 2: Extract seed references from templates/directives and validate
        that referenced fields exist in the loaded seed data.

        Returns (errors, warnings).  Namespace mismatches are errors (blocking).
        Nested field mismatches are warnings (non-blocking).
        """
        errors: list[StaticTypeError] = []
        warnings: list[StaticTypeWarning] = []

        seed_data_dir, seed_dir_name = self._resolve_seed_data_dir()
        if seed_data_dir is None:
            # No seed directory anywhere — an error for any action that
            # declares seed refs (the runtime loader would fail per record).
            for action_name, action_config in self.action_configs.items():
                context_scope = action_config.get("context_scope") or {}
                seed_config = context_scope.get("seed", {})
                if seed_config and isinstance(seed_config, dict):
                    errors.append(
                        StaticTypeError(
                            message=(
                                f"Seed data directory not found: create '{seed_dir_name}' at "
                                "the workflow root (same level as agent_config/) or at the "
                                "project root"
                            ),
                            location=FieldLocation(
                                agent_name=action_name,
                                config_field="context_scope.seed",
                                raw_reference=seed_dir_name,
                            ),
                            referenced_agent=action_name,
                            referenced_field="seed",
                            hint=f"Declared seed fields: {', '.join(sorted(seed_config))}",
                        )
                    )
                    break
            return errors, warnings

        # Phase 1: validate file existence and load seed data
        action_seed_data: dict[str, dict[str, Any]] = {}
        action_seed_keys: dict[str, set[str]] = {}

        for action_name, config in self.action_configs.items():
            context_scope = config.get("context_scope", {})
            if not isinstance(context_scope, dict):
                continue
            seed_config = context_scope.get("seed", {})
            if not seed_config or not isinstance(seed_config, dict):
                continue

            action_seed_keys[action_name] = set(seed_config.keys())
            action_seed_data[action_name] = {}

            for field_name, file_spec in seed_config.items():
                if not isinstance(file_spec, str):
                    continue

                try:
                    resolved = resolve_seed_path(file_spec, seed_data_dir)
                except ValueError as e:
                    errors.append(
                        StaticTypeError(
                            message=str(e),
                            location=FieldLocation(
                                agent_name=action_name,
                                config_field=f"context_scope.seed.{field_name}",
                                raw_reference=file_spec,
                            ),
                            referenced_agent=action_name,
                            referenced_field=field_name,
                            hint="Use relative paths within the seed_data/ directory.",
                        )
                    )
                    continue

                if not resolved.exists():
                    available: list[str] = []
                    if seed_data_dir.exists():
                        available = sorted(f.name for f in seed_data_dir.iterdir() if f.is_file())

                    errors.append(
                        StaticTypeError(
                            message=(f"Seed file not found: {file_spec} (resolved to {resolved})"),
                            location=FieldLocation(
                                agent_name=action_name,
                                config_field=f"context_scope.seed.{field_name}",
                                raw_reference=file_spec,
                            ),
                            referenced_agent=action_name,
                            referenced_field=field_name,
                            available_fields=set(available),
                            hint=(
                                f"Available files: {', '.join(available)}"
                                if available
                                else "(seed_data/ directory is empty)"
                            ),
                        )
                    )
                    continue

                # Load JSON content for field validation
                try:
                    content = json.loads(resolved.read_text(encoding="utf-8"))
                    action_seed_data[action_name][field_name] = content
                except (OSError, json.JSONDecodeError) as e:
                    errors.append(
                        StaticTypeError(
                            message=f"Seed file '{file_spec}' failed to parse: {e}",
                            location=FieldLocation(
                                agent_name=action_name,
                                config_field=f"context_scope.seed.{field_name}",
                                raw_reference=file_spec,
                            ),
                            referenced_agent=action_name,
                            referenced_field=field_name,
                            hint="Ensure the seed file contains valid JSON.",
                        )
                    )

        # Phase 2: validate seed field references against loaded data
        self._validate_seed_field_references(action_seed_data, action_seed_keys, errors, warnings)

        return errors, warnings

    def _validate_seed_field_references(
        self,
        action_seed_data: dict[str, dict[str, Any]],
        action_seed_keys: dict[str, set[str]],
        errors: list[StaticTypeError],
        warnings: list[StaticTypeWarning],
    ) -> None:
        """Validate that seed field references in templates match loaded seed data."""
        from jinja2.exceptions import TemplateSyntaxError

        from agent_actions.validation.static_analyzer.reference_extractor import (
            ReferenceExtractor,
        )

        ref_extractor = ReferenceExtractor()

        for action_name, config in self.action_configs.items():
            effective_config = self._resolve_prompt_for_extraction(config)
            try:
                requirements = ref_extractor.extract_from_agent(effective_config)
            except TemplateSyntaxError as exc:
                errors.append(
                    StaticTypeError(
                        message=f"Template syntax error in '{action_name}': {exc.message} (line {exc.lineno})",
                        location=FieldLocation(
                            agent_name=action_name,
                            config_field="prompt",
                            line_number=exc.lineno,
                        ),
                        referenced_agent=action_name,
                        referenced_field="",
                    )
                )
                continue
            seed_refs = [r for r in requirements if r.source_agent == "seed"]
            if not seed_refs:
                continue

            declared_keys = action_seed_keys.get(action_name, set())
            loaded_data = action_seed_data.get(action_name, {})

            seen_refs: set[str] = set()
            for req in seed_refs:
                ref_key = f"{action_name}:{req.field_path}"
                if ref_key in seen_refs:
                    continue
                seen_refs.add(ref_key)

                parts = req.field_path.split(".", 1)
                seed_key = parts[0]
                nested_path = parts[1] if len(parts) > 1 else None

                # Namespace validation (ERROR — high confidence)
                if seed_key not in declared_keys:
                    hint = (
                        f"Declared seed keys: {', '.join(sorted(declared_keys))}"
                        if declared_keys
                        else f"No seed entries declared for action '{action_name}'."
                    )
                    errors.append(
                        StaticTypeError(
                            message=(
                                f"Action '{action_name}' references seed.{seed_key} "
                                f"but '{seed_key}' is not declared in "
                                f"context_scope.seed"
                            ),
                            location=FieldLocation(
                                agent_name=action_name,
                                config_field=req.location,
                                raw_reference=req.raw_reference,
                            ),
                            referenced_agent=action_name,
                            referenced_field=f"seed.{seed_key}",
                            available_fields=declared_keys,
                            hint=hint,
                        )
                    )
                    continue

                # Nested field validation (WARNING — could be conditional/dynamic)
                if not nested_path or seed_key not in loaded_data:
                    continue
                # Skip wildcard paths — can't validate statically
                if "*" in nested_path:
                    continue

                content = loaded_data[seed_key]
                if not _nested_key_exists(content, nested_path):
                    available = sorted(content.keys()) if isinstance(content, dict) else []
                    top_field = nested_path.split(".")[0]
                    suggestions = get_close_matches(top_field, available, n=1, cutoff=0.6)
                    warnings.append(
                        StaticTypeWarning(
                            message=(
                                f"Seed field '{seed_key}.{nested_path}' referenced "
                                f"in action '{action_name}' does not exist in "
                                f"seed data"
                            ),
                            location=FieldLocation(
                                agent_name=action_name,
                                config_field=req.location,
                                raw_reference=req.raw_reference,
                            ),
                            referenced_agent=action_name,
                            referenced_field=f"seed.{seed_key}.{nested_path}",
                            available_fields=set(available),
                            hint=(
                                f"Did you mean: {suggestions[0]}?"
                                if suggestions
                                else f"Available fields: {', '.join(available)}"
                            ),
                        )
                    )

    @staticmethod
    def _resolve_prompt_for_extraction(config: dict[str, Any]) -> dict[str, Any]:
        """Resolve $file: prompt references for seed field extraction.

        Returns the config with the prompt resolved to actual template text.
        Falls back to the original config if resolution fails (e.g. prompt
        file not found — that error is caught by other validators).
        """
        prompt = config.get("prompt", "")
        if not isinstance(prompt, str) or not prompt.startswith("$"):
            return config

        try:
            from agent_actions.prompt.formatter import PromptFormatter

            resolved = PromptFormatter.get_raw_prompt(config)
            return {**config, "prompt": resolved}
        except Exception as exc:
            logger.warning(
                "Cannot resolve prompt for seed field extraction in action '%s': %s",
                config.get("name", "unknown"),
                exc,
            )
            return config

    # ── Vendor run-mode compatibility ──────────────────────────────────

    def _check_vendor_run_mode_compatibility(self) -> list[StaticTypeError]:
        """Check that vendor supports the requested run_mode."""
        errors: list[StaticTypeError] = []

        from agent_actions.validation.preflight.vendor_compatibility_validator import (
            _resolve_capabilities,
        )

        for action_name, config in self.action_configs.items():
            vendor = (config.get("model_vendor") or "").lower()
            run_mode = config.get("run_mode", "online")

            # Normalize RunMode enum to string
            if hasattr(run_mode, "value"):
                run_mode = run_mode.value

            if run_mode != "batch":
                continue

            capabilities = _resolve_capabilities(vendor)
            if capabilities is None:
                continue

            if not capabilities.get("supports_batch"):
                errors.append(
                    StaticTypeError(
                        message=(
                            f"Action '{action_name}' uses run_mode=batch with vendor "
                            f"'{vendor}', but {vendor} does not support batch mode"
                        ),
                        location=FieldLocation(
                            agent_name=action_name,
                            config_field="run_mode",
                            raw_reference=f"run_mode=batch, vendor={vendor}",
                        ),
                        referenced_agent=action_name,
                        referenced_field="run_mode",
                        hint=f"Use run_mode: online for {vendor} actions, or choose a batch-capable vendor.",
                    )
                )

        return errors

    # ── Helpers ────────────────────────────────────────────────────────

    def _resolve_seed_data_dir(self) -> tuple[Path | None, str]:
        """Resolve the seed data directory via the shared runtime resolver.

        Preflight must consult the same folder the runtime loader will use
        (workflow root first, then project root).
        """
        if not self.workflow_config_path:
            return None, "seed_data"

        from agent_actions.config.path_config import resolve_seed_data_dir

        return resolve_seed_data_dir(self.workflow_config_path)
