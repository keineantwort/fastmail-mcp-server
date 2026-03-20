"""MCP tool definitions for Fastmail email operations."""

import logging

from fastmail_mcp.config import settings

logger = logging.getLogger(__name__)
from fastmail_mcp.jmap.client import jmap_client
from fastmail_mcp.jmap.mailbox import get_all_mailboxes, get_mailbox_id_by_name
from fastmail_mcp.oauth.scopes import require_scope
from fastmail_mcp.utils.quote_cleaner import clean_quoted_text
from fastmail_mcp.utils.summarizer import summarize_text


def _resolve_label_ids(all_mailboxes: dict[str, str]) -> tuple[set[str], set[str]]:
    """Resolve allowlist and denylist label names to mailbox IDs.

    Returns:
        (allowlist_ids, denylist_ids) — allowlist_ids is empty when no
        allowlist is configured (= allow all).
    """
    allowlist_ids = set()
    for label in settings.allowlist_labels:
        for mid, name in all_mailboxes.items():
            if name == label:
                allowlist_ids.add(mid)

    denylist_ids = {
        mid for mid, name in all_mailboxes.items()
        if name == settings.denylist_label
    }
    return allowlist_ids, denylist_ids


def _is_allowed(email_mailbox_ids: set[str], allowlist_ids: set[str], denylist_ids: set[str]) -> bool:
    """Check whether an email passes the allowlist→denylist filter chain.

    1. If an allowlist is configured, the email must be in at least one
       allowlisted mailbox.  Otherwise it is dropped.
    2. If the email is in any denylisted mailbox, it is dropped.
    """
    # Step 1: allowlist (skip if not configured)
    if allowlist_ids and not (email_mailbox_ids & allowlist_ids):
        return False
    # Step 2: denylist
    if email_mailbox_ids & denylist_ids:
        return False
    return True


async def search_emails(query: str, label: str) -> list[dict]:
    """Search emails within a specific label.

    Args:
        query: Search query string.
        label: Label/mailbox name to search within.

    Returns:
        List of email summaries with id, subject, from, date, and AI summary.
    """
    require_scope("mail:read")
    logger.info("search_emails called: query=%r, label=%r", query, label)

    mailbox_id = await get_mailbox_id_by_name(label)
    if mailbox_id is None:
        logger.warning("Label %r not found as mailbox", label)
        return []

    # Query emails in the mailbox
    # NOTE: Fastmail JMAP returns 0 results when text is empty string,
    # so we only include the text filter when a query is actually provided.
    query_filter: dict = {"inMailbox": mailbox_id}
    if query:
        query_filter["text"] = query

    logger.info("JMAP filter: %s", query_filter)

    query_result = await jmap_client.method_call(
        "Email/query",
        {
            "filter": query_filter,
            "sort": [{"property": "receivedAt", "isAscending": False}],
            "limit": 20,
        },
    )

    email_ids = query_result.get("ids", [])
    logger.info("JMAP returned %d email IDs", len(email_ids))
    if not email_ids:
        return []

    # Fetch email details
    get_result = await jmap_client.method_call(
        "Email/get",
        {
            "ids": email_ids,
            "properties": ["id", "subject", "from", "receivedAt", "preview", "mailboxIds"],
        },
    )

    all_mailboxes = await get_all_mailboxes()
    allowlist_ids, denylist_ids = _resolve_label_ids(all_mailboxes)
    logger.info("Allowlist IDs: %s, Denylist IDs: %s", allowlist_ids, denylist_ids)

    results = []
    for email in get_result.get("list", []):
        email_mailbox_ids = set(email.get("mailboxIds", {}).keys())
        if not _is_allowed(email_mailbox_ids, allowlist_ids, denylist_ids):
            email_labels = [all_mailboxes.get(m, m) for m in email_mailbox_ids]
            logger.info("FILTERED OUT: %r labels=%s", email.get("subject"), email_labels)
            continue

        summary = await summarize_text(email.get("preview", ""))
        results.append({
            "id": email["id"],
            "subject": email.get("subject", "(no subject)"),
            "from": email.get("from", [{}])[0].get("email", "unknown"),
            "date": email.get("receivedAt", ""),
            "summary": summary,
        })

    return results


async def get_email_details(message_id: str) -> dict:
    """Fetch full email details with cleaned body.

    HARD-BLOCKS any email that fails the allowlist/denylist filter.

    Args:
        message_id: JMAP email ID.

    Returns:
        Email details with cleaned body text and attachment metadata.
    """
    require_scope("mail:read")

    result = await jmap_client.method_call(
        "Email/get",
        {
            "ids": [message_id],
            "properties": [
                "id", "subject", "from", "to", "cc", "receivedAt",
                "bodyValues", "textBody", "htmlBody", "attachments",
                "mailboxIds",
            ],
            "fetchAllBodyValues": True,
        },
    )

    emails = result.get("list", [])
    if not emails:
        return {"error": "Email not found"}

    email = emails[0]

    # HARD-BLOCK: allowlist → denylist
    all_mailboxes = await get_all_mailboxes()
    allowlist_ids, denylist_ids = _resolve_label_ids(all_mailboxes)
    email_mailbox_ids = set(email.get("mailboxIds", {}).keys())

    if not _is_allowed(email_mailbox_ids, allowlist_ids, denylist_ids):
        return {"error": "Access denied: this email is not in the allowlist or is on the denylist."}

    # Extract and clean body text
    body_values = email.get("bodyValues", {})
    text_parts = email.get("textBody", [])
    body_text = ""
    for part in text_parts:
        part_id = part.get("partId")
        if part_id and part_id in body_values:
            body_text += body_values[part_id].get("value", "")

    cleaned_body = clean_quoted_text(body_text)

    # Attachment metadata
    attachments = [
        {
            "name": att.get("name", "unnamed"),
            "type": att.get("type", "unknown"),
            "size": att.get("size", 0),
        }
        for att in email.get("attachments", [])
    ]

    return {
        "id": email["id"],
        "subject": email.get("subject", "(no subject)"),
        "from": email.get("from", []),
        "to": email.get("to", []),
        "cc": email.get("cc", []),
        "date": email.get("receivedAt", ""),
        "body": cleaned_body,
        "attachments": attachments,
    }


async def summarize_thread(thread_id: str) -> dict:
    """Consolidate and summarize an email thread.

    Args:
        thread_id: JMAP thread ID.

    Returns:
        Thread summary with individual email summaries and overall summary.
    """
    require_scope("mail:read")

    # Get all emails in the thread
    query_result = await jmap_client.method_call(
        "Email/query",
        {
            "filter": {"inThread": thread_id},
            "sort": [{"property": "receivedAt", "isAscending": True}],
        },
    )

    email_ids = query_result.get("ids", [])
    if not email_ids:
        return {"error": "Thread not found or empty"}

    get_result = await jmap_client.method_call(
        "Email/get",
        {
            "ids": email_ids,
            "properties": ["id", "subject", "from", "receivedAt", "preview", "mailboxIds"],
        },
    )

    all_mailboxes = await get_all_mailboxes()
    allowlist_ids, denylist_ids = _resolve_label_ids(all_mailboxes)

    thread_text_parts = []
    emails_meta = []

    for email in get_result.get("list", []):
        email_mailbox_ids = set(email.get("mailboxIds", {}).keys())
        if not _is_allowed(email_mailbox_ids, allowlist_ids, denylist_ids):
            continue

        preview = email.get("preview", "")
        sender = email.get("from", [{}])[0].get("email", "unknown")
        thread_text_parts.append(f"From {sender}: {preview}")
        emails_meta.append({
            "id": email["id"],
            "subject": email.get("subject", ""),
            "from": sender,
            "date": email.get("receivedAt", ""),
        })

    combined_text = "\n\n".join(thread_text_parts)
    overall_summary = await summarize_text(combined_text)

    return {
        "thread_id": thread_id,
        "email_count": len(emails_meta),
        "emails": emails_meta,
        "summary": overall_summary,
    }


async def sync_fastmail() -> dict:
    """Trigger a JMAP sync / session refresh."""
    await jmap_client.connect()
    return {
        "status": "ok",
        "account_id": jmap_client.account_id,
        "api_url": jmap_client.api_url,
    }
