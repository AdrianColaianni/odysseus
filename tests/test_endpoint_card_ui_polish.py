"""Endpoint card URL presentation in the admin panel."""

from pathlib import Path

from tests.helpers.node import run_node_module

_REPO = Path(__file__).resolve().parent.parent
_ADMIN_JS = _REPO / "static" / "js" / "admin.js"


class TestEndpointCardUrlPresentation:
    def test_should_display_endpoint_base_url_policy(self):
        js = f"""
          import fs from 'node:fs';
          import {{ isChatgptSubscriptionEndpoint }} from '{(_REPO / 'static' / 'js' / 'chatgptSubscriptionUsage.js').as_posix()}';
          const source = fs.readFileSync('{_ADMIN_JS.as_posix()}', 'utf8');
          const fnStart = source.indexOf('function shouldDisplayEndpointBaseUrl');
          const fnEnd = source.indexOf('// ChatGPT per-endpoint usage panel', fnStart);
          const fnCode = source.slice(fnStart, fnEnd);
          const fns = new Function('isChatgptSubscriptionEndpoint', 'esc',
            fnCode + '; return {{ shouldDisplayEndpointBaseUrl, isFeatherlessEndpoint, endpointDetailHtml }};'
          )(isChatgptSubscriptionEndpoint, x => String(x));

          const results = {{
            chatgpt: fns.shouldDisplayEndpointBaseUrl({{
              base_url: 'https://chatgpt.com/backend-api/codex',
              provider: 'chatgpt-subscription',
              provider_auth_id: 'auth-123'
            }}),
            featherless: fns.shouldDisplayEndpointBaseUrl({{
              base_url: 'https://api.featherless.ai/v1',
              name: 'Featherless.ai'
            }}),
            featherless_subdomain: fns.shouldDisplayEndpointBaseUrl({{
              base_url: 'https://eu.featherless.ai/v1'
            }}),
            generic: fns.shouldDisplayEndpointBaseUrl({{
              base_url: 'https://api.example.com/v1',
              name: 'Custom AI'
            }}),
            local: fns.shouldDisplayEndpointBaseUrl({{
              base_url: 'http://127.0.0.1:11434',
              name: 'Ollama'
            }}),
            null_ep: fns.shouldDisplayEndpointBaseUrl(null)
          }};
          console.log(JSON.stringify(results));
        """
        out = run_node_module(js)
        assert out["chatgpt"] is False, "ChatGPT raw transport URL must be hidden"
        assert out["featherless"] is False, "Featherless raw transport URL must be hidden"
        assert out["featherless_subdomain"] is False, "Featherless domain variants must be hidden"
        assert out["generic"] is True, "Generic custom endpoint URL must remain visible"
        assert out["local"] is True, "Local endpoint URL must remain visible"
        assert out["null_ep"] is False

    def test_endpoint_detail_html_suppresses_first_class_urls_and_keeps_others(self):
        js = f"""
          import fs from 'node:fs';
          import {{ isChatgptSubscriptionEndpoint }} from '{(_REPO / 'static' / 'js' / 'chatgptSubscriptionUsage.js').as_posix()}';
          const source = fs.readFileSync('{_ADMIN_JS.as_posix()}', 'utf8');
          const fnStart = source.indexOf('function shouldDisplayEndpointBaseUrl');
          const fnEnd = source.indexOf('// ChatGPT per-endpoint usage panel', fnStart);
          const fnCode = source.slice(fnStart, fnEnd);
          const fns = new Function('isChatgptSubscriptionEndpoint', 'esc',
            fnCode + '; return {{ shouldDisplayEndpointBaseUrl, isFeatherlessEndpoint, endpointDetailHtml }};'
          )(isChatgptSubscriptionEndpoint, x => String(x));

          const chatgptEp = {{
            base_url: 'https://chatgpt.com/backend-api/codex',
            provider: 'chatgpt-subscription',
            provider_auth_id: 'auth-1',
            has_key: false
          }};
          const featherlessEp = {{
            base_url: 'https://api.featherless.ai/v1',
            name: 'Featherless.ai',
            has_key: true,
            api_key_fingerprint: 'abcd1234'
          }};
          const genericEp = {{
            base_url: 'https://api.custom.com/v1',
            name: 'Custom',
            has_key: true,
            api_key_fingerprint: 'ef5678'
          }};
          const localEp = {{
            base_url: 'http://127.0.0.1:11434',
            name: 'Local',
            has_key: false
          }};

          const results = {{
            chatgptHtml: fns.endpointDetailHtml(chatgptEp, 'api'),
            featherlessHtml: fns.endpointDetailHtml(featherlessEp, 'api'),
            genericHtml: fns.endpointDetailHtml(genericEp, 'api'),
            localHtml: fns.endpointDetailHtml(localEp, 'local')
          }};
          console.log(JSON.stringify(results));
        """
        out = run_node_module(js)
        # ChatGPT card suppresses raw base URL and has no key, so no detail line
        assert "chatgpt.com" not in out["chatgptHtml"]
        assert out["chatgptHtml"] == ""

        # Featherless suppresses raw base URL but can display key fingerprint if present
        assert "api.featherless.ai" not in out["featherlessHtml"]
        assert "abcd1234" in out["featherlessHtml"]

        # Generic custom endpoint retains URL and key
        assert "https://api.custom.com/v1" in out["genericHtml"]
        assert "ef5678" in out["genericHtml"]

        # Local endpoint retains URL and copy affordance
        assert "http://127.0.0.1:11434" in out["localHtml"]
        assert 'data-adm-copy-url="http://127.0.0.1:11434"' in out["localHtml"]
        assert "admin-ep-copy-btn" in out["localHtml"]
