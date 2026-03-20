import pytest
from pydantic import ValidationError

from fastmail_mcp.config import Settings


class TestSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.setenv("FASTMAIL_API_TOKEN", "tok_test")
        monkeypatch.setenv("AUTHENTIK_URL", "https://auth.example.com")
        s = Settings(_env_file=None)

        assert s.fastmail_api_token == "tok_test"
        assert s.fastmail_jmap_url == "https://api.fastmail.com/jmap/session"
        assert s.authentik_client_id == "fastmail-mcp"
        assert s.authentik_client_secret == ""
        assert s.mcp_public_url == "http://localhost:8000"
        assert s.mcp_host == "0.0.0.0"
        assert s.mcp_port == 8000
        assert s.llm_api_url == "https://api.deepinfra.com/v1/openai/chat/completions"
        assert s.llm_api_key == ""
        assert s.llm_model == "meta-llama/Meta-Llama-3-8B-Instruct"
        assert s.token_cache_ttl == 300

    def test_overrides(self, monkeypatch):
        monkeypatch.setenv("FASTMAIL_API_TOKEN", "tok_prod")
        monkeypatch.setenv("AUTHENTIK_URL", "https://auth.prod.com")
        monkeypatch.setenv("MCP_PORT", "9000")
        monkeypatch.setenv("TOKEN_CACHE_TTL", "60")
        s = Settings(_env_file=None)

        assert s.mcp_port == 9000
        assert s.token_cache_ttl == 60

    def test_custom_llm_settings(self, monkeypatch):
        monkeypatch.setenv("FASTMAIL_API_TOKEN", "tok_test")
        monkeypatch.setenv("AUTHENTIK_URL", "https://auth.example.com")
        monkeypatch.setenv("LLM_API_URL", "https://api.openai.com/v1/chat/completions")
        monkeypatch.setenv("LLM_API_KEY", "sk-test")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
        s = Settings(_env_file=None)

        assert s.llm_api_url == "https://api.openai.com/v1/chat/completions"
        assert s.llm_api_key == "sk-test"
        assert s.llm_model == "gpt-4o-mini"

    def test_missing_required_raises(self, monkeypatch):
        monkeypatch.delenv("FASTMAIL_API_TOKEN", raising=False)
        monkeypatch.delenv("AUTHENTIK_URL", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)
