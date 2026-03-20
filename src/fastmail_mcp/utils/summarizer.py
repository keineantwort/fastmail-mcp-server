"""LLM summarization for email list views (OpenAI-compatible API)."""

import httpx

from fastmail_mcp.config import settings


async def summarize_text(text: str, max_tokens: int = 60) -> str:
    """Generate a 1-sentence summary via an OpenAI-compatible API.

    Falls back to truncation if no API key is configured or the API is unavailable.
    """
    if not settings.llm_api_key:
        return text[:200] + "..." if len(text) > 200 else text

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            settings.llm_api_url,
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Summarize the following email in exactly one sentence. Be concise.",
                    },
                    {"role": "user", "content": text[:2000]},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
        )

        if resp.status_code != 200:
            return text[:200] + "..." if len(text) > 200 else text

        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
