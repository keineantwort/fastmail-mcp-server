# Fastmail MCP Server

An [MCP](https://modelcontextprotocol.io/) server that gives AI assistants secure, read-only access to your Fastmail account via [JMAP](https://jmap.io/). Designed for self-hosted environments.

## Features

- **Email search** — query emails within specific labels/mailboxes
- **Email details** — fetch full message bodies with automatic quote stripping
- **Thread summaries** — AI-powered one-sentence summaries via any OpenAI-compatible API
- **Denylist** — emails labeled "Denylist" are hard-blocked from AI access
- **OAuth2 proxy** — RFC 8414 / RFC 9728 authorization flow, proxied through an OAuth2 provider (e.g. Authentik, Keycloak, Authelia)
- **Token introspection** — Bearer tokens validated and cached against your OAuth2 provider
- **Scope enforcement** — `mail:read` / `mail:write` scopes checked per tool call

## Architecture

```
MCP Client (Claude, etc.)
    │
    ▼
┌───────────────────────┐
│  Fastmail MCP Server  │
│  ┌─────────────────┐  │
│  │ OAuth2 Proxy    │──┼──▶ OAuth2 Provider (Authentik, Keycloak, …)
│  │ Auth Middleware │  │
│  ├─────────────────┤  │
│  │ MCP Tools       │──┼──▶ Fastmail JMAP API
│  ├─────────────────┤  │
│  │ LLM Summarizer  │──┼──▶ OpenAI-compatible API (optional)
│  └─────────────────┘  │
└───────────────────────┘
```

## Prerequisites

- Python 3.11+
- A [Fastmail API token](https://www.fastmail.com/help/technical/api-keys.html)
- An OAuth2 provider with introspection support (Authentik, Keycloak, Authelia, etc.)
- *(Optional)* An OpenAI-compatible API for email summaries (DeepInfra, OpenAI, Ollama, etc.)

## Quick Start

### 1. Clone and configure

```bash
git clone https://github.com/keineantwort/fastmail-mcp-server.git
cd fastmail-mcp-server
cp .env.example .env
# Edit .env with your credentials
```

### 2. Run with Docker Compose (recommended)

```bash
docker compose up -d
```

The server starts on port `8000` by default.

### 3. Run without Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install .
python -m fastmail_mcp
```

## Configuration

All settings are configured via environment variables (or a `.env` file).

| Variable | Required | Default | Description |
|---|---|---|---|
| `FASTMAIL_API_TOKEN` | yes | — | Fastmail API token |
| `FASTMAIL_JMAP_URL` | no | `https://api.fastmail.com/jmap/session` | JMAP session URL |
| `AUTHENTIK_URL` | yes | — | Base URL of your OAuth2 provider |
| `AUTHENTIK_CLIENT_ID` | no | `fastmail-mcp` | OAuth2 client ID |
| `AUTHENTIK_CLIENT_SECRET` | no | `""` | OAuth2 client secret |
| `MCP_PUBLIC_URL` | no | `http://localhost:8000` | Public URL of this server |
| `MCP_HOST` | no | `0.0.0.0` | Bind address |
| `MCP_PORT` | no | `8000` | Bind port |
| `LLM_API_URL` | no | `https://api.deepinfra.com/v1/openai/chat/completions` | OpenAI-compatible chat completions endpoint |
| `LLM_API_KEY` | no | `""` | API key for the LLM provider (empty = summaries disabled) |
| `LLM_MODEL` | no | `meta-llama/Meta-Llama-3-8B-Instruct` | Model identifier |
| `TOKEN_CACHE_TTL` | no | `300` | Token introspection cache TTL in seconds |

## MCP Tools

| Tool | Scope | Description |
|---|---|---|
| `search_emails_tool` | `mail:read` | Search emails by query within a label/mailbox |
| `get_email_details_tool` | `mail:read` | Fetch a full email with cleaned body text |
| `summarize_thread_tool` | `mail:read` | Summarize all emails in a thread |
| `sync_fastmail_tool` | — | Refresh the JMAP session |

## OAuth2 Endpoints

The server exposes an OAuth2 proxy that delegates authentication to your identity provider:

| Endpoint | Method | Description |
|---|---|---|
| `/.well-known/oauth-authorization-server` | GET | RFC 8414 metadata |
| `/.well-known/oauth-protected-resource` | GET | RFC 9728 resource metadata |
| `/oauth/register` | POST | Dynamic client registration |
| `/oauth/authorize` | GET | Authorization (proxied to your IdP) |
| `/oauth/token` | POST | Token exchange (proxied to your IdP) |
| `/mcp` | POST/GET/DELETE | MCP Streamable HTTP transport (Bearer token required) |
| `/health` | GET | Health check |

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
FASTMAIL_API_TOKEN=test AUTHENTIK_URL=https://auth.test pytest tests/ -v

# Lint
ruff check src/ tests/
```

## License

[MIT](LICENSE)
