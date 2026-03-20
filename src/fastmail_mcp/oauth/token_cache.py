"""Token introspection cache (5 min TTL) against Authentik."""

import time

import httpx
from cachetools import TTLCache

from fastmail_mcp.config import settings


class TokenIntrospector:
    """Validates access tokens via Authentik's introspection endpoint with caching."""

    def __init__(self) -> None:
        self._cache: TTLCache[str, dict] = TTLCache(maxsize=1024, ttl=settings.token_cache_ttl)
        self._client = httpx.AsyncClient(timeout=10.0)

    async def introspect(self, token: str) -> dict | None:
        """Introspect a token. Returns the introspection response or None if inactive."""
        if token in self._cache:
            cached = self._cache[token]
            if cached.get("active"):
                return cached
            return None

        introspection_url = f"{settings.authentik_url}/application/o/introspect/"
        resp = await self._client.post(
            introspection_url,
            data={
                "token": token,
                "client_id": settings.authentik_client_id,
                "client_secret": settings.authentik_client_secret,
            },
        )

        if resp.status_code != 200:
            return None

        result = resp.json()
        self._cache[token] = result

        if not result.get("active"):
            return None

        return result

    async def close(self) -> None:
        await self._client.aclose()


# Singleton
token_introspector = TokenIntrospector()
