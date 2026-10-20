"""Extended TLS trust for private-CA LLM providers (GigaChat, corporate gateways).

`LLM_CA_BUNDLE` names a PEM layered on top of the default trust store; there
is no verify=off knob. Only the shared client in src/llm_core.py and the
endpoint probes in routes/model_routes.py use `llm_verify()`; arbitrary-URL
fetches keep the httpx default. tests/test_tls_overrides_scope.py pins that
allowlist.
"""

import logging
import os
import ssl
from typing import Optional

logger = logging.getLogger(__name__)


_extra_bundle_path: Optional[str] = (os.environ.get("LLM_CA_BUNDLE") or "").strip() or None


def _build_ssl_context() -> Optional[ssl.SSLContext]:
    """Build an SSLContext that uses the default trust store and ALSO trusts
    the operator-supplied PEM bundle. Returns None when no extra bundle is
    configured, so callers fall through to httpx's default verify=True."""
    if not _extra_bundle_path:
        return None
    if not os.path.isfile(_extra_bundle_path):
        logger.warning(
            "LLM_CA_BUNDLE points at %r but the file does not exist; "
            "falling back to the default trust store.",
            _extra_bundle_path,
        )
        return None
    ctx = ssl.create_default_context()
    try:
        ctx.load_verify_locations(cafile=_extra_bundle_path)
    except (ssl.SSLError, OSError) as e:
        logger.warning(
            "LLM_CA_BUNDLE=%r failed to load (%s); falling back to the "
            "default trust store.",
            _extra_bundle_path, e,
        )
        return None
    logger.info(
        "Loaded extra CA bundle %r on top of the default trust store.",
        _extra_bundle_path,
    )
    return ctx


# Resolved once at import time. The httpx clients in src/llm_core.py are
# long-lived (process-wide), so editing LLM_CA_BUNDLE requires a restart —
# matching the existing semantics of LLM_HOST, SEARXNG_INSTANCE, etc.
_SHARED_SSL_CONTEXT: Optional[ssl.SSLContext] = _build_ssl_context()


def llm_verify():
    """Return the value to pass as `verify=` on httpx.get / httpx.Client /
    httpx.AsyncClient. Returns the extended-trust SSLContext when
    LLM_CA_BUNDLE is set and loaded; otherwise True (httpx default — system
    / certifi bundle, verification fully on)."""
    return _SHARED_SSL_CONTEXT if _SHARED_SSL_CONTEXT is not None else True
