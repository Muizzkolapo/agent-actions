# Documentation Generation Scripts

This folder contains scripts for generating API documentation using [pdoc](https://pdoc.dev/).

## Scripts

### `generate_docs.sh`
Shell script for generating documentation on Unix/Mac systems.

**Usage:**
```bash
./docs_scripts/generate_docs.sh
```

### `generate_docs.py`
Cross-platform Python script for generating documentation.

**Usage:**
```bash
python docs_scripts/generate_docs.py
```

## How It Works

Both scripts:
1. Automatically change to the repository root directory
2. Remove old `pdoc_docs/` if it exists
3. Generate fresh HTML documentation for all modules
4. Output to `pdoc_docs/` in the repository root

## Output

- **Location**: `../pdoc_docs/` (repository root)
- **Format**: HTML
- **Files**: ~178 HTML files
- **Size**: ~29MB

## Notes

- Scripts can be run from any directory
- Output is always in the repository root
- `pdoc_docs/` is gitignored (not committed)

For more information, see `DOCUMENTATION.md` in the repository root.
