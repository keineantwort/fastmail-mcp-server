from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Fastmail
    fastmail_api_token: str
    fastmail_jmap_url: str = "https://api.fastmail.com/jmap/session"

    # Authentik OAuth2
    authentik_url: str
    authentik_client_id: str = "fastmail-mcp"
    authentik_client_secret: str = ""

    # MCP Server
    mcp_public_url: str = "http://localhost:8000"
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000

    # LLM Summarization (OpenAI-compatible API)
    llm_api_url: str = "https://api.deepinfra.com/v1/openai/chat/completions"
    llm_api_key: str = ""
    llm_model: str = "meta-llama/Meta-Llama-3-8B-Instruct"

    # Token cache TTL (seconds)
    token_cache_ttl: int = 300  # 5 minutes

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
