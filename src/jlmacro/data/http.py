"""Shared HTTP client construction for outbound provider calls.

Centralised so every real adapter (FredProvider, RBAProvider, ABSProvider, ...) gets
the same timeout/retry/user-agent behaviour, and so tests can inject an
httpx.MockTransport instead of hitting the network - see tests/unit/test_*_provider.py.
"""

from __future__ import annotations

import httpx

from jlmacro.config import get_settings

_USER_AGENT = "jlmacro-platform/0.1 (+research; not for redistribution)"


def build_http_client(*, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """Build an httpx.Client with the platform's default timeout/headers.

    Pass `transport` (e.g. httpx.MockTransport) in tests to avoid real network calls.
    """
    settings = get_settings()
    return httpx.Client(
        timeout=settings.jlmacro_http_timeout_seconds,
        headers={"User-Agent": _USER_AGENT},
        transport=transport,
        follow_redirects=True,
    )
