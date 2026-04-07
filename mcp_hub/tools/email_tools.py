"""Email tools — sync from Stalwart JMAP and query cached metadata."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, func, select

from mcp_hub.config import settings
from mcp_hub.database import async_session
from mcp_hub.models.email import EmailMessage, EmailSyncState

logger = logging.getLogger(__name__)

JMAP_PROPERTIES = [
    "id",
    "mailboxIds",
    "from",
    "to",
    "cc",
    "subject",
    "preview",
    "size",
    "receivedAt",
    "keywords",
    "hasAttachment",
]


def _addr_list(addrs: list[dict] | None) -> str:
    """Format JMAP address list to 'Name <email>' strings."""
    if not addrs:
        return ""
    parts = []
    for a in addrs:
        name = a.get("name", "")
        email = a.get("email", "")
        parts.append(f"{name} <{email}>" if name else email)
    return ", ".join(parts)


def _jmap_auth() -> tuple[str, str]:
    """Return (url, base64 auth header) for Stalwart JMAP."""
    return settings.stalwart_jmap_url, settings.stalwart_jmap_token


async def _jmap_request(method_calls: list) -> dict:
    """Execute a JMAP request against Stalwart."""
    url, token = _jmap_auth()
    if not url:
        raise ConnectionError("Stalwart JMAP not configured (set MH_STALWART_JMAP_URL)")

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        "methodCalls": method_calls,
    }

    async with httpx.AsyncClient(verify=False, timeout=30) as client:  # noqa: S501
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def sync_emails(limit: int = 200) -> str:
    """Sync recent emails from Stalwart JMAP into the local database.

    Fetches the most recent emails and upserts metadata into PostgreSQL.
    """
    limit = max(1, min(limit, 1000))

    try:
        # Query for recent email IDs
        result = await _jmap_request(
            [
                [
                    "Email/query",
                    {
                        "sort": [{"property": "receivedAt", "isAscending": False}],
                        "limit": limit,
                    },
                    "q0",
                ],
                [
                    "Email/get",
                    {
                        "#ids": {"resultOf": "q0", "name": "Email/query", "path": "/ids"},
                        "properties": JMAP_PROPERTIES,
                    },
                    "g0",
                ],
            ]
        )
    except ConnectionError as e:
        return f"Error: {e}"
    except httpx.HTTPError as e:
        return f"Error connecting to Stalwart: {e}"

    method_responses = result.get("methodResponses", [])

    # Find the Email/get response
    emails_data = None
    account_id = None
    for resp in method_responses:
        if resp[0] == "Email/get":
            emails_data = resp[1].get("list", [])
            account_id = resp[1].get("accountId", "default")
            break

    if emails_data is None:
        return "Error: no Email/get response from JMAP server"

    synced = 0
    async with async_session() as session:
        for email in emails_data:
            jmap_id = email.get("id")
            if not jmap_id:
                continue

            # Resolve mailbox (use first mailbox ID)
            mailbox_ids = email.get("mailboxIds", {})
            mailbox = next(iter(mailbox_ids.keys()), "unknown") if mailbox_ids else "unknown"

            # Parse keywords for flags
            keywords = email.get("keywords", {})
            is_read = "$seen" in keywords
            is_flagged = "$flagged" in keywords

            received_str = email.get("receivedAt", "")
            try:
                received_at = datetime.fromisoformat(received_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                received_at = datetime.now(tz=UTC)

            # Upsert: delete old then insert
            await session.execute(delete(EmailMessage).where(EmailMessage.jmap_id == jmap_id))
            msg = EmailMessage(
                jmap_id=jmap_id,
                mailbox=mailbox,
                from_addr=_addr_list(email.get("from")),
                to_addr=_addr_list(email.get("to")),
                cc_addr=_addr_list(email.get("cc")),
                subject=email.get("subject", "(no subject)"),
                preview=email.get("preview", ""),
                size_bytes=email.get("size", 0),
                is_read=is_read,
                is_flagged=is_flagged,
                has_attachment=email.get("hasAttachment", False),
                received_at=received_at,
            )
            session.add(msg)
            synced += 1

        # Update sync state
        state = (
            await session.execute(
                select(EmailSyncState).where(EmailSyncState.account_id == (account_id or "default"))
            )
        ).scalar_one_or_none()
        if state:
            state.last_sync = datetime.now(tz=UTC)
            state.total_synced += synced
        else:
            session.add(
                EmailSyncState(
                    account_id=account_id or "default",
                    total_synced=synced,
                )
            )

        await session.commit()

    return f"Synced {synced} emails from Stalwart into database"


async def search_emails(
    query: str = "",
    from_addr: str = "",
    to_addr: str = "",
    days: int = 30,
    unread_only: bool = False,
    flagged_only: bool = False,
    limit: int = 25,
) -> str:
    """Search cached email metadata by sender, recipient, subject, or date range."""
    limit = max(1, min(limit, 100))

    async with async_session() as session:
        q = select(EmailMessage).order_by(EmailMessage.received_at.desc())

        if query:
            q = q.where(EmailMessage.subject.ilike(f"%{query}%"))
        if from_addr:
            q = q.where(EmailMessage.from_addr.ilike(f"%{from_addr}%"))
        if to_addr:
            q = q.where(EmailMessage.to_addr.ilike(f"%{to_addr}%"))
        if days > 0:
            cutoff = datetime.now(tz=UTC) - timedelta(days=days)
            q = q.where(EmailMessage.received_at >= cutoff)
        if unread_only:
            q = q.where(EmailMessage.is_read == False)  # noqa: E712
        if flagged_only:
            q = q.where(EmailMessage.is_flagged == True)  # noqa: E712

        q = q.limit(limit)
        emails = (await session.execute(q)).scalars().all()

        if not emails:
            return "No emails found matching your criteria"

        lines = [f"Email search results ({len(emails)}):"]
        for e in emails:
            flags = ""
            if not e.is_read:
                flags += " [UNREAD]"
            if e.is_flagged:
                flags += " [FLAGGED]"
            if e.has_attachment:
                flags += " [ATTACH]"
            lines.append(
                f"  {e.received_at:%Y-%m-%d %H:%M}{flags}\n"
                f"    From: {e.from_addr}\n"
                f"    To: {e.to_addr}\n"
                f"    Subject: {e.subject}"
            )
            if e.preview:
                preview = e.preview[:120] + "..." if len(e.preview) > 120 else e.preview
                lines.append(f"    Preview: {preview}")

        return "\n".join(lines)


async def email_stats(days: int = 30) -> str:
    """Get email statistics: volume by sender, unread count, daily trends."""
    async with async_session() as session:
        cutoff = datetime.now(tz=UTC) - timedelta(days=days)

        # Total count
        total = (
            await session.execute(
                select(func.count(EmailMessage.id)).where(EmailMessage.received_at >= cutoff)
            )
        ).scalar() or 0

        # Unread count
        unread = (
            await session.execute(
                select(func.count(EmailMessage.id)).where(
                    EmailMessage.received_at >= cutoff,
                    EmailMessage.is_read == False,  # noqa: E712
                )
            )
        ).scalar() or 0

        # Flagged count
        flagged = (
            await session.execute(
                select(func.count(EmailMessage.id)).where(
                    EmailMessage.received_at >= cutoff,
                    EmailMessage.is_flagged == True,  # noqa: E712
                )
            )
        ).scalar() or 0

        # With attachments
        with_attach = (
            await session.execute(
                select(func.count(EmailMessage.id)).where(
                    EmailMessage.received_at >= cutoff,
                    EmailMessage.has_attachment == True,  # noqa: E712
                )
            )
        ).scalar() or 0

        # Top senders
        top_senders_q = (
            select(EmailMessage.from_addr, func.count(EmailMessage.id).label("cnt"))
            .where(EmailMessage.received_at >= cutoff)
            .group_by(EmailMessage.from_addr)
            .order_by(func.count(EmailMessage.id).desc())
            .limit(10)
        )
        top_senders = (await session.execute(top_senders_q)).all()

        # Total size
        total_size = (
            await session.execute(
                select(func.sum(EmailMessage.size_bytes)).where(EmailMessage.received_at >= cutoff)
            )
        ).scalar() or 0

        # Sync state
        sync_state = (await session.execute(select(EmailSyncState).limit(1))).scalar_one_or_none()

        lines = [
            f"# Email Stats (last {days} days)",
            "",
            f"**Total emails:** {total}",
            f"**Unread:** {unread}",
            f"**Flagged:** {flagged}",
            f"**With attachments:** {with_attach}",
            f"**Total size:** {total_size / 1024 / 1024:.1f} MB",
        ]

        if sync_state:
            lines.append(f"**Last sync:** {sync_state.last_sync:%Y-%m-%d %H:%M}")
            lines.append(f"**Total ever synced:** {sync_state.total_synced}")

        if top_senders:
            lines.extend(["", "## Top Senders"])
            for sender, count in top_senders:
                lines.append(f"  {count:>4}  {sender}")

        return "\n".join(lines)


async def email_get(jmap_id: str) -> str:
    """Fetch full email body from Stalwart JMAP by message ID."""
    if not jmap_id.strip():
        return "Error: jmap_id required"

    try:
        result = await _jmap_request(
            [
                [
                    "Email/get",
                    {
                        "ids": [jmap_id],
                        "properties": [
                            "id",
                            "from",
                            "to",
                            "cc",
                            "subject",
                            "receivedAt",
                            "textBody",
                            "htmlBody",
                            "bodyValues",
                            "hasAttachment",
                            "attachments",
                        ],
                        "fetchTextBodyValues": True,
                        "fetchHTMLBodyValues": True,
                    },
                    "g0",
                ],
            ]
        )
    except (ConnectionError, httpx.HTTPError) as e:
        return f"Error fetching email: {e}"

    for resp in result.get("methodResponses", []):
        if resp[0] == "Email/get":
            emails = resp[1].get("list", [])
            if not emails:
                return f"Error: email {jmap_id} not found"

            email = emails[0]
            body_values = email.get("bodyValues", {})

            # Get text body
            body = ""
            for part in email.get("textBody", []):
                part_id = part.get("partId", "")
                if part_id in body_values:
                    body = body_values[part_id].get("value", "")
                    break

            # Fallback to HTML body
            if not body:
                for part in email.get("htmlBody", []):
                    part_id = part.get("partId", "")
                    if part_id in body_values:
                        body = body_values[part_id].get("value", "")
                        break

            attachments = email.get("attachments", [])
            att_info = ""
            if attachments:
                att_names = [a.get("name", "unnamed") for a in attachments]
                att_info = f"\n**Attachments:** {', '.join(att_names)}"

            return (
                f"# {email.get('subject', '(no subject)')}\n\n"
                f"**From:** {_addr_list(email.get('from'))}\n"
                f"**To:** {_addr_list(email.get('to'))}\n"
                f"**CC:** {_addr_list(email.get('cc'))}\n"
                f"**Date:** {email.get('receivedAt', 'unknown')}\n"
                f"{att_info}\n\n"
                f"---\n\n{body}"
            )

    return "Error: unexpected JMAP response"
