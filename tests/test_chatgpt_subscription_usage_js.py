"""Node-driven tests for the DOM-free ChatGPT usage card module and its admin handlers."""

import json
from pathlib import Path

from tests.helpers.node import run_node_module

_REPO = Path(__file__).resolve().parent.parent
_MODULE = _REPO / "static" / "js" / "chatgptSubscriptionUsage.js"


_PAYLOAD_A = {
    "available": True,
    "account": {"auth_id": "auth-a", "label": "codex00", "name": "ChatGPT · codex00"},
    "usage": {
        "auth_id": "auth-a", "plan_type": "plus", "account_id": "acct_a", "ordinary_usage_allowed": True,
        "rate_limit_reached_type": None, "fetched_at": 1_800_000_000, "cached": False,
        "limits": [
            {"limit_id": "codex", "limit_name": None, "normal_model_slug": None, "allowed": True, "limit_reached": False,
             "windows": [
                 {"kind": "primary", "name": "5H", "used_percent": 71, "remaining_percent": 29, "window_minutes": 300, "resets_at": 1_800_000_000 + 2 * 3600 + 14 * 60, "reset_after_seconds": 8040},
                 {"kind": "secondary", "name": "WEEK", "used_percent": 28, "remaining_percent": 72, "window_minutes": 10080, "resets_at": 1_800_000_000 + 4 * 86400 + 18 * 3600, "reset_after_seconds": 1},
             ]},
            {"limit_id": "codex_pro", "limit_name": "GPT-5.5 Pro", "normal_model_slug": "gpt-5.5-pro", "allowed": True, "limit_reached": False,
             "windows": [{"kind": "primary", "name": "1H", "used_percent": 5, "remaining_percent": 95, "window_minutes": 60, "resets_at": None, "reset_after_seconds": None}]},
            {"limit_id": "mystery", "limit_name": "Mystery", "normal_model_slug": None, "allowed": None, "limit_reached": None, "windows": []},
        ],
    },
}
_PAYLOAD_B = {
    "available": True,
    "account": {"auth_id": "auth-b", "label": "codex01", "name": "ChatGPT · codex01"},
    "usage": {"plan_type": "pro", "limits": [{"limit_id": "codex", "windows": [{"kind": "primary", "name": "5H", "used_percent": 100, "window_minutes": 300}]}]},
}


def test_view_model_normalizes_windows_and_reset_countdowns():
    js = f"""
      import {{ buildUsageViewModel }} from '{_MODULE.as_posix()}';
      const vm = buildUsageViewModel({json.dumps(_PAYLOAD_A)}, 1800000000);
      console.log(JSON.stringify(vm));
    """
    vm = run_node_module(js)
    assert vm["available"] is True
    assert vm["authId"] == "auth-a"
    assert vm["plan"] == "Plus"
    codex, pro, mystery = vm["limits"]
    assert codex["title"] == ""
    primary, secondary = codex["windows"]
    assert primary["name"] == "5H"
    assert primary["usedLabel"] == "71% used"
    assert primary["remainingLabel"] == "29% remaining"
    assert primary["resetLabel"] == "resets in 2h 14m"
    assert secondary["name"] == "WEEK"
    assert secondary["remainingLabel"] == "72% remaining"
    assert secondary["resetLabel"] == "resets in 4d 18h"
    # Additional bucket is kept with its own title/model; missing reset is not invented.
    assert pro["title"] == "GPT-5.5 Pro" and pro["modelSlug"] == "gpt-5.5-pro"
    assert pro["windows"][0]["resetLabel"] == ""
    assert mystery["windows"] == []


def test_view_model_is_defensive_about_bad_values():
    payload = {
        "available": True,
        "account": {"auth_id": "auth-x"},
        "usage": {"plan_type": 42, "limits": [
            {"limit_id": "codex", "windows": [{"kind": "primary", "used_percent": "abc", "window_minutes": "300", "resets_at": "soon"}, None, "str"]},
            "garbage",
            {"limit_id": "over", "windows": [{"used_percent": 250, "resets_at": 5}]},
        ]},
    }
    js = f"""
      import {{ buildUsageViewModel, renderUsageCardHtml }} from '{_MODULE.as_posix()}';
      const vm = buildUsageViewModel({json.dumps(payload)}, 10);
      const html = renderUsageCardHtml(vm, {{ endpointId: 'ep-x' }});
      console.log(JSON.stringify({{ vm, html }}));
    """
    out = run_node_module(js)
    vm = out["vm"]
    assert vm["plan"] == ""
    codex, over = vm["limits"]
    assert codex["windows"][0]["usedPercent"] is None
    assert codex["windows"][0]["usedLabel"] == "usage unknown"
    assert codex["windows"][0]["resetLabel"] == ""
    assert over["windows"][0]["usedPercent"] == 100
    assert over["windows"][0]["remainingPercent"] == 0
    assert over["windows"][0]["resetLabel"] == "resets now"
    assert 'aria-valuenow' not in out["html"].split('data-usage-limit="over"')[0]
    assert 'aria-valuenow="100"' in out["html"]


def test_unavailable_states_render_message_and_refresh_button():
    cases = {
        "reauth": {"available": False, "reason": "reauth", "reconnect_suggested": True, "account": {"auth_id": "auth-a"}},
        "rate_limited": {"available": False, "reason": "rate_limited", "account": {"auth_id": "auth-a"}},
        "timeout": {"available": False, "reason": "timeout", "account": {"auth_id": "auth-a"}},
        "malformed": None,
        "empty": {},
    }
    js = f"""
      import {{ buildUsageViewModel, renderUsageCardHtml }} from '{_MODULE.as_posix()}';
      const cases = {json.dumps(cases)};
      const out = {{}};
      for (const [k, payload] of Object.entries(cases)) {{
        const vm = buildUsageViewModel(payload, 0);
        out[k] = {{ vm, html: renderUsageCardHtml(vm, {{ endpointId: 'ep-a' }}) }};
      }}
      console.log(JSON.stringify(out));
    """
    out = run_node_module(js)
    assert out["reauth"]["vm"]["reconnectSuggested"] is True
    assert out["malformed"]["vm"]["available"] is False
    for case in out.values():
        assert "adm-chatgpt-usage-unavailable" in case["html"]
        assert 'data-adm-chatgpt-usage-refresh=' in case["html"]


def test_two_account_cards_render_independently_with_exact_ids():
    js = f"""
      import {{ buildUsageViewModel, renderUsageCardHtml }} from '{_MODULE.as_posix()}';
      const a = renderUsageCardHtml(buildUsageViewModel({json.dumps(_PAYLOAD_A)}, 1800000000), {{ endpointId: 'ep-a' }});
      const b = renderUsageCardHtml(buildUsageViewModel({json.dumps(_PAYLOAD_B)}, 1800000000), {{ endpointId: 'ep-b' }});
      console.log(JSON.stringify({{ a, b }}));
    """
    out = run_node_module(js)
    a, b = out["a"], out["b"]
    assert 'data-adm-chatgpt-usage="auth-a"' in a and 'data-adm-chatgpt-usage="auth-b"' in b
    assert 'data-adm-chatgpt-usage-refresh="auth-a" data-chatgpt-endpoint-id="ep-a"' in a
    assert 'data-adm-chatgpt-reconnect="auth-a" data-chatgpt-endpoint-id="ep-a"' in a
    assert 'data-adm-chatgpt-usage-refresh="auth-b" data-chatgpt-endpoint-id="ep-b"' in b
    assert 'data-adm-chatgpt-reconnect="auth-b" data-chatgpt-endpoint-id="ep-b"' in b
    assert "auth-b" not in a and "auth-a" not in b
    assert ">Plus<" in a and ">Pro<" in b
    assert "29% remaining" in a and "72% remaining" in a
    assert "resets in 2h 14m" in a and "resets in 4d 18h" in a
    assert "GPT-5.5 Pro" in a and "gpt-5.5-pro" in a
    assert "0% remaining" in b and "adm-chatgpt-usage-critical" in b
    assert a.count("adm-chatgpt-usage-row") == 3  # 5H + WEEK + additional bucket


def test_rendered_html_escapes_and_contains_no_credentials():
    payload = {
        "available": True,
        "account": {"auth_id": "auth-a", "label": "<img src=x onerror=alert(1)>"},
        "usage": {"plan_type": "<b>plus</b>", "limits": [{"limit_id": "codex", "limit_name": "<script>", "windows": [{"kind": "primary", "name": "<5H>", "used_percent": 10}]}],
                  "access_token": "SHOULD-NOT-BE-HERE"},
    }
    js = f"""
      import {{ buildUsageViewModel, renderUsageCardHtml }} from '{_MODULE.as_posix()}';
      const html = renderUsageCardHtml(buildUsageViewModel({json.dumps(payload)}, 0), {{ endpointId: 'ep-a' }});
      console.log(JSON.stringify({{ html }}));
    """
    html = run_node_module(js)["html"]
    assert "<script>" not in html and "<img" not in html and "<b>plus" not in html
    assert "&lt;5H&gt;" in html
    assert "SHOULD-NOT-BE-HERE" not in html
    assert "Bearer" not in html and "access_token" not in html and "refresh_token" not in html


def test_unknown_limits_without_windows_remain_visible():
    payload = {"available": True, "account": {"auth_id": "a"}, "usage": {
        "limits": [{"limit_id": "future", "limit_name": "Future <limit>", "windows": []}],
    }}
    out = run_node_module(f"""
      import {{ buildUsageViewModel, renderUsageCardHtml, formatResetIn }} from '{_MODULE.as_posix()}';
      console.log(JSON.stringify({{
        html: renderUsageCardHtml(buildUsageViewModel({json.dumps(payload)})),
        reset: formatResetIn(0, 100),
      }}));
    """)
    assert "Future &lt;limit&gt;" in out["html"]
    assert 'data-usage-limit="future"' in out["html"]
    assert out["reset"] == ""


def test_refresh_and_reconnect_handlers_target_only_the_clicked_account():
    # Execute the real admin handlers with small DOM doubles. This checks the
    # actions themselves, beyond checking renderer attributes or source text.
    out = run_node_module(f"""
      import fs from 'node:fs';
      import {{ buildUsageViewModel, renderUsageCardHtml }} from '{_MODULE.as_posix()}';
      const source = fs.readFileSync('{(_MODULE.parent / 'admin.js').as_posix()}', 'utf8');
      const start = source.indexOf('const _chatgptReconnectInflight');
      const end = source.indexOf('function initEndpointForm()', start);
      const urls = [], operations = [];
      const makeButton = () => ({{ dataset: {{}}, addEventListener(_, fn) {{ this.click = fn; }} }});
      function card(id) {{
        const refresh = makeButton(), reconnect = makeButton();
        for (const button of [refresh, reconnect]) button.dataset = {{
          admChatgptUsageRefresh: id, admChatgptReconnect: id, chatgptEndpointId: 'ep-' + id,
        }};
        return {{ innerHTML: '', refresh, reconnect, querySelector(sel) {{
          if (sel.includes('usage-refresh')) return refresh;
          if (sel.includes('chatgpt-reconnect')) return reconnect;
          return {{ replaceWith() {{}} }};
        }} }};
      }}
      const handlers = new Function('fetch', 'buildChatgptUsageViewModel', 'renderChatgptUsageCardHtml',
        'esc', 'runProviderDeviceFlow', 'document', 'loadEndpoints', 'setTimeout',
        source.slice(start, end) + '; return {{ load: _loadChatgptUsage }};'
      )(
        async url => {{ urls.push(url); return {{ ok: true, json: async () => ({{available: true, usage: {{limits: []}}}}) }}; }},
        buildUsageViewModel, renderUsageCardHtml, x => String(x),
        async (provider, options) => {{ operations.push(Object.fromEntries(options.formData)); return {{ status: 'authorized' }}; }},
        {{ createElement: () => ({{}}) }}, async () => {{}}, () => {{}}
      );
      const a = card('a'), b = card('b');
      await handlers.load(a, 'a', 'ep-a'); await handlers.load(b, 'b', 'ep-b');
      const before = b.innerHTML;
      await a.refresh.click({{stopPropagation() {{}}}});
      await a.reconnect.click({{stopPropagation() {{}}}});
      console.log(JSON.stringify({{ urls, operations, bUnchanged: b.innerHTML === before }}));
    """)
    assert out["urls"] == [
        "/api/chatgpt-subscription/accounts/a/usage",
        "/api/chatgpt-subscription/accounts/b/usage",
        "/api/chatgpt-subscription/accounts/a/usage?refresh=1",
    ]
    assert out["operations"] == [{"reconnect_auth_id": "a", "reconnect_endpoint_id": "ep-a"}]
    assert out["bUnchanged"] is True


def test_chatgpt_usage_collapsible_behavior():
    out = run_node_module(f"""
      import fs from 'node:fs';
      import {{ buildUsageViewModel, renderUsageCardHtml }} from '{_MODULE.as_posix()}';
      const source = fs.readFileSync('{(_MODULE.parent / 'admin.js').as_posix()}', 'utf8');

      // Extract localStorage helpers
      const helperStart = source.indexOf('const CHATGPT_USAGE_EXPANDED_KEY');
      const helperEnd = source.indexOf('async function loadEndpoints()');
      const helpersCode = source.slice(helperStart, helperEnd);

      // Extract _loadChatgptUsage and _reconnectChatgptAccount
      const handlerStart = source.indexOf('const _chatgptReconnectInflight');
      const handlerEnd = source.indexOf('function initEndpointForm()', handlerStart);
      const handlersCode = source.slice(handlerStart, handlerEnd);

      // Simulated localStorage
      const storage = {{}};
      const localStorage = {{
        getItem: k => storage[k] || null,
        setItem: (k, v) => {{ storage[k] = String(v); }},
        removeItem: k => {{ delete storage[k]; }},
      }};

      const helpers = new Function('localStorage', helpersCode + '; return {{ _loadExpandedUsageEndpoints, _saveExpandedUsageEndpoints, _isChatgptUsageExpanded, _setChatgptUsageExpanded }};')(localStorage);

      // Verify localStorage persistence format: IDs only, no tokens/secrets
      assertDefaultCollapsed: {{
        if (helpers._isChatgptUsageExpanded('ep-a', 'auth-a') !== false) throw new Error('should be collapsed by default');
      }}
      helpers._setChatgptUsageExpanded('ep-a', 'auth-a', true);
      const stored = JSON.parse(storage['odysseus-chatgpt-usage-expanded']);
      if (!stored.includes('ep-a') || !stored.includes('auth-a')) throw new Error('storage should have ep and auth ids');
      if (storage['odysseus-chatgpt-usage-expanded'].includes('Bearer') || storage['odysseus-chatgpt-usage-expanded'].includes('secret')) throw new Error('storage has credentials');
      if (helpers._isChatgptUsageExpanded('ep-a', 'auth-a') !== true) throw new Error('should be expanded');
      if (helpers._isChatgptUsageExpanded('ep-b', 'auth-b') !== false) throw new Error('b should remain collapsed');
      helpers._setChatgptUsageExpanded('ep-a', 'auth-a', false);
      if (helpers._isChatgptUsageExpanded('ep-a', 'auth-a') !== false) throw new Error('should be collapsed after removal');

      // Now verify toggle and lazy loading interactions
      const urls = [], operations = [];
      const makeEl = (tag = 'div') => ({{
        tagName: tag,
        classList: new Set(),
        style: {{}},
        dataset: {{}},
        attributes: {{}},
        setAttribute(k, v) {{ this.attributes[k] = String(v); }},
        getAttribute(k) {{ return this.attributes[k]; }},
        addEventListener(_, fn) {{ this.click = fn; }},
        querySelector() {{ return null; }},
      }});

      function createAccountRow(id) {{
        const row = makeEl('div');
        row.classList.add('admin-user-row');

        const chevron = makeEl('span');
        chevron.textContent = '▾';

        const toggleBtn = makeEl('button');
        toggleBtn.dataset = {{ admChatgptUsageToggle: id, chatgptEndpointId: 'ep-' + id }};
        toggleBtn.setAttribute('aria-expanded', 'false');
        toggleBtn.querySelector = sel => sel.includes('chevron') ? chevron : null;
        toggleBtn.closest = sel => sel.includes('admin-user-row') ? row : null;

        const reconnectBtn = makeEl('button');
        reconnectBtn.dataset = {{ admChatgptReconnect: id, chatgptEndpointId: 'ep-' + id }};
        reconnectBtn.closest = sel => sel.includes('admin-user-row') ? row : null;

        const host = makeEl('div');
        host.classList.add('adm-chatgpt-usage-host', 'hidden');
        host.style.display = 'none';
        host.dataset = {{ admChatgptUsageHost: id, chatgptEndpointId: 'ep-' + id }};

        row.querySelector = sel => {{
          if (sel.includes('adm-chatgpt-usage-host')) return host;
          if (sel.includes('adm-chatgpt-usage-toggle')) return toggleBtn;
          if (sel.includes('adm-chatgpt-reconnect')) return reconnectBtn;
          return null;
        }};

        return {{ row, toggleBtn, reconnectBtn, host, chevron }};
      }}

      const handlers = new Function('fetch', 'buildChatgptUsageViewModel', 'renderChatgptUsageCardHtml',
        'esc', 'runProviderDeviceFlow', 'document', 'loadEndpoints', 'setTimeout',
        handlersCode + '; return {{ load: _loadChatgptUsage, reconnect: _reconnectChatgptAccount }};'
      )(
        async url => {{ urls.push(url); return {{ ok: true, json: async () => ({{available: true, usage: {{limits: []}}}}) }}; }},
        buildUsageViewModel, renderUsageCardHtml, x => String(x),
        async (provider, options) => {{ operations.push(Object.fromEntries(options.formData)); return {{ status: 'authorized' }}; }},
        {{ createElement: () => ({{ replaceWith() {{}} }}) }}, async () => {{}}, () => {{}}
      );

      const a = createAccountRow('auth-a');
      const b = createAccountRow('auth-b');

      // Wire toggle listener like in admin.js
      function wireToggle(rowObj) {{
        rowObj.toggleBtn.addEventListener('click', async () => {{
          const epId = rowObj.toggleBtn.dataset.chatgptEndpointId;
          const authId = rowObj.toggleBtn.dataset.admChatgptUsageToggle;
          const host = rowObj.host;
          const isHidden = host.classList.has('hidden') || host.style.display === 'none';
          if (isHidden) {{
            host.classList.delete('hidden');
            host.style.display = '';
            rowObj.toggleBtn.setAttribute('aria-expanded', 'true');
            rowObj.chevron.textContent = '▴';
            helpers._setChatgptUsageExpanded(epId, authId, true);
            if (!host.dataset.usageLoaded) {{
              await handlers.load(host, authId, epId);
            }}
          }} else {{
            host.classList.add('hidden');
            host.style.display = 'none';
            rowObj.toggleBtn.setAttribute('aria-expanded', 'false');
            rowObj.chevron.textContent = '▾';
            helpers._setChatgptUsageExpanded(epId, authId, false);
          }}
        }});
      }}
      wireToggle(a);
      wireToggle(b);

      // Step 1: Initial state - 0 fetches before expand
      const initialFetches = urls.length;

      // Step 2: Expand A -> fetches A only, updates aria-expanded and chevron
      await a.toggleBtn.click();
      const aExpandedFetches = urls.slice();
      const bStateAfterAExpand = {{
        hidden: b.host.style.display === 'none',
        ariaExpanded: b.toggleBtn.getAttribute('aria-expanded'),
        chevron: b.chevron.textContent,
      }};

      // Step 3: Collapse A -> 0 extra fetches, updates aria-expanded and chevron
      await a.toggleBtn.click();
      const aCollapsedFetches = urls.slice();

      // Step 4: Re-open A -> 0 extra fetches (cached DOM reused)
      await a.toggleBtn.click();
      const aReopenedFetches = urls.slice();

      // Step 5: Refresh A -> forces fetch with ?refresh=1
      await handlers.load(a.host, 'auth-a', 'ep-auth-a', {{ refresh: true }});
      const refreshFetches = urls.slice();

      console.log(JSON.stringify({{
        initialFetches,
        aExpandedFetches,
        bStateAfterAExpand,
        aCollapsedFetches,
        aReopenedFetches,
        refreshFetches,
        aFinalAriaExpanded: a.toggleBtn.getAttribute('aria-expanded'),
        aFinalChevron: a.chevron.textContent,
      }}));
    """)

    assert out["initialFetches"] == 0
    assert out["aExpandedFetches"] == ["/api/chatgpt-subscription/accounts/auth-a/usage"]
    assert out["bStateAfterAExpand"] == {"hidden": True, "ariaExpanded": "false", "chevron": "▾"}
    assert len(out["aCollapsedFetches"]) == 1  # No extra fetch on collapse
    assert len(out["aReopenedFetches"]) == 1   # No extra fetch on reopen (cached DOM reused)
    assert out["refreshFetches"] == [
        "/api/chatgpt-subscription/accounts/auth-a/usage",
        "/api/chatgpt-subscription/accounts/auth-a/usage?refresh=1",
    ]
    assert out["aFinalAriaExpanded"] == "true"
    assert out["aFinalChevron"] == "▴"


def test_chatgpt_usage_collapsible_reconnect_and_failure():
    out = run_node_module(f"""
      import fs from 'node:fs';
      import {{ buildUsageViewModel, renderUsageCardHtml }} from '{_MODULE.as_posix()}';
      const source = fs.readFileSync('{(_MODULE.parent / 'admin.js').as_posix()}', 'utf8');

      const handlerStart = source.indexOf('const _chatgptReconnectInflight');
      const handlerEnd = source.indexOf('function initEndpointForm()', handlerStart);
      const handlersCode = source.slice(handlerStart, handlerEnd);

      const urls = [], operations = [];
      const makeEl = (tag = 'div') => ({{
        tagName: tag,
        classList: new Set(),
        style: {{}},
        dataset: {{}},
        attributes: {{}},
        appendChild() {{}},
        setAttribute(k, v) {{ this.attributes[k] = String(v); }},
        getAttribute(k) {{ return this.attributes[k]; }},
        addEventListener(_, fn) {{ this.click = fn; }},
        querySelector() {{ return null; }},
      }});

      function createAccountRow(id) {{
        const row = makeEl('div');
        const chevron = makeEl('span');
        chevron.textContent = '▾';

        const toggleBtn = makeEl('button');
        toggleBtn.dataset = {{ admChatgptUsageToggle: id, chatgptEndpointId: 'ep-' + id }};
        toggleBtn.setAttribute('aria-expanded', 'false');
        toggleBtn.querySelector = sel => sel.includes('chevron') ? chevron : null;
        toggleBtn.closest = sel => sel.includes('admin-user-row') ? row : null;

        const reconnectBtn = makeEl('button');
        reconnectBtn.dataset = {{ admChatgptReconnect: id, chatgptEndpointId: 'ep-' + id }};
        reconnectBtn.closest = sel => sel.includes('admin-user-row') ? row : null;

        const host = makeEl('div');
        host.classList.add('adm-chatgpt-usage-host', 'hidden');
        host.style.display = 'none';
        host.dataset = {{ admChatgptUsageHost: id, chatgptEndpointId: 'ep-' + id }};

        row.querySelector = sel => {{
          if (sel.includes('adm-chatgpt-usage-host')) return host;
          if (sel.includes('adm-chatgpt-usage-toggle')) return toggleBtn;
          if (sel.includes('adm-chatgpt-reconnect')) return reconnectBtn;
          return null;
        }};

        return {{ row, toggleBtn, reconnectBtn, host, chevron }};
      }}

      let shouldFail = false;
      const handlers = new Function('fetch', 'buildChatgptUsageViewModel', 'renderChatgptUsageCardHtml',
        'esc', 'runProviderDeviceFlow', 'document', 'loadEndpoints', 'setTimeout',
        handlersCode + '; return {{ load: _loadChatgptUsage, reconnect: _reconnectChatgptAccount }};'
      )(
        async url => {{
          urls.push(url);
          if (shouldFail) throw new Error('network down');
          return {{ ok: true, json: async () => ({{ available: true, usage: {{ limits: [] }} }}) }};
        }},
        buildUsageViewModel, renderUsageCardHtml, x => String(x),
        async (provider, options) => {{ operations.push(Object.fromEntries(options.formData)); return {{ status: 'authorized' }}; }},
        {{ createElement: () => ({{ replaceWith() {{}} }}) }}, async () => {{}}, () => {{}}
      );

      const b = createAccountRow('auth-b');

      // Wire reconnect listener like in admin.js
      b.reconnectBtn.addEventListener('click', async () => {{
        const epId = b.reconnectBtn.dataset.chatgptEndpointId;
        const authId = b.reconnectBtn.dataset.admChatgptReconnect;
        const host = b.host;
        host.classList.delete('hidden');
        host.style.display = '';
        b.toggleBtn.setAttribute('aria-expanded', 'true');
        b.chevron.textContent = '▴';
        await handlers.reconnect(host, authId, epId);
      }});

      // Reconnect when collapsed -> unhides host, updates aria-expanded, runs reconnect for B
      await b.reconnectBtn.click();
      const bReconnectState = {{
        hostHidden: b.host.style.display === 'none',
        ariaExpanded: b.toggleBtn.getAttribute('aria-expanded'),
        chevron: b.chevron.textContent,
        operations: operations.slice(),
      }};

      // Failure state test
      shouldFail = true;
      const failHost = makeEl('div');
      failHost.dataset = {{ admChatgptUsageHost: 'auth-f', chatgptEndpointId: 'ep-f' }};
      await handlers.load(failHost, 'auth-f', 'ep-f');
      const failHtml = failHost.innerHTML;

      console.log(JSON.stringify({{
        bReconnectState,
        failHasUnavailable: failHtml.includes('adm-chatgpt-usage-unavailable'),
        failHasRefresh: failHtml.includes('data-adm-chatgpt-usage-refresh'),
        failNoDuplicateReconnect: !failHtml.includes('data-adm-chatgpt-reconnect'),
      }}));
    """)

    assert out["bReconnectState"]["hostHidden"] is False
    assert out["bReconnectState"]["ariaExpanded"] == "true"
    assert out["bReconnectState"]["chevron"] == "▴"
    assert out["bReconnectState"]["operations"] == [{"reconnect_auth_id": "auth-b", "reconnect_endpoint_id": "ep-auth-b"}]
    assert out["failHasUnavailable"] is True
    assert out["failHasRefresh"] is True
    assert out["failNoDuplicateReconnect"] is True
