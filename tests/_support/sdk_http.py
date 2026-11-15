"""The HTTP library a vendor SDK runs on, for tests that hand the SDK its own transport.

anthropic 1.x and openai 3.x run on httpx2 and refuse httpx's clients, requests and
responses; the locked versions run on httpx.
"""

from __future__ import annotations

import importlib
from types import ModuleType

import httpx


def http_library(sdk: ModuleType) -> ModuleType:
    """httpx, or httpx2 for an SDK that runs on it.

    Told by the SDK's ``Timeout`` class: the SDKs overwrite ``__module__`` on the classes
    they re-export, so the name says nothing.
    """
    if sdk.Timeout is httpx.Timeout:
        return httpx
    return importlib.import_module("httpx2")
