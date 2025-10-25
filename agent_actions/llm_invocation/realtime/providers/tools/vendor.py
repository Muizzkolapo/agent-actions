import json
from agent_actions.core.tooling import execute_user_defined_function
from agent_actions.utilities.constants import MODEL_NAME_KEY
from typing import Dict, Any, Optional, Union

class ToolHandler:

    @staticmethod
    def invoke(agent_config: Dict[str, Any], context_data: Union[str, Dict], tool_args: Optional[Dict[str, Any]]=None, source_content: Optional[Any]=None) -> Any:
        """
        Invoke a user-defined function (UDF) specified in the configuration.
        """
        model_name = agent_config.get(MODEL_NAME_KEY)
        if not model_name:
            from agent_actions.shared.exceptions import ConfigurationError
            raise ConfigurationError("Tool vendor requires 'model_name' (UDF path) in agent config", context={'vendor': 'tool', 'missing_field': 'model_name', 'agent_config_keys': list(agent_config.keys())})
        side_output = agent_config.get('side_output', False)
        udf_kwargs = tool_args if tool_args is not None else {}
        response = execute_user_defined_function(model_name, context_data, **udf_kwargs)
        if side_output:
            condition, result = response
            if condition:
                return {'result': json.loads(result), 'side_output': True}
            else:
                return json.loads(result)
        elif isinstance(response, str):
            return json.loads(response)
        else:
            return response