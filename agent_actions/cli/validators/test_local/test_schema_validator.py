from pathlib import Path
from validators.schema_validator import SchemaValidator # Adjust import as needed

# --- Setup ---
# Create a dummy schema for testing
schema_dir = Path("/tmp/test_schemas")
schema_dir.mkdir(exist_ok=True)
schema_content = """
{
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"}
    },
    "required": ["name", "age"]
}
"""
(schema_dir / "my_schema.json").write_text(schema_content)

# --- Test Case 1: Valid Data ---
print("--- Running Test Case 1: Valid Data ---")
validator_valid = SchemaValidator()
data_valid = {
    "operation": "validate_data",
    "schema_name": "my_schema",
    "data": {"name": "John Doe", "age": 30},
    "schema_dir": schema_dir
}
if validator_valid.validate(data_valid):
    print("Data validation passed.")
else:
    print("Data validation failed:")
    for error in validator_valid.get_errors():
        print(f"- {error}")
print("-" * 20)


# --- Test Case 2: Invalid Data (Missing Required Property) ---
print("--- Running Test Case 2: Invalid Data ---")
validator_invalid = SchemaValidator()
data_invalid = {
    "operation": "validate_data",
    "schema_name": "my_schema",
    "data": {"name": "Jane Doe"}, # Missing 'age'
    "schema_dir": schema_dir
}
if not validator_invalid.validate(data_invalid):
    print("Data validation failed as expected.")
    for error in validator_invalid.get_errors():
        print(f"- {error}")
else:
    print("Validation passed, but it should have failed.")
print("-" * 20)


# --- Test Case 3: Schema Not Found ---
print("--- Running Test Case 3: Schema Not Found ---")
validator_no_schema = SchemaValidator()
data_no_schema = {
    "operation": "validate_data",
    "schema_name": "non_existent_schema",
    "data": {"name": "Test", "age": 100},
    "schema_dir": schema_dir
}
if not validator_no_schema.validate(data_no_schema):
    print("Validation failed as expected because schema was not found.")
    for error in validator_no_schema.get_errors():
        print(f"- {error}")
else:
    print("Validation passed, but it should have failed.")
print("-" * 20)

# Cleanup
import shutil
shutil.rmtree(schema_dir)
print("Cleanup complete.")
