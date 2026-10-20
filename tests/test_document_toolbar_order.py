"""Toolbar controls follow a predictable writing workflow."""

from tests.helpers.stylesheets import stylesheet_link_tags
from tests.helpers.node import run_node_module


def test_rich_toolbar_rendered_order_is_stable_on_desktop_and_mobile():
    script = r"""
      import { chromium } from 'playwright';
      const browser = await chromium.launch({ headless: true });

      async function inspect(viewport, suffix) {
        const page = await browser.newPage({ viewport });
        await page.goto(`${process.env.ODYSSEUS_TEST_STATIC_ORIGIN}/static/js/documentStats.js`);
        await page.setContent('__ODY_STYLESHEETS__<div id="toast"></div><div id="chat-container"></div><div id="sidebar"></div>');
        await page.evaluate(async suffix => {
          const mod = await import(`/static/js/document.js?v=20260831richtexttools91&toolbar-order=${suffix}`);
          mod.init('/api');
          mod.injectFreshDoc({
            id: `toolbar-order-${suffix}`,
            title: 'Toolbar order',
            language: 'richtext',
            current_content: '<p>Writing tools</p>',
            version_count: 1,
          });
        }, suffix);
        await page.waitForSelector('#doc-email-richbody p');

        const state = await page.evaluate(() => {
          const toolbar = document.querySelector('#md-toolbar-items');
          const controls = Array.from(toolbar.querySelectorAll(':scope > [data-toolbar-group]'));
          const key = item => item.dataset.dd || item.dataset.md || item.id;
          const visible = controls.filter(item => {
            const style = getComputedStyle(item);
            return !item.classList.contains('md-toolbar-sep')
              && style.display !== 'none' && style.visibility !== 'hidden';
          });
          return {
            all: controls.map(item => [item.dataset.toolbarGroup, key(item)]),
            visible: visible.map(key),
            separators: Array.from(toolbar.querySelectorAll(':scope > [data-toolbar-separator]'))
              .map(item => item.dataset.toolbarSeparator),
            toolbarOverflow: toolbar.scrollWidth > toolbar.clientWidth,
            pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          };
        });
        await page.close();
        return state;
      }

      const desktop = await inspect({ width: 900, height: 700 }, 'desktop');
      const mobile = await inspect({ width: 390, height: 844 }, 'mobile');
      console.log(JSON.stringify({ desktop, mobile }));
      await browser.close();
    """
    script = script.replace("__ODY_STYLESHEETS__", stylesheet_link_tags())
    data = run_node_module(script, timeout=120)

    expected_groups = [
        "display-size", "type", "inline-basic", "inline-color", "alignment", "spacing",
        "paragraph", "insert", "inline-rich", "document", "view",
    ]
    expected_separators = [
        "display-size-type",
        "type-inline-basic",
        "inline-basic-inline-color",
        "inline-color-alignment",
        "alignment-spacing",
        "spacing-paragraph",
        "paragraph-insert",
        "insert-inline-rich",
        "inline-rich-document",
        "document-view",
    ]
    for state in data.values():
        groups = [group for group, _ in state["all"]]
        assert list(dict.fromkeys(groups)) == expected_groups
        assert state["separators"] == expected_separators
        assert state["visible"][:6] == [
            "doc-ai-writing-btn",
            "heading",
            "font",
            "textsize",
            "bold",
            "italic",
        ]
        assert state["visible"].index("link") < state["visible"].index("list")
        assert state["visible"].index("md-toolbar-attach-btn") < state["visible"].index("list")
        assert state["visible"].index("md-toolbar-attach-btn") < state["visible"].index("doc-find-toolbar-btn")
        assert state["visible"].index("subscript") > state["visible"].index("md-toolbar-attach-btn")
        if "doc-outline-toolbar-btn" in state["visible"]:
            assert state["visible"].index("doc-ai-writing-btn") < state["visible"].index("doc-outline-toolbar-btn")
        assert state["pageOverflow"] == 0

    assert data["mobile"]["toolbarOverflow"] is True
