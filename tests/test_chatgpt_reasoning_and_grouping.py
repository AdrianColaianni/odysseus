"""Tests for Model Picker Endpoint Grouping and ChatGPT Reasoning Effort Control.

Covers:
1. Endpoint/account grouping in modelPicker.js (keyed on endpoint_id, distinct routes, collapsible headers, search auto-expansion, keyboard nav).
2. ChatGPT reasoning effort (validation, catalog metadata, payload shaping with zero provider tools).
"""

from pathlib import Path

from src import chatgpt_subscription, llm_core
from tests.helpers.node import run_node_module

ROOT = Path(__file__).parents[1]


# ============================================================
# PART 1: FRONTEND MODEL PICKER GROUPING & UI
# ============================================================

def test_model_picker_endpoint_grouping_logic_in_node():
    """Verify in node that modelPicker groups models by endpoint_id and maintains distinct routes."""
    source = (ROOT / "static/js/modelPicker.js").read_text(encoding="utf-8")
    key_start = source.index("function _pickerModelKey(m)")
    key_end = source.index("// Shared keyboard nav")
    key_helper = source[key_start:key_end]

    group_start = source.index("const _endpointGroupNames =")
    group_end = source.index("const _collapsedProviders =")
    group_snippet = source[group_start:group_end]

    test_js = f"""
    const _PROVIDER_NAMES = {{}};
    const _PROVIDER_ALIAS = {{}};
    {key_helper}
    {group_snippet}

    const codex00_model = {{
        mid: 'gpt-5.5',
        display: 'gpt-5.5',
        endpointId: 'chatgpt-codex00',
        epName: 'ChatGPT · codex00',
        category: 'chatgpt_subscription',
        url: 'https://chatgpt.com/backend-api/codex'
    }};

    const codex01_model = {{
        mid: 'gpt-5.5',
        display: 'gpt-5.5',
        endpointId: 'chatgpt-codex01',
        epName: 'ChatGPT · codex01',
        category: 'chatgpt_subscription',
        url: 'https://chatgpt.com/backend-api/codex'
    }};

    const k0 = _pickerModelKey(codex00_model);
    const k1 = _pickerModelKey(codex01_model);
    if (k0 === k1) throw new Error('Same model across accounts must have distinct route keys');

    const g0 = _providerGroupKey(codex00_model);
    const g1 = _providerGroupKey(codex01_model);
    if (g0 === g1) throw new Error('Groups must be separate per account endpoint');

    const name0 = _providerGroupName(g0);
    const name1 = _providerGroupName(g1);
    if (name0 !== 'ChatGPT · codex00') throw new Error('Unexpected group name for codex00: ' + name0);
    if (name1 !== 'ChatGPT · codex01') throw new Error('Unexpected group name for codex01: ' + name1);

    console.log(JSON.stringify({{ k0, k1, g0, g1, name0, name1 }}));
    """
    res = run_node_module(test_js)
    assert res["k0"] != res["k1"]
    assert res["g0"] != res["g1"]
    assert res["name0"] == "ChatGPT · codex00"
    assert res["name1"] == "ChatGPT · codex01"


def test_model_picker_group_names_render_as_text():
    src = (ROOT / "static/js/modelPicker.js").read_text(encoding="utf-8")
    assert "nameSpan.textContent = _providerGroupName(provider)" in src


# ============================================================
# PART 2: BACKEND REASONING EFFORT CATALOG & VALIDATION
# ============================================================

def test_chatgpt_reasoning_effort_validation():
    """Test validate_reasoning_effort against catalog definitions."""
    # gpt-6-astra supports low, medium, high, xhigh, max, ultra
    assert chatgpt_subscription.validate_reasoning_effort("gpt-6-astra", "high") == "high"
    assert chatgpt_subscription.validate_reasoning_effort("gpt-6-astra", "LOW") == "low"
    assert chatgpt_subscription.validate_reasoning_effort("gpt-6-astra", "medium") == "medium"
    assert chatgpt_subscription.validate_reasoning_effort("gpt-6-astra", "xhigh") == "xhigh"
    assert chatgpt_subscription.validate_reasoning_effort("gpt-6-astra", "unsupported_level") is None
    assert chatgpt_subscription.validate_reasoning_effort("gpt-6-astra", "default") is None
    assert chatgpt_subscription.validate_reasoning_effort("gpt-6-astra", None) is None

    # Model metadata catalog
    meta_astra = chatgpt_subscription.get_chatgpt_model_metadata("gpt-6-astra")
    assert meta_astra["default_reasoning_level"] == "low"
    levels = meta_astra["supported_reasoning_levels"]
    assert "low" in levels
    assert "medium" in levels
    assert "high" in levels

    meta_55 = chatgpt_subscription.get_chatgpt_model_metadata("gpt-5.5")
    assert meta_55["default_reasoning_level"] == "medium"


def test_models_metadata_attached_for_chatgpt_catalog():
    """Verify get_chatgpt_model_metadata populates metadata for ChatGPT models."""
    from src.chatgpt_subscription import get_chatgpt_model_metadata
    models = ["gpt-6-astra", "gpt-5.5", "gpt-5.6-sol", "llama3"]
    models_metadata = {}
    for mid in models:
        meta = get_chatgpt_model_metadata(mid)
        if meta:
            models_metadata[mid] = meta
    assert "gpt-6-astra" in models_metadata
    assert "gpt-5.5" in models_metadata
    assert "gpt-5.6-sol" in models_metadata
    assert "llama3" not in models_metadata
    assert models_metadata["gpt-6-astra"]["default_reasoning_level"] == "low"
    assert "high" in models_metadata["gpt-6-astra"]["supported_reasoning_levels"]


def test_responses_payload_zero_tools_with_reasoning():
    """Verify that reasoning effort does NOT permit any native tool surfaces."""
    forbidden_tools = [
        {"type": "function", "function": {"name": "test"}},
        {"type": "web_search_preview"},
    ]
    payload = llm_core._build_chatgpt_responses_payload(
        model="gpt-6-astra",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.7,
        max_tokens=4096,
        stream=True,
        reasoning_effort="high",
        tools=forbidden_tools,
    )
    assert payload["reasoning"] == {"effort": "high"}
    assert "tools" not in payload
    assert "tool_choice" not in payload
    for k in llm_core.CHATGPT_FORBIDDEN_PAYLOAD_KEYS:
        assert k not in payload
    assert set(payload.keys()) <= llm_core.CHATGPT_ALLOWED_PAYLOAD_KEYS
