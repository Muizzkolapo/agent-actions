import os
import json
from agent_actions.core.utils import process_as_string,ensure_list
import logging
logging.basicConfig(level=logging.ERROR)
from agent_actions.core.tooling import execute_user_defined_function


class ToolHandler:
    @staticmethod
    def invoke(agent_config, input_documentation):
        """
        Invoke a user-defined function (UDF) specified in the configuration.

        Parameters:
            agent_config (dict): The agent configuration containing the UDF name.
            udf_name (str): The name of the UDF to invoke.
            input_documentation (dict): The input data to process.

        Returns:
            The result of the UDF execution.
        """
        model_name = agent_config['model_name']
        side_output = agent_config.get('side_output', False)
        
        response = execute_user_defined_function(model_name, input_documentation)
        
        if side_output:
            condition, result = response
            if condition:
                return {'result': json.loads(result), 'side_output': True}
            else:
                return json.loads(result)
        else:
            return json.loads(response)