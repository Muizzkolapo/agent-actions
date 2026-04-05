"""
Fake Data Generator for Testing.

Generates realistic fake data based on JSON schemas and prompts.
Uses seeded randomness for reproducibility while providing variety.
"""

import hashlib
import json
import logging
import random
from typing import Any

logger = logging.getLogger(__name__)


class FakeDataGenerator:
    """
    Generate realistic fake data matching JSON schemas.

    Features:
    - Field-name-aware generation (e.g., "email" field gets email format)
    - Prompt-aware generation (extracts context from prompts)
    - Seeded randomness for reproducibility
    - Attempt-based quality variation for testing retries

    The attempt number controls data "quality":
    - Attempt 1: Minimal data (short strings, small arrays)
    - Attempt 2: Slightly more data
    - Attempt 3+: Full data (long strings, complete arrays)
    """

    # Word counts per attempt (for string generation)
    WORD_COUNTS = {
        1: 3,  # Short - likely fails validation
        2: 8,  # Medium - may still fail validation
        3: 25,  # Long - should pass most validations
    }

    # Array sizes per attempt
    ARRAY_SIZES = {
        1: 1,  # Minimal
        2: 2,  # Small
        3: 3,  # Normal
    }

    # Word pools for generating varied text
    NOUNS = [
        "system",
        "user",
        "data",
        "process",
        "service",
        "module",
        "component",
        "interface",
        "function",
        "method",
        "class",
        "object",
        "instance",
        "request",
        "response",
        "message",
        "event",
        "action",
        "task",
        "job",
        "file",
        "document",
        "record",
        "entry",
        "item",
        "element",
        "node",
        "network",
        "server",
        "client",
        "database",
        "cache",
        "queue",
        "stream",
        "analysis",
        "report",
        "summary",
        "result",
        "output",
        "input",
        "config",
        "workflow",
        "pipeline",
        "stage",
        "step",
        "phase",
        "iteration",
        "cycle",
    ]

    ADJECTIVES = [
        "primary",
        "secondary",
        "active",
        "inactive",
        "pending",
        "complete",
        "valid",
        "invalid",
        "successful",
        "failed",
        "new",
        "updated",
        "deleted",
        "critical",
        "important",
        "standard",
        "custom",
        "default",
        "optional",
        "internal",
        "external",
        "public",
        "private",
        "shared",
        "isolated",
        "fast",
        "slow",
        "large",
        "small",
        "complex",
        "simple",
        "dynamic",
        "automated",
        "manual",
        "scheduled",
        "triggered",
        "continuous",
        "batch",
    ]

    VERBS = [
        "process",
        "analyze",
        "validate",
        "transform",
        "generate",
        "create",
        "update",
        "delete",
        "retrieve",
        "store",
        "send",
        "receive",
        "handle",
        "execute",
        "complete",
        "initialize",
        "configure",
        "optimize",
        "monitor",
        "report",
        "notify",
        "schedule",
        "trigger",
        "invoke",
        "dispatch",
        "route",
    ]

    FIRST_NAMES = [
        "James",
        "Emma",
        "Liam",
        "Olivia",
        "Noah",
        "Ava",
        "Oliver",
        "Sophia",
        "William",
        "Isabella",
        "Benjamin",
        "Mia",
        "Lucas",
        "Charlotte",
        "Henry",
        "Amelia",
        "Alexander",
        "Harper",
        "Sebastian",
        "Evelyn",
        "Jack",
        "Luna",
        "Aiden",
        "Camila",
        "Owen",
        "Gianna",
        "Samuel",
        "Abigail",
        "Ryan",
        "Ella",
    ]

    LAST_NAMES = [
        "Smith",
        "Johnson",
        "Williams",
        "Brown",
        "Jones",
        "Garcia",
        "Miller",
        "Davis",
        "Rodriguez",
        "Martinez",
        "Hernandez",
        "Lopez",
        "Gonzalez",
        "Wilson",
        "Anderson",
        "Thomas",
        "Taylor",
        "Moore",
        "Jackson",
        "Martin",
        "Lee",
        "Thompson",
        "White",
        "Harris",
        "Clark",
        "Lewis",
        "Robinson",
    ]

    COMPANIES = [
        "Acme Corp",
        "TechFlow Inc",
        "DataSync Systems",
        "CloudNine Solutions",
        "ByteWise Labs",
        "Quantum Dynamics",
        "NexGen Analytics",
        "PrimeStack",
        "CoreLogic",
        "Apex Innovations",
        "Stellar Systems",
        "FusionTech",
    ]

    DOMAINS = ["example.com", "test.org", "sample.net", "demo.io", "mock.dev"]

    CITIES = [
        "New York",
        "Los Angeles",
        "Chicago",
        "Houston",
        "Phoenix",
        "Philadelphia",
        "San Antonio",
        "San Diego",
        "Dallas",
        "San Jose",
        "Austin",
        "Seattle",
        "Denver",
        "Boston",
        "Nashville",
        "Portland",
        "Las Vegas",
        "Miami",
    ]

    COUNTRIES = ["USA", "Canada", "UK", "Germany", "France", "Australia", "Japan"]

    CATEGORIES = [
        "technology",
        "business",
        "finance",
        "healthcare",
        "education",
        "retail",
        "manufacturing",
        "logistics",
        "marketing",
        "sales",
        "support",
        "operations",
    ]

    STATUSES = ["pending", "active", "completed", "failed", "cancelled", "archived"]

    PRIORITIES = ["low", "medium", "high", "critical", "urgent"]

    # Current generation context
    _current_seed: int | None = None
    _current_prompt: str | None = None
    _rng: random.Random = random.Random()

    @classmethod
    def set_context(cls, seed: int | None = None, prompt: str | None = None):
        """
        Set generation context for reproducibility and prompt-awareness.

        Args:
            seed: Random seed for reproducibility (None = use hash of prompt or random)
            prompt: Prompt text to extract context from
        """
        cls._current_prompt = prompt

        if seed is not None:
            cls._current_seed = seed
        elif prompt:
            cls._current_seed = int(hashlib.md5(prompt.encode()).hexdigest()[:8], 16)
        else:
            cls._current_seed = random.randint(0, 2**32 - 1)

        cls._rng = random.Random(cls._current_seed)
        logger.debug(
            "FakeDataGenerator context set: seed=%s, has_prompt=%s",
            cls._current_seed,
            prompt is not None,
        )

    @classmethod
    def _get_rng(cls) -> random.Random:
        """Get the current random number generator."""
        if cls._rng is None:
            cls._rng = random.Random()  # type: ignore[unreachable]
        return cls._rng

    @classmethod
    def generate_from_schema(
        cls,
        schema: dict[str, Any],
        attempt: int = 1,
        field_name: str | None = None,
        prompt: str | None = None,
    ) -> Any:
        """
        Generate fake data matching a JSON schema.

        Args:
            schema: JSON schema dict
            attempt: Attempt number (1, 2, 3+) - affects data size/quality
            field_name: Name of the field being generated (for context-aware generation)
            prompt: Optional prompt to influence generation

        Returns:
            Generated data matching the schema structure
        """
        if prompt and prompt != cls._current_prompt:
            cls.set_context(prompt=prompt)

        if not isinstance(schema, dict):
            return cls._generate_string(attempt, field_name=field_name)  # type: ignore[unreachable]

        if "$ref" in schema:
            return cls._generate_string(attempt, field_name=field_name)

        if "const" in schema:
            return schema["const"]

        if "enum" in schema:
            enum_values = schema["enum"]
            if enum_values:
                rng = cls._get_rng()
                idx = (attempt - 1 + rng.randint(0, 100)) % len(enum_values)
                return enum_values[idx]
            return None

        # Handle oneOf/anyOf (pick based on attempt)
        if "oneOf" in schema and schema["oneOf"]:
            idx = (attempt - 1) % len(schema["oneOf"])
            return cls.generate_from_schema(schema["oneOf"][idx], attempt, field_name)
        if "anyOf" in schema and schema["anyOf"]:
            idx = (attempt - 1) % len(schema["anyOf"])
            return cls.generate_from_schema(schema["anyOf"][idx], attempt, field_name)
        if "allOf" in schema and schema["allOf"]:
            merged = {}
            for sub_schema in schema["allOf"]:
                if isinstance(sub_schema, dict):
                    result = cls.generate_from_schema(sub_schema, attempt, field_name)
                    if isinstance(result, dict):
                        merged.update(result)
            return merged if merged else cls._generate_string(attempt, field_name=field_name)

        # Handle unified schema format (fields list)
        if "fields" in schema and isinstance(schema["fields"], list):
            return cls._generate_from_fields(schema, attempt)

        # Get the type
        schema_type = schema.get("type")

        # Handle multiple types (e.g., ["string", "null"])
        if isinstance(schema_type, list):
            for t in schema_type:
                if t != "null":
                    schema_type = t
                    break
            else:
                schema_type = "null"

        # Generate based on type
        if schema_type == "string":
            return cls._generate_string(attempt, schema, field_name)
        elif schema_type == "number":
            return cls._generate_number(attempt, schema, field_name)
        elif schema_type == "integer":
            return cls._generate_integer(attempt, schema, field_name)
        elif schema_type == "boolean":
            return cls._generate_boolean(attempt, field_name)
        elif schema_type == "null":
            return None
        elif schema_type == "array":
            return cls._generate_array(schema, attempt, field_name)
        elif schema_type == "object":
            return cls._generate_object(schema, attempt)
        else:
            # No type specified - try to infer
            if "properties" in schema:
                return cls._generate_object(schema, attempt)
            if "items" in schema:
                return cls._generate_array(schema, attempt, field_name)
            return cls._generate_string(attempt, field_name=field_name)

    @classmethod
    def _generate_string(
        cls,
        attempt: int,
        schema: dict | None = None,
        field_name: str | None = None,
    ) -> str:
        """Generate a contextually appropriate string."""
        schema = schema or {}
        rng = cls._get_rng()
        field_lower = (field_name or "").lower()

        # Check for format-specific generation
        string_format = schema.get("format")
        if string_format:
            return cls._generate_formatted_string(string_format, attempt)

        # Check field name for context-aware generation
        if field_lower:
            # Email fields
            if "email" in field_lower:
                first = rng.choice(cls.FIRST_NAMES).lower()
                last = rng.choice(cls.LAST_NAMES).lower()
                domain = rng.choice(cls.DOMAINS)
                return f"{first}.{last}{attempt}@{domain}"

            # Name fields
            if field_lower in ("name", "fullname", "full_name", "username", "user_name"):
                return f"{rng.choice(cls.FIRST_NAMES)} {rng.choice(cls.LAST_NAMES)}"
            if field_lower in ("firstname", "first_name", "given_name"):
                return rng.choice(cls.FIRST_NAMES)
            if field_lower in ("lastname", "last_name", "surname", "family_name"):
                return rng.choice(cls.LAST_NAMES)

            # URL fields
            if any(x in field_lower for x in ["url", "link", "href", "uri", "website"]):
                path = rng.choice(cls.NOUNS)
                return f"https://{rng.choice(cls.DOMAINS)}/{path}/{attempt}"

            # ID fields
            if field_lower in ("id", "uid", "guid", "uuid") or field_lower.endswith("_id"):
                return f"{field_name or 'id'}_{rng.randint(1000, 9999)}_{attempt}"

            # Date/time fields
            if any(x in field_lower for x in ["date", "time", "created", "updated", "timestamp"]):
                month = rng.randint(1, 12)
                day = rng.randint(1, 28)
                return f"2024-{month:02d}-{day:02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z"

            # Title/subject fields
            if any(x in field_lower for x in ["title", "subject", "heading", "header"]):
                adj = rng.choice(cls.ADJECTIVES).capitalize()
                noun = rng.choice(cls.NOUNS).capitalize()
                verb = rng.choice(cls.VERBS).capitalize()
                return f"{adj} {noun} {verb} Report"

            # Description/summary/content fields
            if any(
                x in field_lower
                for x in ["description", "summary", "content", "body", "text", "details", "notes"]
            ):
                return cls._generate_sentence(attempt, rng)

            # Status fields
            if "status" in field_lower:
                return rng.choice(cls.STATUSES)

            # Priority fields
            if "priority" in field_lower:
                return rng.choice(cls.PRIORITIES)

            # Category/type fields
            if any(x in field_lower for x in ["category", "type", "kind", "group"]):
                return rng.choice(cls.CATEGORIES)

            # Company/organization fields
            if any(x in field_lower for x in ["company", "organization", "org", "employer"]):
                return rng.choice(cls.COMPANIES)

            # City/location fields
            if any(x in field_lower for x in ["city", "location", "place"]):
                return rng.choice(cls.CITIES)

            # Country fields
            if "country" in field_lower:
                return rng.choice(cls.COUNTRIES)

            # Phone fields
            if any(x in field_lower for x in ["phone", "mobile", "tel"]):
                return (
                    f"+1-{rng.randint(200, 999)}-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"
                )

            # Address fields
            if "address" in field_lower:
                return f"{rng.randint(100, 9999)} {rng.choice(cls.LAST_NAMES)} Street"

            # Code/identifier fields
            if any(x in field_lower for x in ["code", "sku", "ref", "reference"]):
                prefix = field_name[:3].upper() if field_name else "REF"
                return f"{prefix}-{rng.randint(10000, 99999)}"

            # Tag fields
            if "tag" in field_lower:
                return rng.choice(cls.CATEGORIES)

            # Message fields
            if "message" in field_lower or "reason" in field_lower:
                return cls._generate_sentence(attempt, rng)

        # Default: generate a varied sentence
        return cls._generate_sentence(attempt, rng)

    @classmethod
    def _generate_sentence(cls, attempt: int, rng: random.Random) -> str:
        """Generate a varied sentence based on attempt number."""
        word_count = cls.WORD_COUNTS.get(attempt, cls.WORD_COUNTS[3])

        words = []
        for i in range(word_count):
            if i % 4 == 0:
                words.append(rng.choice(cls.ADJECTIVES))
            elif i % 4 == 1:
                words.append(rng.choice(cls.NOUNS))
            elif i % 4 == 2:
                words.append(rng.choice(cls.VERBS))
            else:
                words.append(rng.choice(cls.NOUNS))

        sentence = " ".join(words)
        return sentence[0].upper() + sentence[1:] + "."

    @classmethod
    def _generate_formatted_string(cls, format_type: str, attempt: int) -> str:
        """Generate string based on format type."""
        rng = cls._get_rng()
        first = rng.choice(cls.FIRST_NAMES).lower()
        last = rng.choice(cls.LAST_NAMES).lower()

        formats = {
            "email": f"{first}.{last}{attempt}@{rng.choice(cls.DOMAINS)}",
            "uri": f"https://{rng.choice(cls.DOMAINS)}/{rng.choice(cls.NOUNS)}/{attempt}",
            "url": f"https://{rng.choice(cls.DOMAINS)}/{rng.choice(cls.NOUNS)}/{attempt}",
            "date": f"2024-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "date-time": f"2024-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:00Z",
            "time": f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}",
            "uuid": f"{rng.randint(0, 0xFFFFFFFF):08x}-{rng.randint(0, 0xFFFF):04x}-{rng.randint(0, 0xFFFF):04x}-{rng.randint(0, 0xFFFF):04x}-{rng.randint(0, 0xFFFFFFFFFFFF):012x}",
            "hostname": f"{rng.choice(cls.NOUNS)}{attempt}.{rng.choice(cls.DOMAINS)}",
            "ipv4": f"{rng.randint(1, 254)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(1, 254)}",
            "ipv6": f"2001:db8::{rng.randint(0, 0xFFFF):04x}:{rng.randint(0, 0xFFFF):04x}",
        }
        return formats.get(format_type, cls._generate_sentence(attempt, rng))

    @classmethod
    def _generate_number(
        cls,
        attempt: int,
        schema: dict | None = None,
        field_name: str | None = None,
    ) -> float:
        """Generate a number respecting schema constraints."""
        schema = schema or {}
        rng = cls._get_rng()
        field_lower = (field_name or "").lower()

        minimum = schema.get("minimum", 0)
        maximum = schema.get("maximum", 1000)
        multiple_of = schema.get("multipleOf")

        # Context-aware generation
        if field_lower:
            if any(x in field_lower for x in ["price", "cost", "amount", "total"]):
                value = round(rng.uniform(9.99, 999.99), 2)
            elif any(x in field_lower for x in ["rate", "ratio", "percent", "percentage"]):
                value = round(rng.uniform(0.01, 100.0), 2)
            elif any(x in field_lower for x in ["score", "rating"]):
                value = round(rng.uniform(1.0, 10.0), 1)
            elif "lat" in field_lower:
                value = round(rng.uniform(-90.0, 90.0), 6)
            elif "lon" in field_lower or "lng" in field_lower:
                value = round(rng.uniform(-180.0, 180.0), 6)
            else:
                value = round(rng.uniform(minimum, maximum), 2)
        else:
            # Base value varies by attempt
            base = 10.5 * attempt + rng.uniform(-5, 5)
            value = max(minimum, min(maximum, base))

        if multiple_of:
            value = round(value / multiple_of) * multiple_of

        return round(value, 2)

    @classmethod
    def _generate_integer(
        cls,
        attempt: int,
        schema: dict | None = None,
        field_name: str | None = None,
    ) -> int:
        """Generate an integer respecting schema constraints."""
        schema = schema or {}
        rng = cls._get_rng()
        field_lower = (field_name or "").lower()

        minimum = schema.get("minimum", 0)
        maximum = schema.get("maximum", 1000)

        # Context-aware generation
        if field_lower:
            if any(x in field_lower for x in ["age"]):
                return rng.randint(18, 80)
            if any(x in field_lower for x in ["year"]):
                return rng.randint(2020, 2025)
            if any(x in field_lower for x in ["count", "quantity", "qty", "num", "number"]):
                return rng.randint(1, 100) * attempt
            if any(x in field_lower for x in ["score", "rating", "rank"]):
                return rng.randint(1, 100)
            if any(x in field_lower for x in ["port"]):
                return rng.randint(1024, 65535)
            if "version" in field_lower:
                return attempt

        # Default: varies by attempt with randomness
        base = 10 * attempt + rng.randint(-5, 15)
        return max(minimum, min(maximum, base))  # type: ignore[no-any-return]

    @classmethod
    def _generate_boolean(cls, attempt: int, field_name: str | None = None) -> bool:
        """Generate a boolean."""
        rng = cls._get_rng()
        field_lower = (field_name or "").lower()

        # Context-aware: certain fields tend to be true/false
        if field_lower:
            if any(x in field_lower for x in ["enabled", "active", "valid", "success", "verified"]):
                return attempt >= 2  # True on later attempts
            if any(x in field_lower for x in ["disabled", "deleted", "failed", "error"]):
                return attempt < 2  # False on later attempts

        # Random with slight bias toward True
        return rng.random() > 0.4

    @classmethod
    def _generate_array(
        cls,
        schema: dict[str, Any],
        attempt: int,
        field_name: str | None = None,
    ) -> list[Any]:
        """Generate an array respecting schema constraints."""
        items_schema = schema.get("items", {})
        prefix_items = schema.get("prefixItems", [])
        min_items = schema.get("minItems", 0)
        max_items = schema.get("maxItems")

        # Size based on attempt
        size = cls.ARRAY_SIZES.get(attempt, cls.ARRAY_SIZES[3])
        size = max(min_items, size)
        if max_items is not None:
            size = min(max_items, size)

        result = []

        if prefix_items:
            for _i, item_schema in enumerate(prefix_items[:size]):
                result.append(cls.generate_from_schema(item_schema, attempt))
            remaining = size - len(prefix_items)
            for _ in range(max(0, remaining)):
                result.append(cls.generate_from_schema(items_schema, attempt))
        else:
            for _ in range(size):
                # Vary the seed slightly for each array item
                cls._get_rng().randint(0, 1000)
                result.append(cls.generate_from_schema(items_schema, attempt, field_name))

        return result

    @classmethod
    def _generate_object(cls, schema: dict[str, Any], attempt: int) -> dict[str, Any]:
        """Generate an object respecting schema constraints."""
        result = {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Generate all defined properties with field name context
        for prop_name, prop_schema in properties.items():
            result[prop_name] = cls.generate_from_schema(prop_schema, attempt, prop_name)

        # Ensure required fields are present
        for req_field in required:
            if req_field not in result:
                result[req_field] = cls._generate_string(attempt, field_name=req_field)

        return result

    @classmethod
    def _generate_from_fields(cls, schema: dict[str, Any], attempt: int) -> dict[str, Any]:
        """Generate data from a unified schema with a 'fields' list.

        Unified schemas use the format:
            {
                "name": "...",
                "fields": [
                    {"id": "title", "type": "string", ...},
                    {"id": "items", "type": "array", "items": {...}, ...},
                    {"id": "meta", "type": "object", "properties": {...}, ...},
                ],
                "required": ["title", "items"],
            }

        Each field's ``id`` becomes the key in the output dict. The field's
        ``type`` drives value generation. Object fields may carry
        ``properties``; array fields may carry ``items``.

        Args:
            schema: Unified schema dict containing a ``fields`` list.
            attempt: Attempt number controlling value quality/length.

        Returns:
            Dict mapping field ids to generated values.
        """
        result: dict[str, Any] = {}

        for field in schema["fields"]:
            if not isinstance(field, dict):
                continue
            field_id = field.get("id")
            if not field_id:
                continue

            field_type = field.get("type", "string")
            result[field_id] = cls._generate_field_value(field, field_type, attempt)

        # Ensure required fields are present even if not in the fields list
        for req_field in schema.get("required", []):
            if req_field not in result:
                result[req_field] = cls._generate_string(attempt, field_name=req_field)

        return result

    @classmethod
    def _generate_field_value(cls, field: dict[str, Any], field_type: str, attempt: int) -> Any:
        """Generate a value for a single unified-format field.

        Converts the field definition into a JSON Schema-compatible dict
        and delegates to the existing type-aware generators.

        Args:
            field: Unified field dict (has ``id``, ``type``, optionally
                   ``items``, ``properties``, ``enum``, etc.).
            field_type: The field's declared type.
            attempt: Attempt number for quality variation.

        Returns:
            Generated value appropriate for the field type.
        """
        field_id = field.get("id", "")

        # Handle enum values regardless of declared type
        if "enum" in field and field["enum"]:
            rng = cls._get_rng()
            idx = (attempt - 1 + rng.randint(0, 100)) % len(field["enum"])
            return field["enum"][idx]

        if field_type == "string":
            return cls._generate_string(attempt, field_name=field_id)
        elif field_type == "number":
            return cls._generate_number(attempt, field_name=field_id)
        elif field_type == "integer":
            return cls._generate_integer(attempt, field_name=field_id)
        elif field_type == "boolean":
            return cls._generate_boolean(attempt, field_name=field_id)
        elif field_type == "array":
            # Build a JSON Schema-style array schema from the field
            array_schema: dict[str, Any] = {"type": "array"}
            if "items" in field:
                array_schema["items"] = field["items"]
            else:
                array_schema["items"] = {"type": "string"}
            for key in ("minItems", "maxItems"):
                if key in field:
                    array_schema[key] = field[key]
            return cls._generate_array(array_schema, attempt, field_id)
        elif field_type == "object":
            # Build a JSON Schema-style object schema from the field
            obj_schema: dict[str, Any] = {"type": "object"}
            if "properties" in field:
                obj_schema["properties"] = field["properties"]
            if "required" in field:
                obj_schema["required"] = field["required"]
            return cls._generate_object(obj_schema, attempt)
        else:
            # Unknown type — fall back to string generation
            return cls._generate_string(attempt, field_name=field_id)

    @staticmethod
    def extract_schema_from_openai_request(body: dict[str, Any]) -> dict[str, Any] | None:
        """Extract JSON schema from OpenAI-format request body."""
        if not isinstance(body, dict):
            return None  # type: ignore[unreachable]

        # Check response_format.json_schema.schema
        response_format = body.get("response_format", {})
        if isinstance(response_format, dict):
            json_schema = response_format.get("json_schema", {})
            if isinstance(json_schema, dict):
                schema = json_schema.get("schema")
                if schema:
                    return schema  # type: ignore[no-any-return]
            schema = response_format.get("schema")
            if schema:
                return schema  # type: ignore[no-any-return]

        # Check tools[0].function.parameters
        tools = body.get("tools", [])
        if tools and isinstance(tools, list):
            for tool in tools:
                if isinstance(tool, dict):
                    function = tool.get("function", {})
                    if isinstance(function, dict):
                        parameters = function.get("parameters")
                        if parameters:
                            return parameters  # type: ignore[no-any-return]

        if "schema" in body:
            return body["schema"]  # type: ignore[no-any-return]

        return None

    @staticmethod
    def extract_prompt_from_openai_request(body: dict[str, Any]) -> str | None:
        """Extract prompt/user message from OpenAI-format request body."""
        if not isinstance(body, dict):
            return None  # type: ignore[unreachable]

        messages = body.get("messages", [])
        if messages and isinstance(messages, list):
            # Get the last user message or system message
            for msg in reversed(messages):
                if isinstance(msg, dict):
                    role = msg.get("role", "")
                    content = msg.get("content", "")
                    if role in ("user", "system") and content:
                        return content if isinstance(content, str) else str(content)

        return None

    @classmethod
    def generate_openai_response(
        cls, custom_id: str, body: dict[str, Any], attempt: int = 1
    ) -> dict[str, Any]:
        """Generate a complete OpenAI API response with fake data."""
        # Extract schema and prompt from request
        schema = cls.extract_schema_from_openai_request(body)
        prompt = cls.extract_prompt_from_openai_request(body)

        # Set context with prompt for reproducible, prompt-aware generation
        seed = int(hashlib.md5(f"{custom_id}:{attempt}".encode()).hexdigest()[:8], 16)
        cls.set_context(seed=seed, prompt=prompt)

        if schema:
            fake_data = cls.generate_from_schema(schema, attempt, prompt=prompt)
        else:
            # Fallback: generic response
            fake_data = {
                "result": cls._generate_sentence(attempt, cls._get_rng()),
                "status": "success",
            }

        response = {
            "id": f"chatcmpl-agac-{custom_id[:8] if custom_id else 'unknown'}",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "agac-model",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(fake_data),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": len(prompt.split()) * 2 if prompt else 100,
                "completion_tokens": 50,
                "total_tokens": (len(prompt.split()) * 2 if prompt else 100) + 50,
            },
        }

        return response

    @classmethod
    def generate_text_response(cls, prompt: str, attempt: int = 1) -> str:
        """
        Generate a plain text response for non-JSON mode.

        Args:
            prompt: The prompt to respond to
            attempt: Attempt number

        Returns:
            Generated text response
        """
        seed = int(hashlib.md5(f"{prompt}:{attempt}".encode()).hexdigest()[:8], 16)
        cls.set_context(seed=seed, prompt=prompt)
        rng = cls._get_rng()

        # Generate multiple sentences based on attempt
        sentences = []
        num_sentences = cls.WORD_COUNTS.get(attempt, cls.WORD_COUNTS[3]) // 5

        for _ in range(max(1, num_sentences)):
            sentences.append(cls._generate_sentence(attempt, rng))

        return " ".join(sentences)
