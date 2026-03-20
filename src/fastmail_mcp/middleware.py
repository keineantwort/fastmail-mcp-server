"""Auth middleware: validates Bearer tokens via Authentik introspection."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from fastmail_mcp.oauth.scopes import set_scopes
from fastmail_mcp.oauth.token_cache import token_introspector

# Paths that don't require auth
_PUBLIC_PATHS = {
    "/.well-known/oauth-authorization-server",
    "/oauth/register",
    "/oauth/authorize",
    "/oauth/token",
    "/health",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates access tokens and sets scope context for each request."""

    async def dispatch(self, request: Request, call_next):
        # Skip auth for public endpoints
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"error": "Missing or invalid Authorization header"}, status_code=401)

        token = auth_header.removeprefix("Bearer ")
        introspection = await token_introspector.introspect(token)

        if introspection is None:
            return JSONResponse({"error": "Invalid or expired token"}, status_code=401)

        # Set scopes in context for downstream scope checks
        scope_str = introspection.get("scope", "")
        scopes = set(scope_str.split()) if scope_str else set()
        set_scopes(scopes)

        return await call_next(request)
