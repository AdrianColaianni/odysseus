"""Deep secret-scrubbing for settings served to non-admin and unauthenticated callers.

`/api/auth/settings` is auth-exempt (the login page reads keybinds and TTS
prefs), so keys, passwords and tokens must be removed. Stdlib only so it
imports without the app and database chain.
"""

import re

_SECRET_KEY_PATTERNS = (
    "_api_key", "_apikey", "_password", "_passwd", "_pass", "_pwd",
    "_secret", "_client_secret", "_token", "_access_token", "_refresh_token",
    "_credential", "_credentials", "_key",
)
_SECRET_KEY_ALLOW = ("google_pse_cx",)  # public identifiers, not secrets
_SENSITIVE_KEY_EXACT = (
    # A stable global integration id is a capability handle for routes that can
    # trigger outbound webhook sends; do not expose it to non-admin settings
    # callers even though it is not secret-shaped.
    "reminder_webhook_integration_id",
)


def _canonical_key_name(name: str) -> str:
    """Normalize common JS-style key names so secret matching is style-agnostic."""
    n = (name or "").replace("-", "_")
    n = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", n)
    n = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", n)
    return n.lower()


def is_secret_key(name: str) -> bool:
    n = _canonical_key_name(name)
    if n in _SECRET_KEY_ALLOW:
        return False
    if n in _SENSITIVE_KEY_EXACT:
        return True
    return any(n.endswith(p) or n == p.lstrip("_") for p in _SECRET_KEY_PATTERNS)


def _scrub_value(key, value):
    """Mask secret-shaped leaves, recursing into nested dicts/lists so a secret
    stored under a non-secret parent key (e.g.
    ``{"email_account": {"smtp_password": "..."}}``) is still blanked. Only
    non-empty *string* values are blanked; presence is preserved."""
    if isinstance(value, dict):
        return {
            k: ("" if (is_secret_key(k) and isinstance(v, str) and v)
                else _scrub_value(k, v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub_value(key, item) for item in value]
    if is_secret_key(key) and isinstance(value, str) and value:
        return ""
    return value


def scrub_settings(settings: dict) -> dict:
    """Return a copy of ``settings`` with secret-shaped values masked (deep)."""
    if not isinstance(settings, dict):
        return {}
    return {k: _scrub_value(k, v) for k, v in (settings or {}).items()}
