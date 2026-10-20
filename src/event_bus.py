"""Event bus: events such as session creation bump counters on event-triggered tasks and fire them."""

import asyncio
import json
import logging
from typing import Optional

from src.constants import AUTH_FILE

logger = logging.getLogger(__name__)

_task_scheduler = None


def _event_automation_enabled_for_owner(owner: Optional[str]) -> bool:
    """Synthetic fixture activity must not auto-fire durable user tasks."""
    return not str(owner or "").strip().casefold().startswith("sft_")


def set_task_scheduler(scheduler):
    """Wire up the scheduler reference (called from app.py on startup)."""
    global _task_scheduler
    _task_scheduler = scheduler


def get_task_scheduler():
    """Return the current task scheduler instance."""
    return _task_scheduler


def fire_event(event_name: str, owner: Optional[str] = None):
    """Fire an event — increments counters and triggers tasks that hit threshold.

    Safe to call from both sync and async contexts.
    """
    try:
        loop = asyncio.get_running_loop()
        # Let the request that emitted the event finish before automation can
        # start model work on the same event loop. Otherwise a document create
        # can appear to hang while an event-triggered task is running.
        # Keep the handoff outside the response flush window. Event-triggered
        # tasks may still perform synchronous work before their first await.
        loop.call_later(1.0, lambda: loop.create_task(_handle_event(event_name, owner)))
    except RuntimeError:
        # No running loop — run in a new one (shouldn't happen in FastAPI)
        asyncio.run(_handle_event(event_name, owner))


def _resolve_event_owner(owner: Optional[str]) -> Optional[str]:
    """Resolve ownerless app events to the primary configured user.

    Some event sources run from localhost/internal code paths where request
    middleware is not present, so they cannot pass a username. Treating that as
    "all owners" made built-in tasks run once per account. Instead, route those
    events to the first admin account, matching the legacy-owner migration.
    """
    owner = (owner or "").strip()
    if owner:
        return owner

    try:
        auth_path = AUTH_FILE
        with open(auth_path, "r", encoding="utf-8") as f:
            users = (json.load(f).get("users") or {})
        for username, data in users.items():
            if data.get("is_admin") is True:
                return username
        if users:
            return next(iter(users))
    except Exception:
        logger.debug("Could not resolve ownerless event owner", exc_info=True)
    return None


def _advance_event_counters(event_name: str, owner: Optional[str]) -> list:
    """Bump each matching task's counter; return (id, name, threshold) for tasks that hit it."""
    from core.database import SessionLocal, ScheduledTask, utcnow_naive

    db = SessionLocal()
    try:
        filters = [
            ScheduledTask.trigger_type == "event",
            ScheduledTask.trigger_event == event_name,
            ScheduledTask.status == "active",
        ]
        if owner:
            filters.append(ScheduledTask.owner == owner)
        else:
            filters.append(ScheduledTask.owner == None)  # noqa: E711

        due = []
        for task in db.query(ScheduledTask).filter(*filters).all():
            threshold = task.trigger_count or 1
            task.trigger_counter = (task.trigger_counter or 0) + 1
            if task.trigger_counter >= threshold:
                task.trigger_counter = 0
                # Persisted before the in-memory handoff: if the process restarts
                # while the task waits behind a model call, `next_run <= now`
                # keeps the trigger alive after the counter has reset.
                task.next_run = utcnow_naive()
                due.append((task.id, task.name, threshold))
            else:
                logger.debug(f"Event '{event_name}': task '{task.name}' counter {task.trigger_counter}/{threshold}")
        db.commit()
        return due
    finally:
        db.close()


async def _handle_event(event_name: str, owner: Optional[str] = None):
    """Process an event: increment counters, fire tasks that hit their threshold."""
    resolved_owner = _resolve_event_owner(owner)
    if not _event_automation_enabled_for_owner(resolved_owner):
        return
    try:
        due = await asyncio.to_thread(_advance_event_counters, event_name, resolved_owner)
        for task_id, name, threshold in due:
            if _task_scheduler:
                logger.info(f"Event '{event_name}' triggered task '{name}' (every {threshold})")
                await _task_scheduler.run_task_now(task_id)
            else:
                logger.warning(f"Event triggered task '{name}' but no scheduler available")
    except Exception:
        logger.exception(f"Error handling event '{event_name}'")
