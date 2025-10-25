"""
Signature computation engine that leverages existing utilities.

This module computes input and output signatures for agent actions
by reusing the existing LLMContextUtils and PromptUtils functionality.
"""
from typing import Dict, Any, Optional
from agent_actions.state_management.signatures import InputSignature, OutputSignature
from agent_actions.preprocessing.prompt_utils import PromptUtils

class SignatureComputer:
    """Computes signatures by reusing existing field computation utilities."""

    @staticmethod
    def compute_output_signature(agent_config: Dict[str, Any], schema_registry: Optional[Dict[str, Any]]=None) -> OutputSignature:
        """Extract output signature from agent config.
        
        Args:
            agent_config: Agent configuration dictionary
            schema_registry: Optional registry for resolving schema references
            
        Returns:
            OutputSignature with schema, observe, and dropped fields
        """
        output_schema = agent_config.get('output_schema', {})
        if isinstance(output_schema, str) and schema_registry:
            resolved_schema = schema_registry.get(output_schema, {})
            output_schema = resolved_schema if isinstance(resolved_schema, dict) else {}
        elif isinstance(output_schema, str):
            output_schema = {}
        elif not isinstance(output_schema, dict):
            output_schema = {}
        schema_fields = list(output_schema.get('properties', {}).keys())
        observe_fields = agent_config.get('observe', agent_config.get('observe', []))
        dropped_fields = agent_config.get('drops', agent_config.get('drops', []))
        return OutputSignature(schema_fields=schema_fields, observe_fields=observe_fields, dropped_fields=dropped_fields)

    @staticmethod
    def compute_input_signature(agent_config: Dict[str, Any], dependency_configs: Dict[str, Dict[str, Any]], schema_registry: Optional[Dict[str, Any]]=None) -> InputSignature:
        """Extract input signature from agent config and dependencies.
        
        Args:
            agent_config: Agent configuration dictionary
            dependency_configs: Map of dependency name to their configs
            schema_registry: Optional registry for resolving schema references
            
        Returns:
            InputSignature with dependency, source, loop, and workflow fields
        """
        input_sig = InputSignature()
        prompt = agent_config.get('prompt', '')
        if not prompt:
            return input_sig
        references = PromptUtils.parse_field_references(prompt)
        for ref in references:
            ref_name = ref['reference']
            field_path = ref['field_path']
            field_name = '.'.join(field_path) if field_path else ref_name
            if ref_name in dependency_configs:
                if ref_name not in input_sig.dependencies:
                    input_sig.dependencies[ref_name] = []
                if field_name not in input_sig.dependencies[ref_name]:
                    input_sig.dependencies[ref_name].append(field_name)
            elif ref_name == 'source':
                if field_name == 'source':
                    field_name = 'source'
                if field_name not in input_sig.source_fields:
                    input_sig.source_fields.append(field_name)
            elif ref_name == 'loop':
                if field_name not in input_sig.loop_fields:
                    input_sig.loop_fields.append(field_name)
            elif ref_name == 'workflow':
                if field_name not in input_sig.workflow_fields:
                    input_sig.workflow_fields.append(field_name)
        return input_sig

    @staticmethod
    def validate_field_availability(input_sig: InputSignature, dependency_signatures: Dict[str, OutputSignature]) -> Dict[str, Any]:
        """Validate that all input fields are available from dependencies.
        
        Args:
            input_sig: Input signature to validate
            dependency_signatures: Map of dependency names to their output signatures
            
        Returns:
            Dict with 'valid' boolean and 'errors' list
        """
        errors = []
        for dep_name, required_fields in input_sig.dependencies.items():
            if dep_name not in dependency_signatures:
                errors.append(f"Dependency '{dep_name}' not found in available dependencies")
                continue
            dep_output = dependency_signatures[dep_name]
            available_fields = dep_output.get_available_fields()
            for field in required_fields:
                base_field = field.split('.')[0]
                if base_field not in available_fields:
                    errors.append(f"Field '{field}' not available from dependency '{dep_name}'. Available fields: {sorted(available_fields)}")
        return {'valid': len(errors) == 0, 'errors': errors}