"""
Signature data structures for agent action input/output field flow.

This module provides minimal data structures to represent field signatures
for agent actions, enabling programmatic inspection of what fields flow
between agents in a workflow.
"""

from enum import Enum
from typing import Dict, List, Optional, Set
from pydantic import BaseModel


class FieldSource(str, Enum):
    """Where a field originates from."""
    SCHEMA = "schema"
    OBSERVE = "observe" 
    SOURCE = "source"
    LOOP = "loop"
    WORKFLOW = "workflow"


class FieldInfo(BaseModel):
    """Minimal field metadata."""
    name: str
    source: FieldSource
    

class InputSignature(BaseModel):
    """Fields required by an action.
    
    Tracks which fields an action needs from its dependencies,
    source data, loops, and workflow context.
    """
    dependencies: Dict[str, List[str]] = {}  # dep_name -> field_names
    source_fields: List[str] = []
    loop_fields: List[str] = []  # Reserved for future use
    workflow_fields: List[str] = []  # Reserved for future use
    
    def get_all_fields(self) -> Set[str]:
        """Get all fields this action needs from any source."""
        fields = set(self.source_fields)
        fields.update(self.loop_fields)
        fields.update(self.workflow_fields)
        
        # Add all dependency fields
        for dep_fields in self.dependencies.values():
            fields.update(dep_fields)
            
        return fields
        
    def get_dependency_fields(self, dep_name: str) -> List[str]:
        """Get fields needed from a specific dependency."""
        return self.dependencies.get(dep_name, [])


class OutputSignature(BaseModel):
    """Fields produced by an action.
    
    Tracks which fields an action outputs based on its schema,
    observe directives, and drops.
    """
    schema_fields: List[str] = []
    observe_fields: List[str] = []  
    dropped_fields: List[str] = []
    
    def get_available_fields(self) -> Set[str]:
        """Get fields available to downstream actions.
        
        Uses the formula: (schema_fields + observe_fields) - dropped_fields
        """
        available = set(self.schema_fields) | set(self.observe_fields)
        available -= set(self.dropped_fields)
        return available
        
    def get_all_field_names(self) -> Set[str]:
        """Get all field names referenced in this signature."""
        all_fields = set(self.schema_fields) | set(self.observe_fields) | set(self.dropped_fields)
        return all_fields