"""Main entry point: MCP server with OAuth proxy and JMAP integration."""

import logging

import anyio
import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route
from urllib.parse import urlencode, parse_qs

from fastmail_mcp.config import settings
from fastmail_mcp.oauth.scopes import set_scopes
from fastmail_mcp.oauth.token_cache import token_introspector
from fastmail_mcp.tools.email_tools import (
    get_email_details,
    search_emails,
    summarize_thread,
    sync_fastmail,
)

logger = logging.getLogger(__name__)

# --- FastMCP Setup ---

mcp = FastMCP("Fastmail MCP Server")


@mcp.tool()
async def search_emails_tool(query: str, label: str) -> list[dict]:
    """Search emails within a specific label/mailbox.

    Args:
        query: Search query string.
        label: Label/mailbox name to filter by (required).
    """
    return await search_emails(query, label)


@mcp.tool()
async def get_email_details_tool(message_id: str) -> dict:
    """Fetch full email details with cleaned body text.

    Blocks access to emails with the 'Denylist' label.

    Args:
        message_id: The JMAP email ID.
    """
    return await get_email_details(message_id)


@mcp.tool()
async def summarize_thread_tool(thread_id: str) -> dict:
    """Summarize an email thread using AI.

    Args:
        thread_id: The JMAP thread ID.
    """
    return await summarize_thread(thread_id)


@mcp.tool()
async def sync_fastmail_tool() -> dict:
    """Trigger a JMAP session sync/refresh with Fastmail."""
    return await sync_fastmail()


# --- SSE Transport ---

sse = SseServerTransport("/messages/")


# --- Helper ---

def _extract_bearer(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    return auth_header[7:]


async def _validate_token(token: str) -> set[str]:
    """Validate token via introspection and return granted scopes.

    Raises PermissionError if the token is invalid.
    """
    result = await token_introspector.introspect(token)
    if result is None:
        raise PermissionError("Token invalid or expired")
    scope_str = result.get("scope", "")
    return set(scope_str.split()) if scope_str else set()


# --- OAuth Proxy Endpoints ---

async def oauth_metadata(request: Request):
    """RFC 8414 — OAuth Authorization Server Metadata."""
    base = settings.mcp_public_url.rstrip("/")
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
    })


async def oauth_protected_resource(request: Request):
    """RFC 9728 — OAuth Protected Resource Metadata."""
    base = settings.mcp_public_url.rstrip("/")
    return JSONResponse({
        "resource": base,
        "authorization_servers": [base],
        "scopes_supported": ["mail:read", "mail:write", "offline_access"],
        "bearer_methods_supported": ["header"],
    })


async def oauth_register(request: Request):
    """Dynamic Client Registration — returns Authentik credentials."""
    return JSONResponse({
        "client_id": settings.authentik_client_id,
        "client_secret": settings.authentik_client_secret,
        "client_name": "Fastmail MCP",
        "redirect_uris": [
            "https://claude.ai/api/mcp/auth_callback",
            "http://localhost:8080/callback",
        ],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    }, status_code=201)


async def oauth_authorize(request: Request):
    """Redirect to Authentik, injecting offline_access scope."""
    params = parse_qs(str(request.url.query), keep_blank_values=True)
    scope_values = params.get("scope", [""])[0].split()
    if "offline_access" not in scope_values:
        scope_values.append("offline_access")
        params["scope"] = [" ".join(scope_values)]
    flat_params = {k: v[0] for k, v in params.items()}
    authentik_authorize_url = f"{settings.authentik_url}/application/o/authorize/"
    redirect_url = f"{authentik_authorize_url}?{urlencode(flat_params)}"
    return RedirectResponse(url=redirect_url, status_code=302)


async def oauth_token(request: Request):
    """Proxy token requests to Authentik."""
    body = await request.body()
    headers = {
        "content-type": request.headers.get("content-type", "application/x-www-form-urlencoded"),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.authentik_url}/application/o/token/",
            content=body,
            headers=headers,
        )
    return JSONResponse(resp.json(), status_code=resp.status_code)


async def health(request: Request):
    return JSONResponse({"status": "ok"})


# --- MCP SSE Endpoints ---

async def handle_sse(request: Request):
    token = _extract_bearer(request)
    if not token:
        return JSONResponse(
            {"error": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        scopes = await _validate_token(token)
    except PermissionError:
        return JSONResponse(
            {"error": "Unauthorized – token invalid or expired"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    set_scopes(scopes)
    logger.info("SSE connected, granted scopes: %s", scopes)

    async with sse.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp._mcp_server.run(
            streams[0],
            streams[1],
            mcp._mcp_server.create_initialization_options(),
        )


async def handle_messages(scope, receive, send):
    request = Request(scope, receive, send)
    token = _extract_bearer(request)
    if not token:
        response = JSONResponse(
            {"error": "Unauthorized"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)
        return
    try:
        await _validate_token(token)
    except PermissionError:
        response = JSONResponse(
            {"error": "Unauthorized – token invalid or expired"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)
        return
    await sse.handle_post_message(scope, receive, send)


# --- Starlette App ---

app = Starlette(
    debug=False,
    routes=[
        Route("/.well-known/oauth-authorization-server", endpoint=oauth_metadata),
        Route("/.well-known/oauth-protected-resource", endpoint=oauth_protected_resource),
        Route("/oauth/authorize", endpoint=oauth_authorize),
        Route("/oauth/token", endpoint=oauth_token, methods=["POST"]),
        Route("/oauth/register", endpoint=oauth_register, methods=["POST"]),
        Route("/health", endpoint=health),
        Route("/sse", endpoint=handle_sse),
        Mount("/messages/", app=handle_messages),
    ],
)


async def run() -> None:
    config = uvicorn.Config(app, host=settings.mcp_host, port=settings.mcp_port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    anyio.run(run)
