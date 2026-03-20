"""List emails from Fastmail using .env credentials.

Usage:
    python tests/list_emails.py
"""

import asyncio
import json
import os

import httpx
from dotenv import load_dotenv

load_dotenv()


async def main():
    token = os.environ["FASTMAIL_API_TOKEN"]
    jmap_url = os.environ.get("FASTMAIL_JMAP_URL", "https://api.fastmail.com/jmap/session")
    allowlist = json.loads(os.environ.get("ALLOWLIST_LABELS", "[]"))
    denylist_label = os.environ.get("DENYLIST_LABEL", "Denylist")

    async with httpx.AsyncClient(
        timeout=30,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    ) as client:
        # Session
        sess = (await client.get(jmap_url)).json()
        api_url = sess["apiUrl"]
        account_id = sess["primaryAccounts"]["urn:ietf:params:jmap:mail"]

        async def call(method, args):
            args.setdefault("accountId", account_id)
            r = await client.post(api_url, json={
                "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
                "methodCalls": [[method, args, "c0"]],
            })
            return r.json()["methodResponses"][0][1]

        # Get all mailboxes
        mbs = await call("Mailbox/get", {"properties": ["id", "name"]})
        mb_map = {m["id"]: m["name"] for m in mbs["list"]}

        # Resolve allowlist/denylist
        allow_ids = {mid for mid, name in mb_map.items() if name in allowlist}
        deny_ids = {mid for mid, name in mb_map.items() if name == denylist_label}

        print(f"Allowlist: {allowlist} -> {len(allow_ids)} mailbox(es)")
        print(f"Denylist:  '{denylist_label}' -> {len(deny_ids)} mailbox(es)")
        print()

        # Search in each allowlist label (or Inbox if no allowlist)
        for label in allowlist or ["Inbox"]:
            mb_q = await call("Mailbox/query", {"filter": {"name": label}})
            if not mb_q.get("ids"):
                print(f'Label "{label}": NOT FOUND')
                continue

            mb_id = mb_q["ids"][0]
            q = await call("Email/query", {
                "filter": {"inMailbox": mb_id},
                "sort": [{"property": "receivedAt", "isAscending": False}],
                "limit": 30,
            })
            ids = q.get("ids", [])
            total = q.get("total", "?")
            print(f"=== {label} ({total} total) ===")

            if not ids:
                print("  (keine Mails)")
                continue

            emails = await call("Email/get", {
                "ids": ids,
                "properties": ["id", "subject", "from", "receivedAt", "preview", "mailboxIds"],
            })

            for e in emails.get("list", []):
                e_mbs = set(e.get("mailboxIds", {}).keys())
                labels = [mb_map.get(m, m) for m in e_mbs]

                # Filter
                if allow_ids and not (e_mbs & allow_ids):
                    status = "BLOCKED"
                elif e_mbs & deny_ids:
                    status = "DENIED"
                else:
                    status = "OK"

                sender = e.get("from", [{}])[0].get("email", "?")
                date = e.get("receivedAt", "")[:10]
                subj = e.get("subject", "(no subject)")
                print(f"  [{status:7s}] {date} | {sender:30s} | {subj}")
                print(f"            Labels: {labels}")


if __name__ == "__main__":
    asyncio.run(main())
