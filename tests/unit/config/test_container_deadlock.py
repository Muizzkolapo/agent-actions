"""Tests for DI container recursive singleton resolution (deadlock prevention)."""

import threading

from agent_actions.config.di.container import DependencyContainer


class ServiceB:
    """Leaf service with no dependencies."""

    def __init__(self):
        self.value = "B"


class ServiceA:
    """Service that depends on ServiceB — triggers recursive container.get()."""

    def __init__(self, dep: ServiceB):
        self.dep = dep


def test_recursive_singleton_resolution_does_not_deadlock():
    """RLock allows same-thread reentry: resolving A (singleton) that
    depends on B (singleton) must succeed without hanging."""
    container = DependencyContainer()
    container.register_singleton(ServiceB, ServiceB)
    container.register_singleton(ServiceA, ServiceA)

    result = [None]
    error = [None]

    def resolve():
        try:
            result[0] = container.get(ServiceA)
        except Exception as exc:
            error[0] = exc

    t = threading.Thread(target=resolve)
    t.start()
    t.join(timeout=5)

    assert not t.is_alive(), "Deadlock detected: resolution hung for >5 seconds"
    assert error[0] is None, f"Resolution raised: {error[0]}"
    assert isinstance(result[0], ServiceA)
    assert isinstance(result[0].dep, ServiceB)


def test_singleton_identity_preserved():
    """Singleton resolved through dependency chain returns the same instance."""
    container = DependencyContainer()
    container.register_singleton(ServiceB, ServiceB)
    container.register_singleton(ServiceA, ServiceA)

    a = container.get(ServiceA)
    b_direct = container.get(ServiceB)
    assert a.dep is b_direct, "Singleton identity not preserved across resolution paths"
