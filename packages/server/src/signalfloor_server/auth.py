"""API keys.

When SIGNALFLOOR_API_KEYS is set, every endpoint except the health checks needs
`Authorization: Bearer <key>`. Agents sending traces set it with OpenTelemetry's standard
OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer <key>".

This is one shared set of keys for one team. There are no users or projects, and any key can
read, write and delete everything. See the deployment notes in the README.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request


async def require_api_key(request: Request) -> None:
    keys: tuple[str, ...] = request.app.state.api_keys
    if not keys:
        return
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    # Compare against every key in constant time, so timing reveals neither the key nor which
    # one matched.
    matches = [hmac.compare_digest(token.strip().encode(), key.encode()) for key in keys]
    if scheme.lower() != "bearer" or not any(matches):
        raise HTTPException(401, "missing or wrong API key", headers={"WWW-Authenticate": "Bearer"})
