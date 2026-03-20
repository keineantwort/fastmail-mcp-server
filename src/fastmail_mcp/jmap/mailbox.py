"""Mailbox (label/folder) helpers for JMAP."""

from fastmail_mcp.jmap.client import jmap_client


async def get_mailbox_id_by_name(name: str) -> str | None:
    """Find a mailbox ID by its name (label)."""
    result = await jmap_client.method_call(
        "Mailbox/query",
        {
            "filter": {"name": name},
        },
    )
    ids = result.get("ids", [])
    return ids[0] if ids else None


async def get_all_mailboxes() -> dict[str, str]:
    """Return a mapping of mailbox_id -> mailbox_name."""
    result = await jmap_client.method_call(
        "Mailbox/get",
        {"properties": ["id", "name"]},
    )
    return {mb["id"]: mb["name"] for mb in result.get("list", [])}
