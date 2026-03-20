"""Auth middleware: validates Bearer tokens via Authentik introspection."""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from fastmail_mcp.oauth.scopes import set_scopes
from fastmail_mcp.oauth.token_cache import token_introspector

logger = logging.getLogger(__name__)

# Prefixes that don't require auth
_PUBLIC_PREFIXES = (
    "/.well-known/",
    "/oauth/",
    "/health",
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates access tokens and sets scope context for each request."""

    async def dispatch(self, request: Request, call_next):
        # Skip auth for public endpoints
        if request.url.path.startswith(_PUBLIC_PREFIXES):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                {"error": "Missing or invalid Authorization header"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header.removeprefix("Bearer ")
        introspection = await token_introspector.introspect(token)

        if introspection is None:
            return JSONResponse(
                {"error": "Invalid or expired token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Set scopes in context for downstream scope checks
        scope_str = introspection.get("scope", "")
        scopes = set(scope_str.split()) if scope_str else set()
        set_scopes(scopes)
        logger.info("Authenticated request to %s, scopes: %s", request.url.path, scopes)

        return await call_next(request)
