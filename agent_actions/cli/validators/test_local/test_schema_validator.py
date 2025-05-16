from pathlib import Path
from validators.schema_validator import SchemaValidator # Adjust import as needed

validator = SchemaValidator()

# --- Create dummy schema files for testing ---
schema_dir = Path("/tmp/my_agent_schemas")
schema_dir.mkdir(exist_ok=True, parents=True)

# Valid schema
(schema_dir / "valid_schema.json").write_text(json.dumps({
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Valid Person Schema",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer", "minimum": 0}
    },
    "required": ["name", "age"]
}))

# Invalid schema (syntax error)
(schema_dir / "invalid_json_schema.json").write_text("{'name': 'test',}") # Invalid JSON

# Invalid schema (logical error - required property not defined)
(schema_dir / "logical_error_schema.json").write_text(json.dumps({
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "Logical Error Schema",
    "type": "object",
    "properties": {
        "address": {"type": "string"}
    },
    "required": ["name"] # 'name' is not in properties
}))

# --- Test Case 1: Validate all schemas for an agent ---
print("\n--- Validating all agent schemas ---")
validation_data = {
    "agent_name": "TestAgent1",
    "schema_dir": schema_dir
}
if validator.validate(validation_data):
    print(f"Schema validation for agent '{validation_data['agent_name']}' passed.")
else:
    print(f"Schema validation for agent '{validation_data['agent_name']}' failed:")
    for err in validator.get_errors():
        print(f"  - {err}")

# --- Test Case 2: Validate specific schemas ---
print("\n--- Validating specific schemas ---")
validation_data_specific = {
    "agent_name": "TestAgent2",
    "schema_dir": schema_dir,
    "schema_files": ["valid_schema.json", "non_existent_schema.json"]
}
if validator.validate(validation_data_specific):
    print(f"Specific schema validation for agent '{validation_data_specific['agent_name']}' passed.")
else:
    print(f"Specific schema validation for agent '{validation_data_specific['agent_name']}' failed:")
    for err in validator.get_errors():
        print(f"  - {err}")

# --- Test Case 3: Test schema compatibility ---
print("\n--- Checking schema compatibility ---")
schema_a_data = {
    "type": "object", "properties": {"name": {"type": "string"}, "value": {"type": "number"}}
}
schema_b_data_compatible = {
    "type": "object", "properties": {"name": {"type": "string"}, "value": {"type": "number"}, "optional_field": {"type": "boolean"}}
}
schema_c_data_incompatible_type = {
    "type": "array"
}
schema_d_data_incompatible_prop = {
    "type": "object", "properties": {"name": {"type": "integer"}} # name type changed
}

if validator.check_schema_compatibility(schema_a_data, schema_b_data_compatible, "SchemaA", "SchemaB_Compatible"):
    print("SchemaA and SchemaB_Compatible are compatible.")
else:
    print("Compatibility check failed (SchemaA, SchemaB_Compatible):")
    for err in validator.get_errors(): print(f"  - {err}")

if validator.check_schema_compatibility(schema_a_data, schema_c_data_incompatible_type, "SchemaA", "SchemaC_IncompatibleType"):
    print("SchemaA and SchemaC_IncompatibleType are compatible (unexpected).")
else:
    print("Compatibility check failed (SchemaA, SchemaC_IncompatibleType):")
    for err in validator.get_errors(): print(f"  - {err}")

if validator.check_schema_compatibility(schema_a_data, schema_d_data_incompatible_prop, "SchemaA", "SchemaD_IncompatibleProp"):
    print("SchemaA and SchemaD_IncompatibleProp are compatible (unexpected).")
else:
    print("Compatibility check failed (SchemaA, SchemaD_IncompatibleProp):")
    for err in validator.get_errors(): print(f"  - {err}")


# Clean up dummy files
import shutil
shutil.rmtree(schema_dir, ignore_errors=True)