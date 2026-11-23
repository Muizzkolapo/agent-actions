"""Build a project on disk whose schema files resolve through the schema route."""

from pathlib import Path
from typing import Any

import yaml

PROJECT_CONFIG = "schema_path: schema\n"


def schema_project(
    root: Path,
    schemas: dict[str, Any],
    *,
    where: str = "schema",
    project_config: str = PROJECT_CONFIG,
) -> Path:
    """Write *project_config* as ``agent_actions.yml`` and each schema as ``<where>/<name>.yml``.

    Returns *root*. A second call on one root adds files beside the first call's.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "agent_actions.yml").write_text(project_config)
    schema_dir = root / where
    schema_dir.mkdir(parents=True, exist_ok=True)
    for name, data in schemas.items():
        (schema_dir / f"{name}.yml").write_text(yaml.safe_dump(data))
    return root
