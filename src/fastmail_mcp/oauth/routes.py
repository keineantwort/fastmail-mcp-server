"""OAuth2 Proxy endpoints implementing RFC 8414 & RFC 9728 pattern with Authentik."""

import secrets
import time
from urllib.parse import urlencode

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

from fastmail_mcp.config import settings

# In-memory stores (use Redis in production)
_registered_clients: dict[str, dict] = {}
_auth_codes: dict[str, dict] = {}


async def well_known_oauth(request: Request) -> JSONResponse:
    """RFC 8414: OAuth Authorization Server Metadata.

    /.well-known/oauth-authorization-server
    """
    base = settings.mcp_public_url.rstrip("/")
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "scopes_supported": ["mail:read", "mail:write", "offline_access"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
    })


async def register_client(request: Request) -> JSONResponse:
    """Dynamic Client Registration (RFC 7591 subset).

    POST /oauth/register
    """
    body = await request.json()
    client_id = f"mcp-{secrets.token_hex(8)}"
    client_secret = secrets.token_hex(32)

    _registered_clients[client_id] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_name": body.get("client_name", "MCP Client"),
        "redirect_uris": body.get("redirect_uris", []),
        "created_at": time.time(),
    }

    return JSONResponse(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "client_name": _registered_clients[client_id]["client_name"],
            "redirect_uris": _registered_clients[client_id]["redirect_uris"],
        },
        status_code=201,
    )


async def authorize(request: Request) -> RedirectResponse:
    """Authorization endpoint — proxies to Authentik.

    GET /oauth/authorize
    Forwards the auth request to Authentik, enforcing offline_access scope.
    """
    params = dict(request.query_params)

    # Enforce offline_access for refresh tokens
    scopes = params.get("scope", "")
    if "offline_access" not in scopes:
        scopes = f"{scopes} offline_access".strip()
        params["scope"] = scopes

    # Proxy to Authentik's authorize endpoint
    authentik_authorize = f"{settings.authentik_url}/application/o/authorize/"
    params["client_id"] = settings.authentik_client_id

    redirect_url = f"{authentik_authorize}?{urlencode(params)}"
    return RedirectResponse(url=redirect_url, status_code=302)


async def token_exchange(request: Request) -> JSONResponse:
    """Token endpoint — proxies token exchange to Authentik.

    POST /oauth/token
    """
    form = await request.form()
    grant_type = form.get("grant_type")

    authentik_token_url = f"{settings.authentik_url}/application/o/token/"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            authentik_token_url,
            data={
                "grant_type": grant_type,
                "code": form.get("code", ""),
                "redirect_uri": form.get("redirect_uri", ""),
                "client_id": settings.authentik_client_id,
                "client_secret": settings.authentik_client_secret,
                "refresh_token": form.get("refresh_token", ""),
                "code_verifier": form.get("code_verifier", ""),
            },
        )

    if resp.status_code != 200:
        return JSONResponse(resp.json(), status_code=resp.status_code)

    return JSONResponse(resp.json())


# Route table for mounting in the main app
oauth_routes = [
    Route("/.well-known/oauth-authorization-server", well_known_oauth, methods=["GET"]),
    Route("/oauth/register", register_client, methods=["POST"]),
    Route("/oauth/authorize", authorize, methods=["GET"]),
    Route("/oauth/token", token_exchange, methods=["POST"]),
]
