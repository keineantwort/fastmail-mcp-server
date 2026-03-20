"""MCP tool definitions for Fastmail email operations."""

from fastmail_mcp.jmap.client import jmap_client
from fastmail_mcp.jmap.mailbox import get_all_mailboxes, get_mailbox_id_by_name
from fastmail_mcp.oauth.scopes import require_scope
from fastmail_mcp.utils.quote_cleaner import clean_quoted_text
from fastmail_mcp.utils.summarizer import summarize_text

# Label that blocks access entirely
DENYLIST_LABEL = "Denylist"


async def search_emails(query: str, label: str) -> list[dict]:
    """Search emails within a specific label.

    Args:
        query: Search query string.
        label: Label/mailbox name to search within.

    Returns:
        List of email summaries with id, subject, from, date, and AI summary.
    """
    require_scope("mail:read")

    mailbox_id = await get_mailbox_id_by_name(label)
    if mailbox_id is None:
        return []

    # Query emails in the mailbox
    query_result = await jmap_client.method_call(
        "Email/query",
        {
            "filter": {
                "inMailbox": mailbox_id,
                "text": query,
            },
            "sort": [{"property": "receivedAt", "isAscending": False}],
            "limit": 20,
        },
    )

    email_ids = query_result.get("ids", [])
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

    # Filter: check none have the denylist label
    all_mailboxes = await get_all_mailboxes()
    denylist_ids = {mid for mid, name in all_mailboxes.items() if name == DENYLIST_LABEL}

    results = []
    for email in get_result.get("list", []):
        email_mailbox_ids = set(email.get("mailboxIds", {}).keys())
        if email_mailbox_ids & denylist_ids:
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

    HARD-BLOCKS any email with the 'Denylist' label.

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

    # HARD-BLOCK: check denylist
    all_mailboxes = await get_all_mailboxes()
    denylist_ids = {mid for mid, name in all_mailboxes.items() if name == DENYLIST_LABEL}
    email_mailbox_ids = set(email.get("mailboxIds", {}).keys())

    if email_mailbox_ids & denylist_ids:
        return {"error": "Access denied: this email is on the denylist."}

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

    # Filter out denylisted emails
    all_mailboxes = await get_all_mailboxes()
    denylist_ids = {mid for mid, name in all_mailboxes.items() if name == DENYLIST_LABEL}

    thread_text_parts = []
    emails_meta = []

    for email in get_result.get("list", []):
        email_mailbox_ids = set(email.get("mailboxIds", {}).keys())
        if email_mailbox_ids & denylist_ids:
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
