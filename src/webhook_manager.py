"""Outgoing webhook manager — fires HTTP POSTs when events happen."""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import re
from typing import Optional

import httpx

from core.database import utcnow_naive
from src.database import SessionLocal, Webhook
from src.url_safety import OutboundAddressBlocked, PinnedAsyncTransport, resolve_outbound_url

logger = logging.getLogger(__name__)

ALLOWED_EVENTS = frozenset({
    "session.created",
    "chat.completed",
    "chat.message",
    "webhook.test",
})


def _validated_public_ips(url: str) -> list:
    """Resolve *url*'s host once and return its public IPs, or raise ValueError.

    Delivery pins the connect to these IPs so DNS rebinding cannot swap in an
    internal address between this check and the socket connect.
    """
    try:
        return resolve_outbound_url(url, block_private=True)
    except OutboundAddressBlocked as e:
        raise ValueError(f"URL must not point to private/internal addresses ({e})") from e


def validate_webhook_url(url: str) -> str:
    """Validate and normalize a webhook URL. Raises ValueError if invalid."""
    url = url.strip()
    if len(url) > 2048:
        raise ValueError("URL too long (max 2048 characters)")
    _validated_public_ips(url)
    return url


def validate_events(events_str: str) -> str:
    """Validate comma-separated event names. Returns cleaned string."""
    events = [e.strip() for e in events_str.split(",") if e.strip()]
    if not events:
        raise ValueError("At least one event is required")
    invalid = set(events) - ALLOWED_EVENTS
    if invalid:
        raise ValueError(f"Invalid events: {', '.join(sorted(invalid))}. Allowed: {', '.join(sorted(ALLOWED_EVENTS - {'webhook.test'}))}")
    return ",".join(events)


# Broad candidate matcher for the IP-redaction pass. Deliberately loose: a
# bracketed host authority ([fe80::1%eth0]:8080 and friends) with an optional
# :port, or a bare IPv6 run — hex groups joined by colons, an optional trailing
# dotted-quad for IPv4-mapped forms (::ffff:192.168.0.1), and an optional %zone.
# It does NOT encode the IPv6 grammar; ipaddress.ip_address() is the real
# validator (see _redact_ip_candidate), so any colon-bearing string it rejects
# (clock times, MACs, "std::vector") is left alone. Every branch is a single
# greedy class or a repetition over a mandatory ':'/'.' delimiter, so there is no
# nested-quantifier backtracking (ReDoS-safe).
_IP_CANDIDATE = re.compile(
    r'\[[^\[\]\s]*\](?::\d+)?'
    r'|(?<![\w.:%])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,}'
    r'(?:(?:\.[0-9]{1,3}){3})?(?:%[0-9A-Za-z._-]+)?'
)


def _redact_ip_candidate(match: re.Match) -> str:
    """Redact a candidate token that the stdlib confirms is an IP address.

    A bare token is redacted only when it parses as IPv6 — bare IPv4 is left to
    the dedicated IPv4 pass. A bracketed token is a host authority, so a v4 or v6
    literal inside [ ] is redacted as a whole. This keeps output consistent (one
    [redacted], never nested or partial) for scoped/mapped/ported forms.
    """
    token = match.group(0)
    bracketed = token.startswith('[')
    candidate = token
    if bracketed:
        # Keep only what's inside [...]; the trailing :port is dropped.
        candidate = candidate[1:candidate.index(']')]
    # A zone id (fe80::1%eth0) is not part of the address ipaddress parses.
    candidate = candidate.split('%', 1)[0]
    # The loose bare pattern can trail one stray ':' (e.g. "::1:" in "host ::1:
    # down"); drop it unless it's the "::" compression marker.
    if candidate.endswith(':') and not candidate.endswith('::'):
        candidate = candidate[:-1]
    try:
        addr = ipaddress.ip_address(candidate)
    except ValueError:
        return token
    if bracketed or isinstance(addr, ipaddress.IPv6Address):
        return '[redacted]'
    return token


def sanitize_error(error: str, max_len: int = 200) -> str:
    """Strip potentially sensitive details from error messages."""
    # Redact IPv6 (and bracketed-authority) addresses first, so an IPv4-mapped
    # form like ::ffff:192.168.0.1 is scrubbed as one unit instead of having its
    # embedded IPv4 removed first and leaving a stray "::ffff:" behind. Broad
    # candidates are validated by ipaddress.ip_address(), so the false-positive
    # guards (clock times, MACs, C++ "::") come from the stdlib, not a regex.
    cleaned = _IP_CANDIDATE.sub(_redact_ip_candidate, error)
    # Remove remaining bare IPv4 addresses and ports.
    cleaned = re.sub(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?', '[redacted]', cleaned)
    # Remove hostnames in URLs.
    cleaned = re.sub(r'https?://[^\s/]+', '[redacted-url]', cleaned)
    return cleaned[:max_len]


def _active_webhooks_for(event: str) -> list:
    db = SessionLocal()
    try:
        webhooks = db.query(Webhook).filter(Webhook.is_active == True).all()  # noqa: E712
        return [w for w in webhooks if event in w.events.split(",")]
    finally:
        db.close()


def _record_delivery(webhook_id: str, outcome: dict) -> None:
    db = SessionLocal()
    try:
        db.query(Webhook).filter(Webhook.id == webhook_id).update(
            {"last_triggered_at": utcnow_naive(), **outcome}
        )
        db.commit()
    except Exception:
        logger.warning("Could not record delivery for webhook %s", webhook_id, exc_info=True)
        db.rollback()
    finally:
        db.close()


class WebhookManager:
    def __init__(self, api_key_manager=None):
        # No shared client: each delivery builds a short-lived client whose
        # transport is pinned to the SSRF-approved IP (see _deliver /
        # _send_request), so a single reusable client can't be pointed at
        # different pinned hosts. Redirects stay disabled on every delivery
        # client to prevent SSRF via redirect chains.
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._api_key_manager = api_key_manager
        # Strong references to in-flight fire-and-forget tasks. asyncio only
        # keeps weak references to tasks, so without this the GC can collect a
        # delivery task mid-flight and the webhook is silently never sent.
        self._bg_tasks: set = set()

    def _spawn_tracked(self, coro):
        """Schedule a background task and hold a strong reference until it
        finishes, so it can't be garbage-collected before delivery completes."""
        task = asyncio.ensure_future(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def _decrypt_secret(self, encrypted: Optional[str]) -> Optional[str]:
        """Decrypt a webhook signing secret from DB storage."""
        if not encrypted:
            return None
        if self._api_key_manager:
            try:
                return self._api_key_manager.decrypt_api_key(encrypted)
            except Exception:
                # If decryption fails, assume it's stored in plaintext (legacy)
                return encrypted
        return encrypted

    def fire_and_forget(self, event: str, payload: dict):
        """Schedule webhook fire from any context (sync or async). Never blocks."""
        if event not in ALLOWED_EVENTS:
            return
        try:
            asyncio.get_running_loop()
            self._spawn_tracked(self.fire(event, payload))
        except RuntimeError:
            # Called from a sync thread (e.g. sync FastAPI route in threadpool)
            if self._loop and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self.fire(event, payload), self._loop)

    async def fire(self, event: str, payload: dict):
        """Fire webhooks matching the given event."""
        if event not in ALLOWED_EVENTS:
            return
        matching = await asyncio.to_thread(_active_webhooks_for, event)
        for wh in matching:
            decrypted_secret = self._decrypt_secret(wh.secret)
            self._spawn_tracked(self._deliver(wh.id, wh.url, decrypted_secret, event, payload))

    async def deliver_test(self, webhook_id: str, url: str, encrypted_secret: Optional[str]):
        """Public method for the test-webhook route."""
        decrypted = self._decrypt_secret(encrypted_secret)
        await self._deliver(webhook_id, url, decrypted, "webhook.test", {"message": "Test ping from Odysseus"})

    async def _send_request(self, url: str, body: str, headers: dict,
                            ips: list) -> httpx.Response:
        """POST *body* to *url* with the TCP connect pinned to *ips*.

        Overridable seam: tests replace this to avoid real sockets. Redirects
        are disabled so a 3xx can't bounce the delivery to another host.
        """
        transport = PinnedAsyncTransport(ips)
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=False, transport=transport,
        ) as client:
            return await client.post(url, content=body, headers=headers)

    async def _deliver(self, webhook_id: str, url: str, secret: Optional[str], event: str, payload: dict):
        """Internal delivery. Never call directly from outside this class (use deliver_test)."""
        # Re-validated at delivery in case the stored URL was tampered with.
        try:
            pinned_ips = await asyncio.to_thread(_validated_public_ips, url)
        except ValueError as e:
            logger.warning(f"Webhook {webhook_id} has invalid URL, skipping: {e}")
            return

        body = json.dumps({"event": event, "timestamp": utcnow_naive().isoformat(), "data": payload})
        headers = {
            "Content-Type": "application/json",
            "X-Odysseus-Event": event,
            "User-Agent": "Odysseus-Webhook/1.0",
        }
        if secret:
            sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
            headers["X-Odysseus-Signature"] = sig

        try:
            resp = await self._send_request(url, body, headers, pinned_ips)
            outcome = {"last_status_code": resp.status_code, "last_error": None}
        except Exception as e:
            logger.warning(f"Webhook delivery failed for {webhook_id}")
            outcome = {"last_status_code": None, "last_error": sanitize_error(str(e))}
        await asyncio.to_thread(_record_delivery, webhook_id, outcome)

    async def close(self):
        # Delivery clients are per-request and closed via their async context
        # manager, so there is no long-lived client to tear down here. Kept for
        # API compatibility with callers (e.g. app shutdown).
        return None
