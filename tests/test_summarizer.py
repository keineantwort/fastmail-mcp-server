import pytest

from fastmail_mcp.utils.summarizer import summarize_text


class TestSummarizeTextFallback:
    """Tests for the truncation fallback (no API key configured)."""

    async def test_short_text_returned_as_is(self, monkeypatch):
        monkeypatch.setattr("fastmail_mcp.utils.summarizer.settings.llm_api_key", "")
        result = await summarize_text("Short email body.")
        assert result == "Short email body."

    async def test_long_text_truncated(self, monkeypatch):
        monkeypatch.setattr("fastmail_mcp.utils.summarizer.settings.llm_api_key", "")
        long_text = "A" * 300
        result = await summarize_text(long_text)
        assert result == "A" * 200 + "..."
        assert len(result) == 203


class TestSummarizeTextApi:
    """Tests for the API path using pytest-httpx."""

    async def test_successful_api_call(self, monkeypatch, httpx_mock):
        monkeypatch.setattr(
            "fastmail_mcp.utils.summarizer.settings.llm_api_key", "test-key"
        )
        httpx_mock.add_response(
            json={
                "choices": [{"message": {"content": "  A concise summary.  "}}]
            }
        )
        result = await summarize_text("Some long email content here.")
        assert result == "A concise summary."

    async def test_api_error_falls_back_to_truncation(self, monkeypatch, httpx_mock):
        monkeypatch.setattr(
            "fastmail_mcp.utils.summarizer.settings.llm_api_key", "test-key"
        )
        httpx_mock.add_response(status_code=500)
        result = await summarize_text("Short body.")
        assert result == "Short body."

    async def test_api_error_falls_back_to_truncation_long(self, monkeypatch, httpx_mock):
        monkeypatch.setattr(
            "fastmail_mcp.utils.summarizer.settings.llm_api_key", "test-key"
        )
        httpx_mock.add_response(status_code=500)
        long_text = "B" * 300
        result = await summarize_text(long_text)
        assert result == "B" * 200 + "..."
