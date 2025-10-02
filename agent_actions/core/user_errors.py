"""
User-friendly error formatting system.

This module converts internal Python exceptions into clear, actionable
error messages for config authors (similar to dbt/Terraform tools).
Users should never see Python stack traces or internal implementation details.
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, Any, Optional

from agent_actions.core.safe_format import (
    safe_format_error,
    extract_root_cause,
    safe_get_exception_message,
    format_exception_chain_for_debug
)

logger = logging.getLogger(__name__)


@dataclass
class UserError:
    """Structured representation of a user-facing error."""

    category: str  # Configuration, Model, Provider, File, Network, Authentication
    title: str     # Brief description
    details: Optional[str] = None   # What went wrong
    fix: Optional[str] = None       # How to fix it
    context: Optional[Dict[str, Any]] = None  # agent, file, field, etc.
    docs_url: Optional[str] = None

    def format_for_cli(self) -> str:
        """Format error for CLI display."""
        lines = [f"{self.category}: {self.title}"]

        if self.details:
            lines.extend(["", f"  Problem: {self.details}"])

        # Add context information
        # Display specific important fields first
        if self.context:
            if 'agent' in self.context:
                lines.append(f"  Agent: {self.context['agent']}")
            if 'file_path' in self.context:
                lines.append(f"  File: {self.context['file_path']}")
            if 'field' in self.context:
                lines.append(f"  Field: {self.context['field']}")
            if 'model' in self.context:
                lines.append(f"  Model: {self.context['model']}")
            if 'provider' in self.context:
                lines.append(f"  Provider: {self.context['provider']}")

            # Display other context fields (for debugging and completeness)
            # Skip internal/technical fields and already-displayed fields
            displayed_fields = {'agent', 'file_path', 'field', 'model', 'provider'}
            skip_fields = {'function', 'module', 'resource_type'}  # Internal technical fields

            other_context = {k: v for k, v in self.context.items()
                           if k not in displayed_fields and k not in skip_fields}

            if other_context:
                lines.append("")
                lines.append("  Context:")
                for key, value in sorted(other_context.items()):
                    lines.append(f"    {key}: {value}")

        if self.fix:
            lines.extend(["", f"  Fix: {self.fix}"])

        if self.docs_url:
            lines.extend(["", f"  Learn more: {self.docs_url}"])

        return "\n".join(lines)


class ErrorTranslator:
    """Translates Python exceptions to user-friendly errors."""

    def translate(self, exc: Exception, context: Optional[Dict[str, Any]] = None) -> UserError:
        """
        Main translation method - converts any exception to UserError.

        Args:
            exc: The exception to translate
            context: Optional context dict with keys like 'agent', 'file_path', etc.

        Returns:
            UserError with user-friendly message
        """
        # Merge exception context with passed context
        merged_context = {}
        if hasattr(exc, 'context') and isinstance(exc.context, dict):
            merged_context.update(exc.context)

        # Also extract other exception attributes that might be useful
        for attr_name in dir(exc):
            if not attr_name.startswith('_') and attr_name not in ['args', 'with_traceback', 'context']:
                try:
                    attr_value = getattr(exc, attr_name)
                    # Only include simple types (not methods/callables)
                    if not callable(attr_value) and isinstance(attr_value, (str, int, float, bool, type(None))):
                        merged_context[attr_name] = attr_value
                except Exception:
                    pass  # Skip attributes that can't be accessed

        if context:
            merged_context.update(context)  # Passed context takes precedence

        context = merged_context

        # Extract root cause for better error detection
        root_cause = extract_root_cause(exc)
        root_message = safe_get_exception_message(root_cause)

        logger.debug(f"Translating error: {type(exc).__name__} -> {type(root_cause).__name__}: {root_message}")

        # Try category-specific handlers
        if self._is_config_error(exc, root_cause, root_message):
            return self._handle_config_error(exc, root_cause, root_message, context)
        elif self._is_model_error(exc, root_cause, root_message):
            return self._handle_model_error(exc, root_cause, root_message, context)
        elif self._is_auth_error(exc, root_cause, root_message):
            return self._handle_auth_error(exc, root_cause, root_message, context)
        elif self._is_file_error(exc, root_cause, root_message):
            return self._handle_file_error(exc, root_cause, root_message, context)
        elif self._is_api_error(exc, root_cause, root_message):
            return self._handle_api_error(exc, root_cause, root_message, context)
        else:
            return self._handle_generic_error(exc, root_cause, root_message, context)

    # Category detection methods

    def _is_config_error(self, exc: Exception, root: Exception, message: str) -> bool:
        """Detect configuration-related errors."""
        exc_names = [type(exc).__name__, type(root).__name__]

        # Check exception types
        if any('Config' in name for name in exc_names):
            return True
        if any(name in ['ValidationError', 'SchemaValidationError'] for name in exc_names):
            return True

        # Check error message patterns
        message_lower = message.lower()
        config_patterns = [
            'missing required field',
            'required field',
            'invalid config',
            'configuration',
            'schema validation',
            'yaml',
            'json',
            'missing key'
        ]
        return any(pattern in message_lower for pattern in config_patterns)

    def _is_model_error(self, exc: Exception, root: Exception, message: str) -> bool:
        """Detect model validation errors."""
        message_lower = message.lower()
        model_patterns = [
            'model',
            'not supported',
            'unsupported model',
            'invalid model',
            'model not found'
        ]
        return any(pattern in message_lower for pattern in model_patterns)

    def _is_auth_error(self, exc: Exception, root: Exception, message: str) -> bool:
        """Detect authentication errors."""
        exc_names = [type(exc).__name__, type(root).__name__]

        # Check exception types
        if any('Auth' in name for name in exc_names):
            return True

        message_lower = message.lower()
        auth_patterns = [
            'api key',
            'authentication',
            'unauthorized',
            'invalid key',
            'permission denied',
            '401',
            '403'
        ]
        return any(pattern in message_lower for pattern in auth_patterns)

    def _is_file_error(self, exc: Exception, root: Exception, message: str) -> bool:
        """Detect file-related errors."""
        exc_names = [type(exc).__name__, type(root).__name__]

        # Check exception types
        if any(name in ['FileNotFoundError', 'PermissionError', 'FileLoadError'] for name in exc_names):
            return True

        message_lower = message.lower()
        file_patterns = [
            'file not found',
            'no such file',
            'permission denied',
            'cannot read',
            'cannot write'
        ]
        return any(pattern in message_lower for pattern in file_patterns)

    def _is_api_error(self, exc: Exception, root: Exception, message: str) -> bool:
        """Detect API/network errors."""
        exc_names = [type(exc).__name__, type(root).__name__]

        # Check exception types
        if any(name.endswith('APIError') or 'API' in name for name in exc_names):
            return True
        if any(name in ['NetworkError', 'ConnectionError', 'TimeoutError'] for name in exc_names):
            return True

        message_lower = message.lower()
        api_patterns = [
            'api',
            'connection',
            'network',
            'timeout',
            'request failed',
            'service unavailable',
            'rate limit'
        ]
        return any(pattern in message_lower for pattern in api_patterns)

    # Category handlers

    def _format_missing_required_fields_error(self, message: str, context: Dict) -> UserError:
        """Format error for missing required configuration fields after hierarchy resolution."""
        action_name = context.get('action_name', context.get('agent', 'unknown'))
        missing_fields = context.get('missing_fields', [])
        missing_display = context.get('missing_display', missing_fields)

        # Create details message
        fields_str = ', '.join([f"'{f}'" for f in missing_display])
        details = f"Action '{action_name}' is missing required configuration: {fields_str}\n\n"
        details += "These fields were not found at any level (project → workflow → action)."

        # Create fix instructions with examples
        fix_parts = [
            "Add the missing field(s) to one of these levels:\n",
            "1. Project-level (agent_actions.yml):",
            "   default_agent_config:",
        ]

        # Add examples for each missing field
        for field in missing_fields:
            if field == 'model_vendor':
                fix_parts.append("     model_vendor: anthropic  # or openai, gemini, groq")
            elif field == 'model_name':
                fix_parts.append("     model_name: claude-3-5-sonnet-20241022")
            elif field == 'api_key':
                fix_parts.append("     api_key: ${ANTHROPIC_API_KEY}")

        fix_parts.extend([
            "",
            "2. Workflow defaults:",
            "   defaults:",
        ])

        for field in missing_fields:
            if field == 'model_vendor':
                fix_parts.append("     vendor: anthropic")
            elif field == 'model_name':
                fix_parts.append("     model: claude-3-5-sonnet-20241022")
            elif field == 'api_key':
                fix_parts.append("     api_key: ${ANTHROPIC_API_KEY}")

        fix_parts.extend([
            "",
            "3. Action-level config:",
            "   actions:",
            "     - name: " + action_name,
        ])

        for field in missing_fields:
            if field == 'model_vendor':
                fix_parts.append("       vendor: anthropic")
            elif field == 'model_name':
                fix_parts.append("       model: claude-3-5-sonnet-20241022")
            elif field == 'api_key':
                fix_parts.append("       api_key: ${ANTHROPIC_API_KEY}")

        return UserError(
            category="Configuration Error",
            title="Missing required configuration fields",
            details=details,
            fix="\n".join(fix_parts),
            context={'action': action_name, 'missing_fields': missing_display},
            docs_url="https://docs.agent-actions.com/core-concepts/configuration-hierarchy"
        )

    def _format_missing_env_var_error(self, message: str, context: Dict) -> UserError:
        """Format error for missing environment variable."""
        env_var = context.get('env_var', 'UNKNOWN')
        agent_name = context.get('agent', 'unknown')
        config_value = context.get('config_value', f'${{{env_var}}}')

        details = f"Environment variable '{env_var}' is not set.\n\n"
        details += f"Your configuration references this variable: {config_value}"

        fix_parts = [
            "Set the environment variable before running:\n",
            f"  export {env_var}=your-api-key-here\n",
            "Or add to your .env file:",
            f"  {env_var}=your-api-key-here\n",
            "Or add to your shell profile (~/.bashrc, ~/.zshrc):",
            f"  export {env_var}=your-api-key-here"
        ]

        return UserError(
            category="Configuration Error",
            title="Environment variable not set",
            details=details,
            fix="\n".join(fix_parts),
            context={'agent': agent_name, 'env_var': env_var}
        )

    def _handle_config_error(self, exc: Exception, root: Exception, message: str, context: Dict) -> UserError:
        """Handle configuration errors."""

        # Check for missing required fields (hierarchy resolution)
        if 'missing required field' in message.lower() or 'required configuration fields are missing' in message.lower():
            return self._format_missing_required_fields_error(message, context)

        # Check for missing environment variable
        if 'environment variable' in message.lower() and 'not set' in message.lower():
            return self._format_missing_env_var_error(message, context)

        if 'schema validation' in message.lower():
            return UserError(
                category="Configuration Error",
                title="Schema validation failed",
                details="The configuration format is invalid",
                fix="Check your YAML/JSON syntax and required fields",
                context=context,
                docs_url="https://docs.agent-actions.com/config/schema"
            )

        # Generic config error
        agent = context.get('agent', 'unknown')
        return UserError(
            category="Configuration Error",
            title=f"Invalid configuration in agent '{agent}'",
            details=message,
            fix="Check your agent configuration file for errors",
            context=context,
            docs_url="https://docs.agent-actions.com/config"
        )

    def _handle_model_error(self, exc: Exception, root: Exception, message: str, context: Dict) -> UserError:
        """Handle model validation errors."""

        # Extract model name from error
        model = self._extract_model_name(message, context)
        provider = context.get('provider', self._guess_provider_from_model(model))

        # Get suggested models for the provider
        suggestions = self._get_model_suggestions(provider)

        fix_msg = f"Update the 'model' field in your agent config"
        if suggestions:
            fix_msg += f" to one of: {', '.join(suggestions)}"

        return UserError(
            category="Model Error",
            title="Invalid model specified",
            details=f"Model '{model}' is not available for provider '{provider}'",
            fix=fix_msg,
            context={**context, 'model': model, 'provider': provider},
            docs_url=f"https://docs.agent-actions.com/models/{provider}"
        )

    def _handle_auth_error(self, exc: Exception, root: Exception, message: str, context: Dict) -> UserError:
        """Handle authentication errors."""

        # Determine provider from error message or context
        provider = self._extract_provider_name(message, context)

        if provider == "anthropic":
            env_var = "ANTHROPIC_API_KEY"
            console_url = "https://console.anthropic.com"
        elif provider == "openai":
            env_var = "OPENAI_API_KEY"
            console_url = "https://platform.openai.com"
        else:
            env_var = "API_KEY"
            console_url = "your provider's console"

        fix_msg = f"1. Get your API key from {console_url}\n"
        fix_msg += f"     2. Set environment variable: export {env_var}=your-key\n"
        fix_msg += f"     3. Or add to .env file: {env_var}=your-key"

        return UserError(
            category="Authentication Error",
            title=f"Invalid {provider.title()} API key",
            details="Your API key is invalid, expired, or not set",
            fix=fix_msg,
            context=context,
            docs_url="https://docs.agent-actions.com/setup/authentication"
        )

    def _handle_file_error(self, exc: Exception, root: Exception, message: str, context: Dict) -> UserError:
        """Handle file-related errors."""

        if 'not found' in message.lower():
            file_path = context.get('file_path', 'unknown')
            agent = context.get('agent')

            if agent and file_path == 'unknown':
                # Probably missing agent config
                return UserError(
                    category="File Error",
                    title="Agent configuration not found",
                    details=f"Could not find configuration for agent '{agent}'",
                    fix=f"1. Create agents/{agent}.yaml\n     2. Or use an existing agent: agent-actions run --agent <existing-agent>",
                    context=context,
                    docs_url="https://docs.agent-actions.com/agents/create"
                )

            return UserError(
                category="File Error",
                title="File not found",
                details=f"Could not find file: {file_path}",
                fix="Ensure the file exists and the path is correct",
                context=context
            )

        # Generic file error
        return UserError(
            category="File Error",
            title="File operation failed",
            details=message,
            fix="Check file permissions and paths",
            context=context
        )

    def _handle_api_error(self, exc: Exception, root: Exception, message: str, context: Dict) -> UserError:
        """Handle API/network errors."""

        provider = self._extract_provider_name(message, context)

        if 'rate limit' in message.lower():
            return UserError(
                category="API Error",
                title="Rate limit exceeded",
                details=f"Too many requests to {provider.title()} API",
                fix="Wait a few minutes before trying again, or upgrade your API plan",
                context=context
            )

        if 'timeout' in message.lower() or 'connection' in message.lower():
            return UserError(
                category="Network Error",
                title="Connection failed",
                details=f"Could not connect to {provider.title()} API",
                fix="Check your internet connection and try again",
                context=context
            )

        # Generic API error
        return UserError(
            category="API Error",
            title=f"{provider.title()} API error",
            details=message,
            fix="Check your API key and network connection",
            context=context
        )

    def _handle_generic_error(self, exc: Exception, root: Exception, message: str, context: Dict) -> UserError:
        """Handle unknown/generic errors."""

        operation = context.get('operation', 'operation')
        agent = context.get('agent')

        title = f"Error during {operation.replace('_', ' ')}"
        if agent:
            title += f" for agent '{agent}'"

        return UserError(
            category="Error",
            title=title,
            details=message,
            fix="Check your configuration and try again",
            context=context,
            docs_url="https://docs.agent-actions.com/troubleshooting"
        )

    # Helper methods

    def _extract_field_name(self, message: str, context: Dict) -> str:
        """Extract field name from error message."""
        # Try to find field name in single quotes
        match = re.search(r"'([^']+)'", message)
        if match:
            return match.group(1)

        # Fallback to context or generic
        return context.get('field', 'unknown')

    def _extract_model_name(self, message: str, context: Dict) -> str:
        """Extract model name from error message."""
        # Look for model name in quotes
        match = re.search(r"['\"]([^'\"]+)['\"].*not supported", message)
        if match:
            return match.group(1)

        return context.get('model', 'unknown')

    def _extract_provider_name(self, message: str, context: Dict) -> str:
        """Extract provider name from error message or context."""
        message_lower = message.lower()

        if 'anthropic' in message_lower:
            return 'anthropic'
        elif 'openai' in message_lower:
            return 'openai'
        elif 'gemini' in message_lower:
            return 'gemini'
        elif 'cohere' in message_lower:
            return 'cohere'

        return context.get('provider', 'API')

    def _guess_provider_from_model(self, model: str) -> str:
        """Guess provider from model name."""
        if 'claude' in model.lower():
            return 'anthropic'
        elif 'gpt' in model.lower():
            return 'openai'
        elif 'gemini' in model.lower():
            return 'gemini'
        else:
            return 'unknown'

    def _get_model_suggestions(self, provider: str) -> list:
        """Get model suggestions for a provider."""
        suggestions = {
            'anthropic': [
                'claude-3-5-sonnet-20241022',
                'claude-3-5-haiku-20241022',
                'claude-3-opus-20240229'
            ],
            'openai': [
                'gpt-4-turbo-preview',
                'gpt-4',
                'gpt-3.5-turbo'
            ],
            'gemini': [
                'gemini-pro',
                'gemini-pro-vision'
            ]
        }
        return suggestions.get(provider, [])


# Main public interface
def format_user_error(exc: Exception, context: Optional[Dict[str, Any]] = None) -> str:
    """
    Convert any exception to a user-friendly error message.

    This is the main entry point for error formatting. It logs the full
    exception for debugging while returning a clean message for users.

    Args:
        exc: The exception to format
        context: Optional context dict with keys like 'agent', 'file_path', etc.

    Returns:
        User-friendly error message string
    """
    # ALWAYS log full error for debugging with complete exception chain
    logger.error(
        "Error occurred during operation",
        exc_info=exc,
        extra={'context': context or {}}
    )
    # Log the detailed exception chain for debugging (not shown to users)
    logger.debug(f"Exception chain details:\n{format_exception_chain_for_debug(exc)}")

    try:
        translator = ErrorTranslator()

        # Merge exception context with passed context
        # Exception context (from decorators) is added first, then passed context
        # can override if there are conflicts
        merged_context = {}
        if hasattr(exc, 'context') and isinstance(exc.context, dict):
            merged_context.update(exc.context)

        # Also extract other exception attributes that might be useful
        # (e.g., line_number, column, template_file, error_count, etc.)
        for attr_name in dir(exc):
            if not attr_name.startswith('_') and attr_name not in ['args', 'with_traceback', 'context']:
                try:
                    attr_value = getattr(exc, attr_name)
                    # Only include simple types (not methods/callables)
                    if not callable(attr_value) and isinstance(attr_value, (str, int, float, bool, type(None))):
                        merged_context[attr_name] = attr_value
                except Exception:
                    pass  # Skip attributes that can't be accessed

        if context:
            merged_context.update(context)  # Passed context takes precedence

        user_error = translator.translate(exc, merged_context)
        return user_error.format_for_cli()
    except Exception as format_error:
        # If formatting fails, log and use safe fallback
        logger.error("Error formatting failed", exc_info=format_error)
        return safe_format_error(exc)