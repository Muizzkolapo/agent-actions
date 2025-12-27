"""
Groq LLM client for agent-actions.

Provides implementation of call_json() and call_non_json() methods
for Groq API integration, supporting models like Llama3.
"""

import json
from textwrap import dedent

from groq import Groq  # pylint: disable=import-error

from agent_actions.errors import VendorAPIError  # New modular pattern!
from agent_actions.llm_invocation.providers.client_base import BaseClient
from agent_actions.llm_invocation.providers.usage_tracker import set_last_usage
from agent_actions.preprocessing.transformation.data_transformer import DataTransformer
from agent_actions.preprocessing.transformation.string_transformer import StringProcessor
from agent_actions.utilities.constants import MODEL_NAME_KEY


class GroqClient(BaseClient):
    """Groq API client for JSON and non-JSON LLM invocations."""

    @staticmethod
    def call_json(api_key, agent_config, prompt_config, context_data, schema):
        groq = Groq(api_key=api_key)
        model_name = agent_config[MODEL_NAME_KEY]
        context_data_str = StringProcessor.process_as_string(context_data)
        prompt = f"\n            <|begin_of_user_instruction|>:{prompt_config} :<|end_of_user_instruction|>\n\n            <|begin_of_text|>:: {context_data_str} :<|end_of_text|>\n\n            <|begin_of_output_schema|> :WRITE OUTPUTS IN JSON SCHEMA: {json.dumps(schema)}. : <|end_of_output_schema|>\n        "
        prompt_dedent = dedent(prompt)
        try:
            llm = groq.chat.completions.create(
                messages=[{"role": "system", "content": prompt_dedent}],
                model=model_name,
                response_format={"type": "json_object"},
            )
            # Extract token usage (OpenAI-compatible format)
            if llm.usage:
                set_last_usage(
                    {
                        "input_tokens": llm.usage.prompt_tokens,
                        "output_tokens": llm.usage.completion_tokens,
                        "total_tokens": llm.usage.total_tokens,
                    }
                )
            response_temp = llm.choices[0].message.content
            response = json.loads(response_temp)
            response_list = DataTransformer.ensure_list(response)
            return response_list
        except Exception as e:
            raise VendorAPIError(
                "Failed to create chat completion with Groq Llama 3",
                context={
                    "model_name": model_name,
                    "vendor": "groq",
                    "api_operation": "chat.completions.create",
                },
                cause=e,
            ) from e

    @staticmethod
    def call_non_json(api_key, agent_config, prompt_config, context_data):
        groq = Groq(api_key=api_key)
        model_name = agent_config[MODEL_NAME_KEY]
        context_data_str = StringProcessor.process_as_string(context_data)
        prompt = f"\n                Instructions: {prompt_config}\n                Input Text: {str(context_data_str)}\n                \n                Please provide a direct response without any JSON formatting.\n                Begin your response here:\n            "
        prompt_dedent = dedent(prompt).strip()
        completion_kwargs = {
            "messages": [{"role": "system", "content": prompt_dedent}],
            "model": model_name,
            "temperature": 0.7,
            "max_tokens": 1000,
        }
        response = groq.chat.completions.create(**completion_kwargs)
        # Extract token usage (OpenAI-compatible format)
        if response.usage:
            set_last_usage(
                {
                    "input_tokens": response.usage.prompt_tokens,
                    "output_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            )
        try:
            response_content = response.choices[0].message.content
            return [response_content]
        except (AttributeError, IndexError, TypeError) as e:
            raise VendorAPIError(
                "Error parsing non-JSON response from Groq Llama 3",
                context={
                    "model_name": model_name,
                    "vendor": "groq",
                    "response": str(response)[:200],
                },
                cause=e,
            )
        except Exception as e:
            raise VendorAPIError(
                "Failed to get non-JSON chat completion from Groq Llama 3",
                context={
                    "model_name": model_name,
                    "vendor": "groq",
                    "api_operation": "chat.completions.create",
                },
                cause=e,
            ) from e
