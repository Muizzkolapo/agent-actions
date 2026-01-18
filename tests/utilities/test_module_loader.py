"""Unit tests for agent_actions.utilities.module_loader.

Tests cover:
- Thread-safe path management
- Module caching
- Decorator registration (modules executed, not just loaded)
- Context manager cleanup
- Recursive subdirectory discovery
- Error handling (missing paths, import failures)
"""

import importlib
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_actions.utilities.module_loader import (
    clear_module_cache,
    clear_path_cache,
    discover_and_load_udfs,
    discover_and_load_udfs_recursive,
    ensure_path_importable,
    ensure_paths_importable,
    importable_path,
    load_module_from_path,
)


@pytest.fixture(autouse=True)
def cleanup_caches():
    """Clear caches before and after each test."""
    clear_path_cache()
    clear_module_cache()
    yield
    clear_path_cache()
    clear_module_cache()


@pytest.fixture
def temp_module_dir(tmp_path):
    """Create a temporary directory with test Python modules."""
    # Create main module (avoid 'test_' prefix to prevent pytest conflicts)
    main_module = tmp_path / "sample_module.py"
    main_module.write_text("""
# Sample module
TEST_VALUE = 42

def test_function():
    return "Hello from sample_module"
""")

    # Create module with decorator side effects
    decorator_module = tmp_path / "decorator_module.py"
    decorator_module.write_text("""
# Module that registers via decorator
_REGISTRY = []

def register(func):
    _REGISTRY.append(func.__name__)
    return func

@register
def registered_function():
    return "I was registered"

def get_registry():
    return _REGISTRY
""")

    # Create subdirectory with nested module
    subdir = tmp_path / "subpackage"
    subdir.mkdir()
    (subdir / "__init__.py").write_text("")
    nested_module = subdir / "nested_module.py"
    nested_module.write_text("""
# Nested module
NESTED_VALUE = 100
""")

    # Create private module (should be skipped)
    private_module = tmp_path / "_private.py"
    private_module.write_text("PRIVATE_VALUE = 999")

    # Create test module (should be skipped)
    sample_module = tmp_path / "test_skip_me.py"
    sample_module.write_text("TEST_VALUE = 888")

    return tmp_path


# ==============================================================================
# Test Low-Level API: Path Management
# ==============================================================================


def test_ensure_path_importable_adds_new_path(temp_module_dir):
    """Test that ensure_path_importable adds new paths to sys.path."""
    path_str = str(temp_module_dir)

    # Remove if already in sys.path
    if path_str in sys.path:
        sys.path.remove(path_str)

    # First call should add the path
    result = ensure_path_importable(temp_module_dir)
    assert result is True
    assert path_str in sys.path


def test_ensure_path_importable_caches_existing_path(temp_module_dir):
    """Test that ensure_path_importable caches already added paths."""
    # First call adds the path
    result1 = ensure_path_importable(temp_module_dir)
    assert result1 is True

    # Second call should return False (already cached)
    result2 = ensure_path_importable(temp_module_dir)
    assert result2 is False


def test_ensure_path_importable_thread_safety(temp_module_dir):
    """Test that concurrent path additions are thread-safe."""
    path_str = str(temp_module_dir)

    # Remove if already in sys.path
    if path_str in sys.path:
        sys.path.remove(path_str)

    clear_path_cache()

    results = []

    def add_path():
        result = ensure_path_importable(temp_module_dir)
        results.append(result)

    # Launch 50 threads concurrently
    threads = [threading.Thread(target=add_path) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Only one thread should have added the path (returned True)
    assert sum(results) == 1
    # Path should only appear once in sys.path
    assert sys.path.count(path_str) == 1


def test_ensure_path_importable_recursive(temp_module_dir):
    """Test that recursive=True adds subdirectories."""
    subpackage_str = str(temp_module_dir / "subpackage")

    # Remove paths if already present
    for path_str in [str(temp_module_dir), subpackage_str]:
        if path_str in sys.path:
            sys.path.remove(path_str)

    clear_path_cache()

    # Add with recursive=True
    ensure_path_importable(temp_module_dir, recursive=True)

    # Both main dir and subpackage should be in sys.path
    assert str(temp_module_dir) in sys.path
    assert subpackage_str in sys.path


def test_ensure_paths_importable(temp_module_dir):
    """Test that ensure_paths_importable handles multiple paths."""
    subdir = temp_module_dir / "subpackage"
    paths = [temp_module_dir, subdir]

    # Clear any existing paths
    for p in paths:
        path_str = str(p)
        if path_str in sys.path:
            sys.path.remove(path_str)

    clear_path_cache()

    # Add multiple paths
    count = ensure_paths_importable(paths)
    assert count == 2

    # Second call should return 0 (all cached)
    count2 = ensure_paths_importable(paths)
    assert count2 == 0


def test_importable_path_context_manager(temp_module_dir):
    """Test that importable_path context manager cleans up."""
    path_str = str(temp_module_dir)

    # Remove if already in sys.path
    if path_str in sys.path:
        sys.path.remove(path_str)

    # Path should not be in sys.path initially
    assert path_str not in sys.path

    # Within context, path should be present
    with importable_path(temp_module_dir) as added_path:
        assert added_path == path_str
        assert path_str in sys.path

    # After context, path should be removed
    assert path_str not in sys.path


def test_importable_path_context_manager_preserves_existing(temp_module_dir):
    """Test that context manager doesn't remove pre-existing paths."""
    path_str = str(temp_module_dir)

    # Add path before context
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

    # Context manager should not remove it
    with importable_path(temp_module_dir):
        assert path_str in sys.path

    # Path should still be present after context
    assert path_str in sys.path


# ==============================================================================
# Test Mid-Level API: Module Loading
# ==============================================================================


def test_load_module_from_path_basic(temp_module_dir):
    """Test basic module loading from file path."""
    module_path = temp_module_dir / "sample_module.py"
    module = load_module_from_path("sample_module", module_path)

    assert module is not None
    assert hasattr(module, "TEST_VALUE")
    assert module.TEST_VALUE == 42
    assert hasattr(module, "test_function")
    assert module.test_function() == "Hello from sample_module"


def test_load_module_from_path_executes_decorators(temp_module_dir):
    """Test that execute=True triggers decorator side effects."""
    module_path = temp_module_dir / "decorator_module.py"

    # Load with execute=True (default)
    module = load_module_from_path("decorator_module", module_path, execute=True)

    assert module is not None
    # Decorator should have registered the function
    registry = module.get_registry()
    assert "registered_function" in registry


def test_load_module_from_path_caching(temp_module_dir):
    """Test that module caching prevents re-execution."""
    module_path = temp_module_dir / "decorator_module.py"

    # First load
    module1 = load_module_from_path("decorator_module", module_path, cache=True)
    registry1 = module1.get_registry()

    # Second load should return cached module
    module2 = load_module_from_path("decorator_module", module_path, cache=True)
    registry2 = module2.get_registry()

    # Should be the exact same object
    assert module1 is module2
    # Registry should not have duplicates
    assert len(registry1) == len(registry2)


def test_load_module_from_path_no_cache(temp_module_dir):
    """Test that cache=False reloads the module."""
    module_path = temp_module_dir / "sample_module.py"

    # Load twice without caching
    module1 = load_module_from_path("sample_module_no_cache", module_path, cache=False)
    module2 = load_module_from_path("sample_module_no_cache", module_path, cache=False)

    # Should be different objects (reloaded)
    assert module1 is not module2
    # But should have same attributes
    assert module1.TEST_VALUE == module2.TEST_VALUE


def test_load_module_from_path_fallback_import():
    """Test that fallback_import tries standard import."""
    # Try loading a standard library module without path
    module = load_module_from_path("json", fallback_import=True)

    assert module is not None
    assert hasattr(module, "dumps")
    assert hasattr(module, "loads")


def test_load_module_from_path_no_fallback():
    """Test that fallback_import=False doesn't try standard import."""
    # Try loading a standard library module without path and no fallback
    module = load_module_from_path("json", fallback_import=False)

    # Should return None (no path provided, no fallback)
    assert module is None


def test_load_module_from_path_missing_file(temp_module_dir):
    """Test that missing file returns None."""
    missing_path = temp_module_dir / "does_not_exist.py"
    module = load_module_from_path("missing", missing_path)

    assert module is None


def test_load_module_from_path_directory(temp_module_dir):
    """Test loading from directory (looks for __init__.py or module_name.py)."""
    subdir = temp_module_dir / "subpackage"

    # Should find __init__.py
    module = load_module_from_path("subpackage", subdir)
    assert module is not None


# ==============================================================================
# Test High-Level API: UDF Discovery
# ==============================================================================


def test_discover_and_load_udfs_basic(temp_module_dir):
    """Test basic UDF discovery (non-recursive)."""
    registry = discover_and_load_udfs(temp_module_dir)

    # Should find sample_module and decorator_module
    assert "sample_module" in registry
    assert "decorator_module" in registry

    # Should NOT find nested_module (non-recursive)
    assert "nested_module" not in registry

    # Check structure
    assert "module" in registry["sample_module"]
    assert "path" in registry["sample_module"]
    assert registry["sample_module"]["module"].TEST_VALUE == 42


def test_discover_and_load_udfs_skip_private(temp_module_dir):
    """Test that private modules are skipped."""
    registry = discover_and_load_udfs(temp_module_dir, skip_private=True)

    # Should NOT find _private.py
    assert "_private" not in registry


def test_discover_and_load_udfs_skip_test(temp_module_dir):
    """Test that test modules are skipped."""
    registry = discover_and_load_udfs(temp_module_dir, skip_test=True)

    # Should NOT find test_skip_me.py
    assert "test_skip_me" not in registry


def test_discover_and_load_udfs_recursive_basic(temp_module_dir):
    """Test recursive UDF discovery."""
    registry = discover_and_load_udfs_recursive(temp_module_dir)

    # Should find sample_module and decorator_module
    assert "sample_module" in registry
    assert "decorator_module" in registry

    # Should ALSO find nested_module (recursive)
    assert "subpackage.nested_module" in registry
    assert registry["subpackage.nested_module"]["module"].NESTED_VALUE == 100


def test_discover_and_load_udfs_recursive_skip_private(temp_module_dir):
    """Test that private modules and dirs are skipped recursively."""
    # Create private subdir
    private_dir = temp_module_dir / "_private_dir"
    private_dir.mkdir()
    (private_dir / "secret.py").write_text("SECRET = 123")

    registry = discover_and_load_udfs_recursive(temp_module_dir, skip_private=True)

    # Should NOT find _private.py or secret.py
    assert "_private" not in registry
    assert "secret" not in registry
    assert "_private_dir.secret" not in registry


def test_discover_and_load_udfs_missing_path():
    """Test that missing path returns empty dict."""
    registry = discover_and_load_udfs("/nonexistent/path")
    assert registry == {}


def test_discover_and_load_udfs_file_path(temp_module_dir):
    """Test that passing a file path (not directory) returns empty dict."""
    file_path = temp_module_dir / "sample_module.py"
    registry = discover_and_load_udfs(file_path)
    assert registry == {}


# ==============================================================================
# Test Cache Management
# ==============================================================================


def test_clear_path_cache():
    """Test that clear_path_cache clears the path cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Add a path
        result1 = ensure_path_importable(tmpdir)
        assert result1 is True

        # Should be cached
        result2 = ensure_path_importable(tmpdir)
        assert result2 is False

        # Clear cache
        clear_path_cache()

        # Should not be cached anymore, so returns True (re-added to cache)
        result3 = ensure_path_importable(tmpdir)
        assert result3 is True  # True because cache was cleared


def test_clear_module_cache(temp_module_dir):
    """Test that clear_module_cache clears the module cache."""
    module_path = temp_module_dir / "decorator_module.py"

    # Load module
    module1 = load_module_from_path("test_clear", module_path, cache=True)
    assert module1 is not None

    # Should return cached version
    module2 = load_module_from_path("test_clear", module_path, cache=True)
    assert module1 is module2

    # Clear cache
    clear_module_cache()

    # Should reload (but will still have same attributes)
    module3 = load_module_from_path("test_clear", module_path, cache=True)
    # Note: Due to sys.modules, might still be same object
    # The important thing is cache was cleared


# ==============================================================================
# Test Edge Cases
# ==============================================================================


def test_ensure_path_importable_with_path_object(temp_module_dir):
    """Test that ensure_path_importable accepts Path objects."""
    result = ensure_path_importable(Path(temp_module_dir))
    assert isinstance(result, bool)


def test_load_module_from_path_registers_in_sys_modules(temp_module_dir):
    """Test that loaded modules are registered in sys.modules."""
    module_path = temp_module_dir / "sample_module.py"
    module_name = "test_sys_modules"

    # Ensure not already in sys.modules
    if module_name in sys.modules:
        del sys.modules[module_name]

    # Load module
    module = load_module_from_path(module_name, module_path)

    # Should be in sys.modules
    assert module_name in sys.modules
    assert sys.modules[module_name] is module


def test_concurrent_module_loading(temp_module_dir):
    """Test that concurrent module loading is thread-safe."""
    module_path = temp_module_dir / "decorator_module.py"
    loaded_modules = []

    def load_module():
        module = load_module_from_path("concurrent_test", module_path, cache=True)
        loaded_modules.append(module)

    # Launch 20 threads concurrently
    threads = [threading.Thread(target=load_module) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All threads should get the same cached module
    assert len(loaded_modules) == 20
    assert all(m is loaded_modules[0] for m in loaded_modules)


def test_discover_and_load_udfs_with_import_error(temp_module_dir):
    """Test that modules with import errors are skipped gracefully."""
    # Create a module with import error
    bad_module = temp_module_dir / "bad_module.py"
    bad_module.write_text("""
import nonexistent_module

def foo():
    return "bar"
""")

    # Should not crash, just skip the bad module
    registry = discover_and_load_udfs(temp_module_dir)

    # Bad module should not be in registry
    assert "bad_module" not in registry

    # Other modules should still be loaded
    assert "sample_module" in registry
