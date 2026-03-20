"""Main entry point: FastMCP server with OAuth proxy and JMAP integration."""

import contextlib

import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from fastmail_mcp.config import settings
from fastmail_mcp.jmap.client import jmap_client
from fastmail_mcp.middleware import AuthMiddleware
from fastmail_mcp.oauth.routes import oauth_routes
from fastmail_mcp.oauth.token_cache import token_introspector
from fastmail_mcp.tools.email_tools import (
    get_email_details,
    search_emails,
    summarize_thread,
    sync_fastmail,
)

# --- FastMCP Setup ---

mcp = FastMCP(
    "Fastmail MCP Server",
    description="Access Fastmail emails via JMAP with label filtering and AI summaries.",
)


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

    Consolidates all emails in a thread into a summary before sending to Claude.

    Args:
        thread_id: The JMAP thread ID.
    """
    return await summarize_thread(thread_id)


@mcp.tool()
async def sync_fastmail_tool() -> dict:
    """Trigger a JMAP session sync/refresh with Fastmail."""
    return await sync_fastmail()


# --- Starlette App with OAuth + MCP ---


async def health(request):
    return JSONResponse({"status": "ok"})


@contextlib.asynccontextmanager
async def lifespan(app):
    # Startup: connect to Fastmail JMAP
    await jmap_client.connect()
    yield
    # Shutdown: cleanup
    await jmap_client.close()
    await token_introspector.close()


# Build the Starlette app
app = Starlette(
    routes=[
        *oauth_routes,
        Route("/health", health, methods=["GET"]),
    ],
    lifespan=lifespan,
)

# Add auth middleware
app.add_middleware(AuthMiddleware)

# Mount the MCP SSE transport under /mcp
mcp_app = mcp.sse_app()
app.mount("/mcp", mcp_app)


if __name__ == "__main__":
    uvicorn.run(
        "fastmail_mcp.server:app",
        host=settings.mcp_host,
        port=settings.mcp_port,
        reload=False,
    )
