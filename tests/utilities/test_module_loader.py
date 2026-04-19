"""Unit tests for agent_actions.utils.module_loader."""

import sys

import pytest

from agent_actions.utils.module_loader import (
    _resolve_module_file,
    clear_module_cache,
    discover_and_load_udfs,
    discover_and_load_udfs_recursive,
    load_module_from_directory,
    load_module_from_path,
)


@pytest.fixture(autouse=True)
def cleanup_caches():
    """Clear caches and test modules before and after each test."""
    modules_before = set(sys.modules.keys())

    clear_module_cache()
    yield
    clear_module_cache()

    test_module_prefixes = (
        "sample_module",
        "decorator_module",
        "subpackage",
        "test_module",
        "test_sys_modules",
        "test_clear",
        "concurrent_test",
        "bad_module",
        "no_exec_module",
        "transient_missing",
        "cached_missing",
        "broken_exec",
        "fallback_ok",
        "dir_mod",
        "mypkg",
    )
    modules_to_remove = [
        name
        for name in sys.modules
        if name not in modules_before
        and any(name.startswith(prefix) for prefix in test_module_prefixes)
    ]
    for name in modules_to_remove:
        del sys.modules[name]


@pytest.fixture
def temp_module_dir(tmp_path):
    """Create a temporary directory with test Python modules."""
    main_module = tmp_path / "sample_module.py"
    main_module.write_text("""
# Sample module
TEST_VALUE = 42

def test_function():
    return "Hello from sample_module"
""")

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

    subdir = tmp_path / "subpackage"
    subdir.mkdir()
    (subdir / "__init__.py").write_text("")
    nested_module = subdir / "nested_module.py"
    nested_module.write_text("""
# Nested module
NESTED_VALUE = 100
""")

    private_module = tmp_path / "_private.py"
    private_module.write_text("PRIVATE_VALUE = 999")

    sample_module = tmp_path / "test_skip_me.py"
    sample_module.write_text("TEST_VALUE = 888")

    return tmp_path


def test_resolve_module_file_simple_name(tmp_path):
    """Resolve simple module name to dir/mymod.py."""
    (tmp_path / "mymod.py").write_text("X = 1")
    result = _resolve_module_file("mymod", tmp_path)
    assert result == tmp_path / "mymod.py"


def test_resolve_module_file_dotted_name(tmp_path):
    """Resolve dotted module name to dir/pkg/mod.py."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("X = 2")
    result = _resolve_module_file("pkg.mod", tmp_path)
    assert result == pkg / "mod.py"


def test_resolve_module_file_package(tmp_path):
    """Resolve package name to dir/pkg/__init__.py."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("X = 3")
    result = _resolve_module_file("pkg", tmp_path)
    assert result == pkg / "__init__.py"


def test_resolve_module_file_not_found(tmp_path):
    """Return None for non-existent module."""
    result = _resolve_module_file("nonexistent", tmp_path)
    assert result is None


def test_resolve_module_file_empty_name(tmp_path):
    """Return None for empty module name."""
    result = _resolve_module_file("", tmp_path)
    assert result is None


def test_resolve_module_file_subdirectory(tmp_path):
    """Recursive fallback finds module in a subdirectory."""
    subdir = tmp_path / "qanalabs-quiz-gen"
    subdir.mkdir()
    target = subdir / "my_function.py"
    target.write_text("X = 1")
    result = _resolve_module_file("my_function", tmp_path)
    assert result == target


def test_resolve_module_file_flat_takes_precedence(tmp_path):
    """Flat path is preferred over recursive match when both exist."""
    flat = tmp_path / "my_function.py"
    flat.write_text("X = 1")
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "my_function.py").write_text("X = 2")
    result = _resolve_module_file("my_function", tmp_path)
    assert result == flat


def test_resolve_module_file_ambiguous_returns_none(tmp_path, capsys):
    """Ambiguous match (same name in multiple subdirs) returns None and logs error."""
    for name in ("sub_a", "sub_b"):
        d = tmp_path / name
        d.mkdir()
        (d / "my_function.py").write_text("X = 1")
    result = _resolve_module_file("my_function", tmp_path)
    assert result is None
    assert "Ambiguous dispatch_task resolution" in capsys.readouterr().err


def test_resolve_module_file_dotted_name_no_recursive(tmp_path):
    """Dotted module names use direct path only, no recursive fallback."""
    subdir = tmp_path / "deep"
    subdir.mkdir()
    pkg = subdir / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text("X = 1")
    # Direct path: tmp_path/pkg/mod.py does not exist
    # Recursive would find deep/pkg/mod.py but dotted names skip recursive
    result = _resolve_module_file("pkg.mod", tmp_path)
    assert result is None


def test_load_module_from_directory_basic(tmp_path):
    """Load a simple module without mutating sys.path."""
    (tmp_path / "dir_mod.py").write_text("VALUE = 99")
    path_before = list(sys.path)
    module = load_module_from_directory("dir_mod", tmp_path, cache=False)
    assert module is not None
    assert module.VALUE == 99
    assert sys.path == path_before, "sys.path must not be mutated"


def test_load_module_from_directory_dotted(tmp_path):
    """Load a nested dotted module from a directory."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "sub.py").write_text("NESTED = 42")
    module = load_module_from_directory("mypkg.sub", tmp_path, cache=False)
    assert module is not None
    assert module.NESTED == 42


def test_load_module_from_directory_not_found_fallback(tmp_path):
    """Fall back to importlib.import_module when file not in dir."""
    module = load_module_from_directory("json", tmp_path, cache=False)
    assert module is not None
    assert hasattr(module, "dumps")


def test_load_module_from_directory_broken_file_no_fallback(tmp_path):
    """Return None when file exists but has broken code — must not fall back."""
    broken = tmp_path / "broken_dir_mod.py"
    broken.write_text("raise RuntimeError('boom')")
    module = load_module_from_directory("broken_dir_mod", tmp_path, cache=False)
    assert module is None
    assert "broken_dir_mod" not in sys.modules


def test_load_module_from_directory_fallback_disabled(tmp_path):
    """Return None when file not found and fallback_import=False."""
    module = load_module_from_directory("json", tmp_path, cache=False, fallback_import=False)
    assert module is None


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
    module = load_module_from_path("decorator_module", module_path, execute=True)

    assert module is not None
    registry = module.get_registry()
    assert "registered_function" in registry


def test_load_module_from_path_no_execute_skips_decorators(tmp_path):
    """Test that execute=False skips decorator side effects."""
    decorator_module = tmp_path / "no_exec_module.py"
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

    module = load_module_from_path("no_exec_module", decorator_module, execute=False, cache=False)

    assert module is not None
    assert not hasattr(module, "_REGISTRY")
    assert not hasattr(module, "register")
    assert not hasattr(module, "registered_function")


def test_load_module_from_path_caching(temp_module_dir):
    """Test that module caching prevents re-execution."""
    module_path = temp_module_dir / "decorator_module.py"

    module1 = load_module_from_path("decorator_module", module_path, cache=True)
    registry1 = module1.get_registry()

    module2 = load_module_from_path("decorator_module", module_path, cache=True)
    registry2 = module2.get_registry()

    assert module1 is module2
    assert len(registry1) == len(registry2)


def test_load_module_from_path_no_cache(temp_module_dir):
    """Test that cache=False reloads the module."""
    module_path = temp_module_dir / "sample_module.py"

    module1 = load_module_from_path("sample_module_no_cache", module_path, cache=False)
    module2 = load_module_from_path("sample_module_no_cache", module_path, cache=False)

    assert module1 is not module2
    assert module1.TEST_VALUE == module2.TEST_VALUE


def test_load_module_from_path_missing_file(temp_module_dir):
    """Test that missing file returns None."""
    missing_path = temp_module_dir / "does_not_exist.py"
    module = load_module_from_path("missing", missing_path)

    assert module is None


def test_load_module_from_path_directory(temp_module_dir):
    """Test loading from directory finds __init__.py."""
    subdir = temp_module_dir / "subpackage"
    module = load_module_from_path("subpackage", subdir)
    assert module is not None


def test_discover_and_load_udfs_basic(temp_module_dir):
    """Test basic UDF discovery (non-recursive)."""
    registry = discover_and_load_udfs(temp_module_dir)

    assert "sample_module" in registry
    assert "decorator_module" in registry
    assert "nested_module" not in registry
    assert "module" in registry["sample_module"]
    assert "path" in registry["sample_module"]
    assert registry["sample_module"]["module"].TEST_VALUE == 42


def test_discover_and_load_udfs_skip_private(temp_module_dir):
    """Test that private modules are skipped."""
    registry = discover_and_load_udfs(temp_module_dir, skip_private=True)
    assert "_private" not in registry


def test_discover_and_load_udfs_skip_test(temp_module_dir):
    """Test that test modules are skipped."""
    registry = discover_and_load_udfs(temp_module_dir, skip_test=True)
    assert "test_skip_me" not in registry


def test_discover_and_load_udfs_recursive_basic(temp_module_dir):
    """Test recursive UDF discovery."""
    registry = discover_and_load_udfs_recursive(temp_module_dir)

    assert "sample_module" in registry
    assert "decorator_module" in registry
    assert "subpackage.nested_module" in registry
    assert registry["subpackage.nested_module"]["module"].NESTED_VALUE == 100


def test_discover_and_load_udfs_recursive_skip_private(temp_module_dir):
    """Test that private modules and dirs are skipped recursively."""
    private_dir = temp_module_dir / "_private_dir"
    private_dir.mkdir()
    (private_dir / "secret.py").write_text("SECRET = 123")

    registry = discover_and_load_udfs_recursive(temp_module_dir, skip_private=True)

    assert "_private" not in registry
    assert "secret" not in registry
    assert "_private_dir.secret" not in registry


def test_discover_and_load_udfs_missing_path():
    """Test that missing path returns empty dict."""
    registry = discover_and_load_udfs("/nonexistent/path")
    assert registry == {}


def test_discover_and_load_udfs_with_import_error(temp_module_dir):
    """Test that modules with import errors are skipped gracefully."""
    bad_module = temp_module_dir / "bad_module.py"
    bad_module.write_text("""
import nonexistent_module

def foo():
    return "bar"
""")

    registry = discover_and_load_udfs(temp_module_dir)

    assert "bad_module" not in registry
    assert "sample_module" in registry


def test_load_module_from_directory_thread_safety(tmp_path):
    """Concurrent load_module_from_directory calls return the same cached module."""
    import threading

    (tmp_path / "concurrent_test.py").write_text("VALUE = 'thread_safe'")
    results: list[object] = [None] * 8
    barrier = threading.Barrier(8)

    def load(idx):
        barrier.wait()
        results[idx] = load_module_from_directory("concurrent_test", tmp_path, cache=True)

    threads = [threading.Thread(target=load, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r is not None for r in results)
    assert all(r is results[0] for r in results), "All threads should get the same cached module"


def test_broken_module_blocks_fallback(tmp_path):
    """exec_module failure blocks fallback — broken code must not be masked."""
    broken = tmp_path / "broken_exec.py"
    broken.write_text("raise RuntimeError('deliberate failure')")

    module = load_module_from_path("broken_exec", broken, fallback_import=True, cache=False)
    assert module is None
    assert "broken_exec" not in sys.modules


def test_missing_path_allows_fallback(tmp_path):
    """Allow fallback_import when path resolution fails."""
    real_module = tmp_path / "fallback_ok.py"
    real_module.write_text("VALUE = 'from_fallback'")

    sys.path.insert(0, str(tmp_path))
    try:
        module = load_module_from_path(
            "fallback_ok",
            tmp_path / "wrong_dir" / "fallback_ok.py",
            fallback_import=True,
            cache=False,
        )
        assert module is not None
        assert module.VALUE == "from_fallback"
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("fallback_ok", None)
