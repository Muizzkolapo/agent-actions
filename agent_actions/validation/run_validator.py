
from pydantic import BaseModel, DirectoryPath, Field, model_validator
from typing import Optional

class RunCommandArgs(BaseModel):
    """Pydantic model for the run command arguments."""
    agent: str = Field(..., description="Agent configuration file name without path or extension")
    user_code: Optional[DirectoryPath] = Field(None, description="Path to the user's code folder containing UDFs")
    use_tools: bool = Field(False, description="Enable tool usage for agents")
    force: bool = Field(False, description="Force execution even if validation warnings occur")
    parallel: bool = Field(False, description="Force parallel execution (overrides auto-detection)")
    no_parallel: bool = Field(False, description="Force sequential execution (overrides auto-detection)")
    concurrency_limit: int = Field(5, description="Maximum number of agents to run concurrently in parallel execution", ge=1, le=50)
    upstream: bool = Field(False, description="Recursively execute upstream dependent workflows")

    @model_validator(mode='after')
    def check_parallel_flags(self):
        """Ensure --parallel and --no-parallel are not used together."""
        if self.parallel and self.no_parallel:
            raise ValueError("Cannot specify both --parallel and --no-parallel flags")
        return self
