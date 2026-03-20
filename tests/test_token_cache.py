import pytest

from fastmail_mcp.oauth.token_cache import TokenIntrospector


@pytest.fixture
def introspector(monkeypatch):
    monkeypatch.setattr("fastmail_mcp.oauth.token_cache.settings.token_cache_ttl", 300)
    monkeypatch.setattr("fastmail_mcp.oauth.token_cache.settings.authentik_url", "https://auth.test")
    monkeypatch.setattr("fastmail_mcp.oauth.token_cache.settings.authentik_client_id", "test-id")
    monkeypatch.setattr("fastmail_mcp.oauth.token_cache.settings.authentik_client_secret", "test-secret")
    return TokenIntrospector()


class TestTokenIntrospector:
    async def test_active_token(self, introspector, httpx_mock):
        httpx_mock.add_response(
            url="https://auth.test/application/o/introspect/",
            json={"active": True, "sub": "user123"},
        )
        result = await introspector.introspect("valid-token")
        assert result == {"active": True, "sub": "user123"}

    async def test_inactive_token(self, introspector, httpx_mock):
        httpx_mock.add_response(
            url="https://auth.test/application/o/introspect/",
            json={"active": False},
        )
        result = await introspector.introspect("expired-token")
        assert result is None

    async def test_api_error_returns_none(self, introspector, httpx_mock):
        httpx_mock.add_response(
            url="https://auth.test/application/o/introspect/",
            status_code=500,
        )
        result = await introspector.introspect("some-token")
        assert result is None

    async def test_cache_hit(self, introspector, httpx_mock):
        httpx_mock.add_response(
            url="https://auth.test/application/o/introspect/",
            json={"active": True, "sub": "user123"},
        )
        # First call hits the API
        result1 = await introspector.introspect("cached-token")
        assert result1 is not None

        # Second call should use cache (no additional HTTP call expected)
        result2 = await introspector.introspect("cached-token")
        assert result2 == result1

        # Only one HTTP request should have been made
        assert len(httpx_mock.get_requests()) == 1

    async def test_inactive_token_cached(self, introspector, httpx_mock):
        httpx_mock.add_response(
            url="https://auth.test/application/o/introspect/",
            json={"active": False},
        )
        result1 = await introspector.introspect("bad-token")
        assert result1 is None

        result2 = await introspector.introspect("bad-token")
        assert result2 is None

        assert len(httpx_mock.get_requests()) == 1
