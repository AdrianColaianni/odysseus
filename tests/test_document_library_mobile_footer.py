"""Mobile Documents-library footer remains focused and explicit."""

from tests.helpers.stylesheets import stylesheet_link_tags
from tests.helpers.node import run_node_module


def test_mobile_open_in_new_chat_copies_to_materialized_session():
    script = r"""
      import { chromium } from 'playwright';
      const browser = await chromium.launch({ headless: true });
      const page = await browser.newPage({ viewport: { width: 390, height: 844 }, hasTouch: true });
      await page.goto(`${process.env.ODYSSEUS_TEST_STATIC_ORIGIN}/static/js/documentStats.js`);
      await page.setContent('__ODY_STYLESHEETS__<div id="toast"></div><div id="chat-container"></div><div id="sidebar"></div>');
      const state = await page.evaluate(async () => {
        let currentSession = 'current-chat';
        let createDirectCalls = 0;
        let postedBody = null;
        const originalFetch = window.fetch;
        window.fetch = async (input, init = {}) => {
          const url = String(input);
          const response = value => new Response(JSON.stringify(value), {
            status: 200, headers: { 'Content-Type': 'application/json' },
          });
          if (url.includes('/api/documents/library')) return response({
            documents: [{ id: 'source-doc', title: 'Source', language: 'markdown', preview: 'Preview', session_id: 'original-chat' }],
            total: 1, languages: { markdown: 1 }, session_count: 1,
          });
          if (url.endsWith('/api/document/source-doc')) return response({
            id: 'source-doc', title: 'Source', language: 'markdown', current_content: '# Source', session_id: 'original-chat',
          });
          if (url.endsWith('/api/document') && init.method === 'POST') {
            postedBody = JSON.parse(init.body);
            return response({ id: 'copied-doc', language: 'markdown', current_content: '# Source', session_id: postedBody.session_id });
          }
          if (url.includes('/api/sessions') || url.includes('/api/history')) return response([]);
          return originalFetch(input, init);
        };

        const sessions = (await import('/static/js/sessions.js')).default;
        sessions.getCurrentSessionId = () => currentSession;
        sessions.getCurrentModel = () => 'model';
        sessions.getSessions = () => [{ id: 'current-chat', endpoint_url: '/chat', model: 'model', endpoint_id: 'endpoint' }];
        sessions.createDirectChat = () => { createDirectCalls += 1; currentSession = null; };
        sessions.materializePendingSession = async () => { currentSession = 'new-chat'; return true; };

        const library = await import('/static/js/documentLibrary.js?v=20260831richtexttools91&new-chat-test=1');
        library.initLibrary({
          apiBase: '', esc: String, getDocs: () => new Map(), isOpen: () => false,
          createDocument() {}, newDocument() {}, async loadDocument() {}, prepareDocumentOpen() {},
          switchToDoc() {}, openPanel() {}, addDocToTabs() {}, syncDocIndicator() {},
        });
        library.openLibrary();
        await new Promise(resolve => setTimeout(resolve, 120));
        document.querySelector('#doclib-grid .doclib-card').click();
        await new Promise(resolve => setTimeout(resolve, 180));
        document.querySelector('.doclib-expanded-open-btn').click();
        await new Promise(resolve => setTimeout(resolve, 30));
        Array.from(document.querySelectorAll('._lib-dd .dropdown-item-compact'))
          .find(item => item.textContent.includes('Open in new chat')).click();
        for (let i = 0; i < 20 && !postedBody; i += 1) await new Promise(resolve => setTimeout(resolve, 20));
        return { createDirectCalls, currentSession, postedBody };
      });
      console.log(JSON.stringify(state));
      await browser.close();
    """
    script = script.replace("__ODY_STYLESHEETS__", stylesheet_link_tags())
    data = run_node_module(script, timeout=120)
    assert data["createDirectCalls"] == 1
    assert data["currentSession"] == "new-chat"
    assert data["postedBody"]["session_id"] == "new-chat"
