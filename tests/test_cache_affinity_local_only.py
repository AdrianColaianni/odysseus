"""llama.cpp slot-affinity fields must never reach cloud providers (#3793).

_apply_local_cache_affinity adds session_id + cache_prompt to outgoing
payloads for KV-cache slot affinity (#2927). The old gate treated any unknown
OpenAI-compatible host as self-hosted, so strict cloud APIs added as custom
endpoints (Mistral at api.mistral.ai) received the extra fields and rejected
every request with 422 extra_forbidden. Self-hosted now also requires the
endpoint to resolve as local: loopback/private/tailscale host, or endpoint
kind explicitly configured as "local".
"""
import src.llm_core as llm_core
import src.model_context as model_context


def _affinity_fields(url, monkeypatch, kind=None):
    monkeypatch.setattr(model_context, "_configured_endpoint_kind", lambda _u: kind)
    payload = {}
    llm_core._apply_local_cache_affinity(payload, url, "sess-123")
    return payload


AFFINITY = {"session_id": "sess-123", "cache_prompt": True}


def test_cloud_and_unknown_public_hosts_get_no_affinity_fields(monkeypatch):
    for url in [
        "https://api.mistral.ai/v1",  # the #3793 repro: Mistral rejects unknown body fields with 422
        "https://api.openai.com/v1",
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "https://llm.example-cloud.com/v1",
    ]:
        assert _affinity_fields(url, monkeypatch) == {}, url


def test_private_prefix_dns_host_gets_no_affinity_fields(monkeypatch):
    for url in [
        "https://10.example-cloud.com/v1",
        "https://172.16.example-cloud.com/v1",
        "https://192.168.example-cloud.com/v1",
    ]:
        assert _affinity_fields(url, monkeypatch) == {}, url


def test_loopback_and_lan_servers_get_affinity_fields(monkeypatch):
    for url in ["http://localhost:8080/v1", "http://192.168.1.50:8000/v1"]:
        assert _affinity_fields(url, monkeypatch) == AFFINITY, url


def test_public_host_with_local_kind_override_gets_affinity_fields(monkeypatch):
    # Escape hatch: a self-hosted llama.cpp exposed via a tunnel keeps the
    # slot-affinity hint when its endpoint kind is configured as "local".
    payload = _affinity_fields("https://my-llama.example.com/v1", monkeypatch, kind="local")
    assert payload == AFFINITY


def test_no_session_id_is_a_noop(monkeypatch):
    monkeypatch.setattr(model_context, "_configured_endpoint_kind", lambda _u: None)
    payload = {}
    llm_core._apply_local_cache_affinity(payload, "http://localhost:8080/v1", None)
    assert payload == {}


# Tailscale CGNAT boundaries (review finding on #3945): only 100.64.0.0/10 is
# Tailscale; the rest of 100.0.0.0/8 contains public ranges, and a strict
# provider addressed by one must not receive the llama.cpp extras.
def test_only_hosts_inside_cgnat_get_affinity_fields(monkeypatch):
    for host in ["100.63.255.255", "100.128.0.1"]:
        assert _affinity_fields(f"http://{host}/v1", monkeypatch) == {}, host
    for host in ["100.64.0.1", "100.127.255.254"]:
        assert _affinity_fields(f"http://{host}:8080/v1", monkeypatch) == AFFINITY, host
