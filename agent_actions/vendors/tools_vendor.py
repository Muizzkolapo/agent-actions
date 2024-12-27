import json
from agent_actions.core.tooling import execute_user_defined_function


class ToolHandler:
    @staticmethod
    def invoke(agent_config, context_data):
        """
        Invoke a user-defined function (UDF) specified in the configuration.

        Parameters:
            agent_config (dict): The agent configuration containing the UDF name.
            udf_name (str): The name of the UDF to invoke.
            context_data (dict): The input data to process.

        Returns:
            The result of the UDF execution.
        """
        model_name = agent_config['model_name']
        side_output = agent_config.get('side_output', False)
        
        response = execute_user_defined_function(model_name, context_data)
        
        if side_output:
            condition, result = response
            if condition:
                return {'result': json.loads(result), 'side_output': True}
            else:
                return json.loads(result)
        else:
            return json.loads(response)