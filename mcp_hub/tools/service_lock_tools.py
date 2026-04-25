"""Service lock tools for cross-agent coordination during maintenance windows.

Agents take a lock before bringing down a shared service (gitlab, mcp-hub, k8s,
argocd, etc.) so other agents can query the lock instead of retrying blindly or
filing confused cascading tickets.

Locks auto-expire after 2 hours as a safety net against stuck locks.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from mcp_hub.database import async_session
from mcp_hub.models.service_lock import LOCK_AUTO_EXPIRE_HOURS, ServiceLock


def _fmt_lock(lock: ServiceLock) -> str:
    """Format a single lock for display."""
    lines = [
        f"  Lock #{lock.id}: {lock.service}",
        f"    Held by: {lock.holder_role}",
        f"    Reason: {lock.reason}",
        f"    Since: {lock.acquired_at:%Y-%m-%d %H:%M UTC}",
    ]
    if lock.expected_back_at:
        lines.append(f"    Expected back: {lock.expected_back_at:%Y-%m-%d %H:%M UTC}")
    if lock.holder_session_id:
        lines.append(f"    Session: {lock.holder_session_id}")
    return "\n".join(lines)


async def lock_service(
    service: str,
    holder_role: str,
    reason: str,
    expected_back_at: str = "",
    holder_session_id: str = "",
) -> str:
    """Acquire a service lock. Call before taking a shared service down.

    service: short name, e.g. 'gitlab', 'mcp-hub', 'k8s-control-plane', 'argocd'
    expected_back_at: optional ISO8601 timestamp when the service will be back
    """
    if not service.strip():
        return "Error: service cannot be empty"
    if not holder_role.strip():
        return "Error: holder_role cannot be empty"
    if not reason.strip():
        return "Error: reason cannot be empty"

    service = service.strip().lower()
    holder_role = holder_role.strip()
    reason = reason.strip()

    parsed_expected: datetime | None = None
    if expected_back_at:
        try:
            parsed_expected = datetime.fromisoformat(expected_back_at.replace("Z", "+00:00"))
            if parsed_expected.tzinfo is None:
                parsed_expected = parsed_expected.replace(tzinfo=UTC)
        except ValueError:
            return f"Error: invalid expected_back_at '{expected_back_at}' — use ISO8601 format"

    async with async_session() as session:
        # Check if already locked (active lock with no released_at)
        existing = (
            await session.execute(
                select(ServiceLock).where(
                    ServiceLock.service == service,
                    ServiceLock.released_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        if existing is not None:
            return (
                f"Error: '{service}' is already locked by {existing.holder_role} "
                f"(lock #{existing.id}, since {existing.acquired_at:%Y-%m-%d %H:%M UTC}). "
                f"Reason: {existing.reason}"
            )

        lock = ServiceLock(
            service=service,
            holder_role=holder_role,
            holder_session_id=holder_session_id.strip() or None,
            reason=reason,
            expected_back_at=parsed_expected,
        )
        session.add(lock)
        await session.commit()
        await session.refresh(lock)

        msg = (
            f"Lock #{lock.id} acquired: '{service}' locked by {holder_role}\n"
            f"  Reason: {reason}\n"
            f"  Auto-expires after {LOCK_AUTO_EXPIRE_HOURS}h if not released"
        )
        if parsed_expected:
            msg += f"\n  Expected back: {parsed_expected:%Y-%m-%d %H:%M UTC}"
        return msg


async def unlock_service(lock_id: int, message: str = "") -> str:
    """Release a service lock. Call when the service is healthy again."""
    async with async_session() as session:
        lock = await session.get(ServiceLock, lock_id)
        if lock is None:
            return f"Error: lock #{lock_id} not found"
        if lock.released_at is not None:
            return (
                f"Error: lock #{lock_id} for '{lock.service}' was already released "
                f"at {lock.released_at:%Y-%m-%d %H:%M UTC}"
            )

        lock.released_at = datetime.now(UTC)
        await session.commit()

        held_minutes = int((lock.released_at - lock.acquired_at).total_seconds() / 60)
        result = (
            f"Lock #{lock_id} released: '{lock.service}' is now unlocked\n"
            f"  Held for {held_minutes} minutes by {lock.holder_role}"
        )
        if message:
            result += f"\n  Note: {message.strip()}"
        return result


async def get_service_status(service: str) -> str:
    """Check whether a service is currently locked.

    Returns locked status, holder, reason, and expected_back_at if locked.
    Returns locked: false if the service is available.
    """
    if not service.strip():
        return "Error: service cannot be empty"

    service = service.strip().lower()

    async with async_session() as session:
        lock = (
            await session.execute(
                select(ServiceLock).where(
                    ServiceLock.service == service,
                    ServiceLock.released_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        if lock is None:
            return f"service: {service}\nlocked: false"

        lines = [
            f"service: {service}",
            "locked: true",
            f"lock_id: {lock.id}",
            f"holder_role: {lock.holder_role}",
            f"reason: {lock.reason}",
            f"since: {lock.acquired_at:%Y-%m-%d %H:%M UTC}",
        ]
        if lock.expected_back_at:
            lines.append(f"expected_back_at: {lock.expected_back_at:%Y-%m-%d %H:%M UTC}")
        if lock.holder_session_id:
            lines.append(f"holder_session_id: {lock.holder_session_id}")
        return "\n".join(lines)


async def list_service_locks(active_only: bool = True, limit: int = 50) -> str:
    """List service locks.

    active_only=true (default): only show currently held locks (released_at IS NULL)
    active_only=false: show all locks including released ones
    """
    limit = max(1, min(limit, 200))

    async with async_session() as session:
        query = select(ServiceLock).order_by(ServiceLock.acquired_at.desc()).limit(limit)
        if active_only:
            query = query.where(ServiceLock.released_at.is_(None))

        locks = (await session.execute(query)).scalars().all()

        if not locks:
            label = "active service locks" if active_only else "service locks"
            return f"No {label} found"

        label = "Active service locks" if active_only else "Service locks"
        lines = [f"{label} ({len(locks)}):"]
        for lock in locks:
            lines.append(_fmt_lock(lock))
            if lock.released_at:
                lines.append(f"    Released: {lock.released_at:%Y-%m-%d %H:%M UTC}")
        return "\n".join(lines)
