"""Allow running as `python -m fastmail_mcp`."""

from fastmail_mcp.server import app, settings

import uvicorn

uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)
