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
    safe_get_exception_message
)

logger = logging.getLogger(__name__)


@dataclass
class UserError:
    """Structured representation of a user-facing error."""

    category: str  # Configuration, Model, Provider, File, Network, Authentication
    title: str     # Brief description
    details: str   # What went wrong
    fix: str       # How to fix it
    context: Dict[str, Any]  # agent, file, field, etc.
    docs_url: Optional[str] = None

    def format_for_cli(self) -> str:
        """Format error for CLI display."""
        lines = [f"{self.category}: {self.title}"]

        if self.details:
            lines.extend(["", f"  Problem: {self.details}"])

        # Add context information
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
        context = context or {}

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

    def _handle_config_error(self, exc: Exception, root: Exception, message: str, context: Dict) -> UserError:
        """Handle configuration errors."""

        # Check for specific config error types
        if 'missing required field' in message.lower():
            field = self._extract_field_name(message, context)
            return UserError(
                category="Configuration Error",
                title="Missing required field",
                details=f"The configuration is missing required field '{field}'",
                fix=f"Add the '{field}' field to your agent configuration file",
                context=context,
                docs_url="https://docs.agent-actions.com/config/fields"
            )

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
    # ALWAYS log full error for debugging
    logger.error(
        "Error occurred during operation",
        exc_info=exc,
        extra={'context': context or {}}
    )

    try:
        translator = ErrorTranslator()
        user_error = translator.translate(exc, context)
        return user_error.format_for_cli()
    except Exception as format_error:
        # If formatting fails, log and use safe fallback
        logger.error("Error formatting failed", exc_info=format_error)
        return safe_format_error(exc)