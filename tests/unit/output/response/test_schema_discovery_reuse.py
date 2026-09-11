"""Tests for schema discovery reuse across load_schema calls."""

from __future__ import annotations

from pathlib import Path

from agent_actions.output.response.loader import SchemaLoader


def _make_schemas(tmp_path: Path, count: int) -> list[str]:
    (tmp_path / "agent_actions.yml").write_text("schema_path: schema\n")
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    names = []
    for i in range(count):
        name = f"schema_{i}"
        (schema_dir / f"{name}.yml").write_text(f"fields:\n  - name: field_{i}\n    type: string\n")
        names.append(name)
    return names


class TestSchemaDiscoveryReuse:
    def test_walks_schema_tree_once_for_many_loads(self, tmp_path, monkeypatch):
        """Loading N schemas walks the schema tree once, not N times."""
        names = _make_schemas(tmp_path, 12)

        walks: list[Path] = []
        real_rglob = Path.rglob

        def counting_rglob(self, pattern, *args, **kwargs):
            walks.append(self)
            return real_rglob(self, pattern, *args, **kwargs)

        monkeypatch.setattr(Path, "rglob", counting_rglob)
        loaded = [SchemaLoader.load_schema(n, project_root=tmp_path) for n in names]
        monkeypatch.undo()

        assert [s["fields"][0]["name"] for s in loaded] == [f"field_{i}" for i in range(12)]
        assert len(walks) == 1

    def test_enumeration_sees_a_schema_added_after_a_load(self, tmp_path):
        """discover_schema_files reports current state, not a prior walk."""
        _make_schemas(tmp_path, 2)
        SchemaLoader.load_schema("schema_0", project_root=tmp_path)

        (tmp_path / "schema" / "added_later.yml").write_text(
            "fields:\n  - name: x\n    type: string\n"
        )

        assert "added_later" in SchemaLoader.discover_schema_files(tmp_path)
        assert (
            SchemaLoader.load_schema("added_later", project_root=tmp_path)["fields"][0]["name"]
            == "x"
        )
