from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class ToolMetadata(BaseModel):
    name: str = Field(description="Name of the tool")
    description: str = Field(description="Purpose and guidelines for the tool")
    input_schema: Dict[str, Any] = Field(description="JSON Schema for tool input arguments")
    output_schema: Dict[str, Any] = Field(description="JSON Schema for tool output results")

class BaseTool:
    def __init__(self, metadata: ToolMetadata):
        self.metadata = metadata

    async def run(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the tool action synchronously or asynchronously.
        Subclasses must implement this method.
        """
        raise NotImplementedError("Subclasses must implement run")
