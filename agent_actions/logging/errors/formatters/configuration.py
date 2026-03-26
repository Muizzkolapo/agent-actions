"""Configuration error formatter."""

from typing import Any

from ..user_error import UserError
from .base import ErrorFormatter


class ConfigurationErrorFormatter(ErrorFormatter):
    """Handles configuration-related errors."""

    def can_handle(self, exc: Exception, root: Exception, message: str) -> bool:
        exc_names = [type(exc).__name__, type(root).__name__]

        if any("Config" in name for name in exc_names):
            return True
        if any(name in ["ValidationError", "SchemaValidationError"] for name in exc_names):
            return True

        message_lower = message.lower()
        config_patterns = [
            "missing required configuration",  # More specific - config errors
            "required configuration field",  # More specific - config errors
            "invalid config",
            "configuration error",
            "schema validation",
            "yaml",
            "missing key",
        ]
        # Avoid matching UDF data validation errors like "Missing required fields: options"
        if "missing required fields:" in message_lower:
            return False
        return any(pattern in message_lower for pattern in config_patterns)

    def format(
        self, exc: Exception, root: Exception, message: str, context: dict[str, Any]
    ) -> UserError:
        missing_field_patterns = [
            "missing required field",
            "required configuration fields are missing",
        ]
        if any(pattern in message.lower() for pattern in missing_field_patterns):
            return self._format_missing_required_fields_error(message, context)

        if "environment variable" in message.lower() and "not set" in message.lower():
            return self._format_missing_env_var_error(message, context)

        if "schema validation" in message.lower():
            return UserError(
                category="Configuration Error",
                title="Schema validation failed",
                details="The configuration format is invalid",
                fix="Check your YAML/JSON syntax and required fields",
                context=context,
                docs_url="https://docs.runagac.com/config/schema",
            )

        agent = context.get("agent", "unknown")
        return UserError(
            category="Configuration Error",
            title=f"Invalid configuration in agent '{agent}'",
            details=message,
            fix="Check your agent configuration file for errors",
            context=context,
            docs_url="https://docs.runagac.com/config",
        )

    def _format_missing_required_fields_error(self, _message: str, context: dict) -> UserError:
        """Format error for missing required configuration fields after hierarchy resolution."""
        action_name = context.get("action_name", context.get("agent", "unknown"))
        missing_fields = context.get("missing_fields", [])
        missing_display = context.get("missing_display", missing_fields)

        fields_str = ", ".join([f"'{f}'" for f in missing_display])
        details = f"Action '{action_name}' is missing required configuration: {fields_str}\n\n"
        details += "These fields were not found at any level (project → workflow → action)."

        fix_parts = [
            "Add the missing field(s) to one of these levels:\n",
            "1. Project-level (agent_actions.yml):",
            "   default_agent_config:",
        ]

        for field in missing_fields:
            if field == "model_vendor":
                fix_parts.append("     model_vendor: anthropic  # or openai, gemini, groq")
            elif field == "model_name":
                fix_parts.append("     model_name: claude-3-5-sonnet-20241022")
            elif field == "api_key":
                fix_parts.append("     api_key: ${ANTHROPIC_API_KEY}")

        fix_parts.extend(
            [
                "",
                "2. Workflow defaults:",
                "   defaults:",
            ]
        )

        for field in missing_fields:
            if field == "model_vendor":
                fix_parts.append("     model_vendor: anthropic")
            elif field == "model_name":
                fix_parts.append("     model_name: claude-3-5-sonnet-20241022")
            elif field == "api_key":
                fix_parts.append("     api_key: ${ANTHROPIC_API_KEY}")

        fix_parts.extend(
            [
                "",
                "3. Action-level config:",
                "   actions:",
                "     - name: " + action_name,
            ]
        )

        for field in missing_fields:
            if field == "model_vendor":
                fix_parts.append("       model_vendor: anthropic")
            elif field == "model_name":
                fix_parts.append("       model_name: claude-3-5-sonnet-20241022")
            elif field == "api_key":
                fix_parts.append("       api_key: ${ANTHROPIC_API_KEY}")

        return UserError(
            category="Configuration Error",
            title="Missing required configuration fields",
            details=details,
            fix="\n".join(fix_parts),
            context={"action": action_name, "missing_fields": missing_display},
            docs_url="https://docs.runagac.com/core-concepts/configuration-hierarchy",
        )

    def _format_missing_env_var_error(self, _message: str, context: dict) -> UserError:
        """Format error for missing environment variable."""
        env_var = context.get("env_var", "UNKNOWN")
        agent_name = context.get("agent", "unknown")
        config_value = context.get("config_value", f"${{{env_var}}}")

        details = f"Environment variable '{env_var}' is not set.\n\n"
        details += f"Your configuration references this variable: {config_value}"

        fix_parts = [
            "Set the environment variable before running:\n",
            f"  export {env_var}=your-api-key-here\n",
            "Or add to your .env file:",
            f"  {env_var}=your-api-key-here\n",
            "Or add to your shell profile (~/.bashrc, ~/.zshrc):",
            f"  export {env_var}=your-api-key-here",
        ]

        return UserError(
            category="Configuration Error",
            title="Environment variable not set",
            details=details,
            fix="\n".join(fix_parts),
            context={"agent": agent_name, "env_var": env_var},
        )
