import json
from agent_actions.core.tooling import execute_user_defined_function

from typing import Dict, Any, Optional, Union
from agent_actions.processors.target_processor.data_generator import DataGenerator
from agent_actions.processors.source_processor.source_data_loader import SourceDataLoader
class ToolHandler:
    @staticmethod
    def invoke(
        agent_config: Dict[str, Any],
        context_data: Union[str, Dict],
        tool_args: Optional[Dict[str, Any]] = None, # Tool args are received here
        source_content: Optional[Any] = None # Also received here
        # ... potentially other args received from _invoke_vendor_handler ...
    ) -> Any:
        udf_name = agent_config.get('model_name')
        if not udf_name:
            raise ValueError("Tool vendor requires 'model_name' (UDF path) in agent config.")

        # Prepare kwargs for the UDF
        # Start with tool_args, and potentially add other context if the UDF might need it
        # (like source_content, agent_config, etc., similar to the conditional_clause UDF call)
        udf_kwargs = tool_args if tool_args is not None else {}

        # Although your current UDF only needs agent_name from tool_args,
        # it's good practice to pass other available context if the UDF signature allows it.
        # However, for the immediate fix, just ensuring tool_args are passed is key.
        # Let's stick to passing just tool_args for the immediate fix, as that's what the UDF expects.

        try:
            # THIS IS THE CRITICAL PART: Pass tool_args using **
            result = execute_user_defined_function(udf_name, context_data, **udf_kwargs)
            return result
        except Exception as e:
            # Re-raise with context
            raise RuntimeError(f"Error invoking tool UDF '{udf_name}': {e}")
