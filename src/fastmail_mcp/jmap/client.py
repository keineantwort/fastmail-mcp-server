"""JMAP client for Fastmail.

Handles session discovery and method calls per RFC 8620.
"""

import httpx

from fastmail_mcp.config import settings


class JMAPClient:
    """Async JMAP client for Fastmail."""

    def __init__(self) -> None:
        self._session: dict | None = None
        self._api_url: str | None = None
        self._account_id: str | None = None
        self._client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {settings.fastmail_api_token}",
                "Content-Type": "application/json",
            },
        )

    @property
    def account_id(self) -> str:
        if self._account_id is None:
            raise RuntimeError("JMAP session not initialized. Call connect() first.")
        return self._account_id

    @property
    def api_url(self) -> str:
        if self._api_url is None:
            raise RuntimeError("JMAP session not initialized. Call connect() first.")
        return self._api_url

    async def connect(self) -> None:
        """Fetch the JMAP session resource and extract API URL + account ID."""
        resp = await self._client.get(settings.fastmail_jmap_url)
        resp.raise_for_status()

        self._session = resp.json()
        self._api_url = self._session["apiUrl"]
        self._account_id = self._session["primaryAccounts"]["urn:ietf:params:jmap:mail"]

    async def method_call(self, method: str, args: dict) -> dict:
        """Execute a single JMAP method call.

        Args:
            method: JMAP method name (e.g., "Email/query").
            args: Method arguments dict.

        Returns:
            The methodResponse data for the call.
        """
        args.setdefault("accountId", self.account_id)

        request_body = {
            "using": [
                "urn:ietf:params:jmap:core",
                "urn:ietf:params:jmap:mail",
            ],
            "methodCalls": [[method, args, "call0"]],
        }

        resp = await self._client.post(self.api_url, json=request_body)
        resp.raise_for_status()

        data = resp.json()
        # methodResponses is [[methodName, responseData, callId], ...]
        method_responses = data.get("methodResponses", [])

        if not method_responses:
            raise RuntimeError(f"Empty response for {method}")

        response_name, response_data, _ = method_responses[0]

        if response_name == "error":
            raise RuntimeError(f"JMAP error: {response_data}")

        return response_data

    async def batch_call(self, calls: list[tuple[str, dict, str]]) -> list[dict]:
        """Execute multiple JMAP method calls in a single request.

        Args:
            calls: List of (method, args, call_id) tuples.

        Returns:
            List of response data dicts in order.
        """
        method_calls = []
        for method, args, call_id in calls:
            args.setdefault("accountId", self.account_id)
            method_calls.append([method, args, call_id])

        request_body = {
            "using": [
                "urn:ietf:params:jmap:core",
                "urn:ietf:params:jmap:mail",
            ],
            "methodCalls": method_calls,
        }

        resp = await self._client.post(self.api_url, json=request_body)
        resp.raise_for_status()

        data = resp.json()
        results = []
        for response_name, response_data, _ in data.get("methodResponses", []):
            if response_name == "error":
                raise RuntimeError(f"JMAP error: {response_data}")
            results.append(response_data)

        return results

    async def close(self) -> None:
        await self._client.aclose()


# Singleton
jmap_client = JMAPClient()
