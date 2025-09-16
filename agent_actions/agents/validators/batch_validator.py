
from pydantic import BaseModel, DirectoryPath, Field
from typing import Optional

class BatchCommandArgs(BaseModel):
    """Pydantic model for the batch command arguments."""
    batch_id: Optional[str] = Field(None, description="The ID of the batch job.")
    output_dir: Optional[DirectoryPath] = Field(None, description="Directory to save the retrieved results.")
