"""Integration tests for the Fastmail JMAP connection.

These tests hit the real Fastmail API and require a valid FASTMAIL_API_TOKEN.
Run with:
    pytest tests/test_integration.py -v -s

Requires .env file or environment variables set.
"""

import json
import os
import re

import httpx
import pytest
from dotenv import load_dotenv

load_dotenv()

FASTMAIL_JMAP_URL = os.environ.get(
    "FASTMAIL_JMAP_URL", "https://api.fastmail.com/jmap/session"
)
FASTMAIL_API_TOKEN = os.environ.get("FASTMAIL_API_TOKEN", "")

pytestmark = pytest.mark.skipif(
    not FASTMAIL_API_TOKEN or FASTMAIL_API_TOKEN == "test"
    or FASTMAIL_API_TOKEN == "your_fastmail_api_token",
    reason="FASTMAIL_API_TOKEN not set or is placeholder",
)


def _parse_allowlist_labels() -> list[str]:
    """Parse ALLOWLIST_LABELS from env, handling both JSON and bare formats.

    .env may contain ["AI-Allowed"] but shell sourcing can strip quotes,
    resulting in [AI-Allowed]. Handle both.
    """
    raw = os.environ.get("ALLOWLIST_LABELS", "[]")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Handle bare format like [AI-Allowed] or [Foo,Bar]
        inner = raw.strip("[] ")
        if not inner:
            return []
        return [s.strip() for s in inner.split(",")]


@pytest.fixture()
async def jmap_session():
    """Connect to JMAP and return (api_url, account_id, client)."""
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={
            "Authorization": f"Bearer {FASTMAIL_API_TOKEN}",
            "Content-Type": "application/json",
        },
    ) as client:
        resp = await client.get(FASTMAIL_JMAP_URL)
        resp.raise_for_status()
        session = resp.json()

        api_url = session["apiUrl"]
        account_id = session["primaryAccounts"]["urn:ietf:params:jmap:mail"]

        yield api_url, account_id, client


async def jmap_call(session, method: str, args: dict) -> dict:
    """Helper: single JMAP method call."""
    api_url, account_id, client = session
    args.setdefault("accountId", account_id)
    body = {
        "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        "methodCalls": [[method, args, "c0"]],
    }
    resp = await client.post(api_url, json=body)
    resp.raise_for_status()
    data = resp.json()
    responses = data.get("methodResponses", [])
    assert responses, f"Empty response for {method}"
    name, result, _ = responses[0]
    assert name != "error", f"JMAP error: {result}"
    return result


# ─── Session / Connection ─────────────────────────────────────────────


class TestJMAPSession:
    async def test_session_discovery(self, jmap_session):
        """Verify we can connect and get a valid JMAP session."""
        api_url, account_id, _ = jmap_session
        assert api_url, "apiUrl must not be empty"
        assert account_id, "account_id must not be empty"
        assert api_url.startswith("https://"), f"Unexpected apiUrl: {api_url}"

    async def test_session_capabilities(self):
        """Verify the session response contains expected capabilities."""
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {FASTMAIL_API_TOKEN}",
                "Content-Type": "application/json",
            },
        ) as client:
            resp = await client.get(FASTMAIL_JMAP_URL)
            resp.raise_for_status()
            session = resp.json()

        assert "urn:ietf:params:jmap:core" in session.get("capabilities", {}), (
            "Missing core capability"
        )
        assert "urn:ietf:params:jmap:mail" in session.get("capabilities", {}), (
            "Missing mail capability"
        )


# ─── Mailboxes ─────────────────────────────────────────────────────────


class TestMailboxes:
    async def test_list_all_mailboxes(self, jmap_session):
        """List all mailboxes and verify standard ones exist."""
        result = await jmap_call(jmap_session, "Mailbox/get", {"properties": ["id", "name"]})
        mailboxes = result.get("list", [])
        assert len(mailboxes) > 0, "No mailboxes found"

        names = {mb["name"] for mb in mailboxes}
        print(f"\nFound {len(mailboxes)} mailboxes: {sorted(names)}")

        # Every Fastmail account should have Inbox
        assert "Inbox" in names, f"'Inbox' not found. Available: {sorted(names)}"

    async def test_query_inbox_by_name(self, jmap_session):
        """Verify Mailbox/query can find Inbox by name."""
        result = await jmap_call(
            jmap_session,
            "Mailbox/query",
            {"filter": {"name": "Inbox"}},
        )
        ids = result.get("ids", [])
        assert len(ids) == 1, f"Expected 1 Inbox, got {len(ids)}"

    async def test_allowlist_labels_exist(self, jmap_session):
        """Check that configured allowlist labels actually exist as mailboxes."""
        allowlist = _parse_allowlist_labels()
        if not allowlist:
            pytest.skip("No ALLOWLIST_LABELS configured")

        result = await jmap_call(jmap_session, "Mailbox/get", {"properties": ["id", "name"]})
        existing_names = {mb["name"] for mb in result.get("list", [])}

        missing = [label for label in allowlist if label not in existing_names]
        assert not missing, (
            f"Allowlist labels not found as mailboxes: {missing}. "
            f"Available: {sorted(existing_names)}"
        )


# ─── Email Search ──────────────────────────────────────────────────────


class TestEmailSearch:
    async def test_search_inbox_no_text_filter(self, jmap_session):
        """Search Inbox without text filter — verifies basic query pipeline."""
        mb_result = await jmap_call(
            jmap_session,
            "Mailbox/query",
            {"filter": {"name": "Inbox"}},
        )
        inbox_id = mb_result["ids"][0]

        # Query recent emails (no text filter = all)
        query_result = await jmap_call(
            jmap_session,
            "Email/query",
            {
                "filter": {"inMailbox": inbox_id},
                "sort": [{"property": "receivedAt", "isAscending": False}],
                "limit": 5,
            },
        )

        email_ids = query_result.get("ids", [])
        total = query_result.get("total", "?")
        print(f"\nInbox: {total} total emails, fetched {len(email_ids)} IDs")
        assert len(email_ids) > 0, "Inbox is empty — cannot verify email search"

    async def test_search_with_empty_text_filter(self, jmap_session):
        """Search with empty text filter — this is what MCP tools send.

        IMPORTANT: Fastmail JMAP may return 0 results for empty text query!
        This test documents whether the behavior differs from no filter.
        """
        mb_result = await jmap_call(
            jmap_session,
            "Mailbox/query",
            {"filter": {"name": "Inbox"}},
        )
        inbox_id = mb_result["ids"][0]

        # With empty text (what MCP tools do)
        with_text = await jmap_call(
            jmap_session,
            "Email/query",
            {
                "filter": {"inMailbox": inbox_id, "text": ""},
                "sort": [{"property": "receivedAt", "isAscending": False}],
                "limit": 5,
            },
        )

        # Without text filter
        without_text = await jmap_call(
            jmap_session,
            "Email/query",
            {
                "filter": {"inMailbox": inbox_id},
                "sort": [{"property": "receivedAt", "isAscending": False}],
                "limit": 5,
            },
        )

        ids_with = with_text.get("ids", [])
        ids_without = without_text.get("ids", [])

        print(f"\nWith empty text filter: {len(ids_with)} results")
        print(f"Without text filter:   {len(ids_without)} results")

        # Fastmail JMAP returns 0 results for text="" — this is expected JMAP behavior.
        # The MCP search_emails tool must omit the text filter when query is empty.
        # This test documents the behavior as a regression check.
        if len(ids_with) == 0 and len(ids_without) > 0:
            print(
                "CONFIRMED: Fastmail JMAP returns 0 results for text=''. "
                "The search_emails tool must omit 'text' when query is empty."
            )

    async def test_search_in_allowlist_label(self, jmap_session):
        """Search within an allowlist label — this is what Claude.ai does."""
        allowlist = _parse_allowlist_labels()
        if not allowlist:
            pytest.skip("No ALLOWLIST_LABELS configured")

        label = allowlist[0]

        # Find the mailbox
        mb_result = await jmap_call(
            jmap_session,
            "Mailbox/query",
            {"filter": {"name": label}},
        )
        ids = mb_result.get("ids", [])
        if not ids:
            pytest.fail(f"Allowlist label '{label}' not found as mailbox")

        mailbox_id = ids[0]

        # Search emails in this label
        query_result = await jmap_call(
            jmap_session,
            "Email/query",
            {
                "filter": {"inMailbox": mailbox_id},
                "sort": [{"property": "receivedAt", "isAscending": False}],
                "limit": 20,
            },
        )

        email_ids = query_result.get("ids", [])
        total = query_result.get("total", 0)
        print(f"\nLabel '{label}' (ID: {mailbox_id}): {total} total, {len(email_ids)} fetched")

        if not email_ids:
            pytest.fail(
                f"Label '{label}' has 0 emails! "
                f"This explains why Claude.ai finds nothing. "
                f"Make sure emails are tagged with this label in Fastmail."
            )


# ─── Email Fetch ───────────────────────────────────────────────────────


class TestEmailFetch:
    async def test_fetch_email_details(self, jmap_session):
        """Fetch full details of a real email."""
        mb_result = await jmap_call(
            jmap_session, "Mailbox/query", {"filter": {"name": "Inbox"}}
        )
        inbox_id = mb_result["ids"][0]

        query_result = await jmap_call(
            jmap_session,
            "Email/query",
            {
                "filter": {"inMailbox": inbox_id},
                "sort": [{"property": "receivedAt", "isAscending": False}],
                "limit": 1,
            },
        )
        email_ids = query_result.get("ids", [])
        if not email_ids:
            pytest.skip("No emails in Inbox")

        get_result = await jmap_call(
            jmap_session,
            "Email/get",
            {
                "ids": [email_ids[0]],
                "properties": [
                    "id", "subject", "from", "to", "cc", "receivedAt",
                    "bodyValues", "textBody", "htmlBody", "attachments",
                    "mailboxIds",
                ],
                "fetchAllBodyValues": True,
            },
        )

        emails = get_result.get("list", [])
        assert len(emails) == 1, f"Expected 1 email, got {len(emails)}"

        email = emails[0]
        print(f"\nEmail: {email.get('subject', '(no subject)')}")
        print(f"  From: {email.get('from', [])}")
        print(f"  Date: {email.get('receivedAt', '')}")
        print(f"  Mailboxes: {list(email.get('mailboxIds', {}).keys())}")

        assert "id" in email
        assert "subject" in email
        assert "mailboxIds" in email
        assert isinstance(email["mailboxIds"], dict)

    async def test_email_has_body(self, jmap_session):
        """Verify that fetched emails actually contain body text."""
        mb_result = await jmap_call(
            jmap_session, "Mailbox/query", {"filter": {"name": "Inbox"}}
        )
        query_result = await jmap_call(
            jmap_session,
            "Email/query",
            {
                "filter": {"inMailbox": mb_result["ids"][0]},
                "sort": [{"property": "receivedAt", "isAscending": False}],
                "limit": 1,
            },
        )
        email_ids = query_result.get("ids", [])
        if not email_ids:
            pytest.skip("No emails in Inbox")

        get_result = await jmap_call(
            jmap_session,
            "Email/get",
            {
                "ids": [email_ids[0]],
                "properties": ["id", "bodyValues", "textBody"],
                "fetchAllBodyValues": True,
            },
        )

        email = get_result["list"][0]
        body_values = email.get("bodyValues", {})
        text_parts = email.get("textBody", [])

        body_text = ""
        for part in text_parts:
            part_id = part.get("partId")
            if part_id and part_id in body_values:
                body_text += body_values[part_id].get("value", "")

        print(f"\nBody length: {len(body_text)} chars")
        print(f"Body preview: {body_text[:200]}...")
        assert body_values, "No bodyValues returned — fetchAllBodyValues may not work"


# ─── Label Filter Pipeline ────────────────────────────────────────────


class TestLabelFilterPipeline:
    """Test the full label filter pipeline against real data."""

    async def test_denylist_label_exists(self, jmap_session):
        """Check if the denylist label actually exists."""
        denylist_label = os.environ.get("DENYLIST_LABEL", "Denylist")
        result = await jmap_call(
            jmap_session,
            "Mailbox/query",
            {"filter": {"name": denylist_label}},
        )
        ids = result.get("ids", [])
        if not ids:
            print(f"\nNote: Denylist label '{denylist_label}' does not exist as mailbox")
        else:
            print(f"\nDenylist label '{denylist_label}' exists (ID: {ids[0]})")

    async def test_emails_pass_filter(self, jmap_session):
        """Simulate the full filter chain that the MCP tools use."""
        allowlist = _parse_allowlist_labels()
        denylist_label = os.environ.get("DENYLIST_LABEL", "Denylist")

        # Get all mailboxes
        mb_result = await jmap_call(
            jmap_session, "Mailbox/get", {"properties": ["id", "name"]}
        )
        all_mailboxes = {mb["id"]: mb["name"] for mb in mb_result.get("list", [])}

        # Resolve filter IDs
        allowlist_ids = set()
        for label in allowlist:
            for mid, name in all_mailboxes.items():
                if name == label:
                    allowlist_ids.add(mid)

        denylist_ids = {mid for mid, name in all_mailboxes.items() if name == denylist_label}

        print(f"\nAllowlist labels: {allowlist} -> IDs: {allowlist_ids}")
        print(f"Denylist label: {denylist_label} -> IDs: {denylist_ids}")

        if allowlist and not allowlist_ids:
            pytest.fail(
                f"PROBLEM: Allowlist labels {allowlist} don't match any mailbox! "
                f"Available: {sorted(all_mailboxes.values())}"
            )

        # Get some recent emails from Inbox
        mb_q = await jmap_call(
            jmap_session, "Mailbox/query", {"filter": {"name": "Inbox"}}
        )
        inbox_id = mb_q["ids"][0]

        query_result = await jmap_call(
            jmap_session,
            "Email/query",
            {
                "filter": {"inMailbox": inbox_id},
                "sort": [{"property": "receivedAt", "isAscending": False}],
                "limit": 10,
            },
        )
        email_ids = query_result.get("ids", [])
        if not email_ids:
            pytest.skip("No emails to test filter with")

        get_result = await jmap_call(
            jmap_session,
            "Email/get",
            {
                "ids": email_ids,
                "properties": ["id", "subject", "mailboxIds"],
            },
        )

        allowed = 0
        blocked = 0
        for email in get_result.get("list", []):
            email_mailbox_ids = set(email.get("mailboxIds", {}).keys())
            email_labels = [all_mailboxes.get(mid, mid) for mid in email_mailbox_ids]

            # Allowlist check
            if allowlist_ids and not (email_mailbox_ids & allowlist_ids):
                blocked += 1
                print(f"  BLOCKED (not in allowlist): {email.get('subject', '?')} — labels: {email_labels}")
                continue

            # Denylist check
            if email_mailbox_ids & denylist_ids:
                blocked += 1
                print(f"  BLOCKED (in denylist): {email.get('subject', '?')} — labels: {email_labels}")
                continue

            allowed += 1
            print(f"  ALLOWED: {email.get('subject', '?')} — labels: {email_labels}")

        print(f"\nFilter results: {allowed} allowed, {blocked} blocked out of {len(email_ids)}")

        if allowlist and allowed == 0:
            pytest.fail(
                f"ALL {len(email_ids)} emails were blocked by filter! "
                f"Inbox emails are not tagged with allowlist labels {allowlist}. "
                f"This is likely why Claude.ai finds no emails."
            )
