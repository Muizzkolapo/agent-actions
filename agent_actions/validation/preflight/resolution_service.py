"""Unified pre-flight resolution service.

Performs a single comprehensive resolution pass across all actions:
- API key environment variable presence
- Seed file ($file:) reference existence
- Provider capability / run_mode compatibility

Uses the same resolution utilities that runtime uses, ensuring no divergence.
"""

import logging
import os
from pathlib import Path
from typing import Any

from agent_actions.utils.path_security import resolve_seed_path
from agent_actions.validation.static_analyzer.errors import (
    FieldLocation,
    StaticTypeError,
    StaticValidationResult,
)

logger = logging.getLogger(__name__)

# Vendor name → config class mapping.  Built lazily on first access to
# avoid importing all vendor configs (and transitively their SDKs) at
# module level.
_VENDOR_CONFIG_MAP: dict[str, type] | None = None

# Sentinel substrings in api_key_env_name that indicate no real key is needed.
_NO_KEY_SENTINELS = ("NO_KEY_REQUIRED",)


def _get_vendor_config_map() -> dict[str, type]:
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
        MistralConfig,
        OllamaConfig,
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
        "mistral": MistralConfig,
        "ollama": OllamaConfig,
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
    return field_info.default


class WorkflowResolutionService:
    """Performs unified pre-flight resolution checks."""

    def __init__(
        self,
        action_configs: dict[str, dict[str, Any]],
        workflow_config_path: str | None = None,
        project_root: Path | None = None,
    ):
        self.action_configs = action_configs
        self.workflow_config_path = workflow_config_path
        self.project_root = project_root

    def resolve_all(self) -> StaticValidationResult:
        """Run all resolution checks and return aggregated result."""
        result = StaticValidationResult()

        if os.environ.get("AA_SKIP_ENV_VALIDATION") != "1":
            for error in self._check_api_keys():
                result.add_error(error)

        for error in self._check_seed_file_references():
            result.add_error(error)

        for error in self._check_vendor_run_mode_compatibility():
            result.add_error(error)

        return result

    # ── API key checks ─────────────────────────────────────────────────

    def _check_api_keys(self) -> list[StaticTypeError]:
        """Check that all required API key env vars are set."""
        errors: list[StaticTypeError] = []

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
            if custom_key:
                custom_str = str(custom_key)
                if custom_str.startswith("$"):
                    env_var_name = custom_str[1:]
                else:
                    # Literal key provided — skip env check
                    continue

            if not os.environ.get(env_var_name):
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

        return errors

    # ── Seed file checks ───────────────────────────────────────────────

    def _check_seed_file_references(self) -> list[StaticTypeError]:
        """Check that all $file: references resolve to existing files."""
        errors: list[StaticTypeError] = []

        seed_data_dir = self._resolve_seed_data_dir()
        if seed_data_dir is None:
            return errors

        for action_name, config in self.action_configs.items():
            context_scope = config.get("context_scope", {})
            if not isinstance(context_scope, dict):
                continue
            seed_path_config = context_scope.get("seed_path", {})
            if not seed_path_config or not isinstance(seed_path_config, dict):
                continue

            for field_name, file_spec in seed_path_config.items():
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
                                config_field=f"context_scope.seed_path.{field_name}",
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
                            message=(
                                f"Seed file not found: {file_spec} "
                                f"(resolved to {resolved})"
                            ),
                            location=FieldLocation(
                                agent_name=action_name,
                                config_field=f"context_scope.seed_path.{field_name}",
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

        return errors

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

    def _resolve_seed_data_dir(self) -> Path | None:
        """Resolve the seed_data directory from workflow config path."""
        if not self.workflow_config_path:
            return None

        config_path = Path(self.workflow_config_path).resolve()
        current = config_path.parent
        while current != current.parent:
            if (current / "agent_config").exists():
                seed_dir = current / "seed_data"
                return seed_dir if seed_dir.exists() else None
            if current.name == "agent_config":
                seed_dir = current.parent / "seed_data"
                return seed_dir if seed_dir.exists() else None
            current = current.parent

        return None
