"""Allow running as `python -m fastmail_mcp`."""

import anyio

from fastmail_mcp.server import run

anyio.run(run)
