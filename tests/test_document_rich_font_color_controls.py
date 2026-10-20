"""Numeric font sizes and the shared app color picker in Rich Text."""


from tests.helpers.stylesheets import stylesheet_link_tags
from tests.helpers.node import run_node_module


def test_numeric_font_size_and_custom_colors_work_on_desktop_and_mobile():
    script = r"""
      import { chromium } from 'playwright';
      const browser = await chromium.launch({ headless: true });

      async function exercise(viewport, suffix) {
        const page = await browser.newPage({ viewport });
        await page.goto(`${process.env.ODYSSEUS_TEST_STATIC_ORIGIN}/static/js/documentStats.js`);
        await page.setContent('__ODY_STYLESHEETS__<div id="toast"></div><div id="chat-container"></div><div id="sidebar"></div>');
        await page.evaluate(async suffix => {
          const mod = await import(`/static/js/document.js?v=20260831richtexttools91&font-color=${suffix}`);
          mod.init('/api');
          mod.injectFreshDoc({
            id: `font-color-${suffix}`,
            title: 'Font and color',
            language: 'richtext',
            current_content: '<p>Font target</p><p>Color target</p><p>Highlight target</p>',
            version_count: 1,
          });
        }, suffix);
        await page.waitForSelector('#doc-email-richbody p');

        async function selectParagraph(index) {
          await page.evaluate(index => {
            const rich = document.querySelector('#doc-email-richbody');
            const paragraph = rich.querySelectorAll('p')[index];
            if (!paragraph) throw new Error(`Missing paragraph ${index}: ${rich.innerHTML}`);
            rich.focus();
            const range = document.createRange();
            range.selectNodeContents(paragraph);
            const selection = getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
          }, index);
        }

        async function openMenu(kind) {
          await page.locator(`[data-dd="${kind}"]`).focus();
          await page.keyboard.press('ArrowDown');
          await page.waitForSelector(`#doc-md-dd-menu[data-dd="${kind}"]`);
        }

        await selectParagraph(0);
        await openMenu('textsize');
        const initialSize = await page.locator('.rich-toolbar-range').evaluate(slider => ({
          value: slider.value,
          label: slider.getAttribute('aria-valuetext'),
          output: document.querySelector('.rich-toolbar-slider-value').value,
        }));
        await page.locator('.rich-toolbar-range').evaluate(slider => {
          slider.value = '5';
          slider.dispatchEvent(new Event('input', { bubbles: true }));
        });
        await page.waitForTimeout(60);
        const sizeState = await page.evaluate(() => ({
          html: document.querySelector('#doc-email-richbody p').innerHTML,
          icon: document.querySelector('.rich-font-size-icon').textContent,
          stored: document.querySelector('#doc-editor-textarea').value,
          output: document.querySelector('.rich-toolbar-slider-value').value,
          menuOpen: Boolean(document.querySelector('#doc-md-dd-menu[data-dd="textsize"]')),
        }));
        await page.keyboard.press('Escape');

        await selectParagraph(1);
        await openMenu('color');
        const colorInputState = await page.locator('.rich-toolbar-color-input').evaluate(input => ({
          type: input.type,
          attached: input.dataset.cpAttached,
          label: input.getAttribute('aria-label'),
        }));
        await page.locator('.rich-toolbar-color-input').click();
        await page.locator('.cp-hex').fill('#123456');
        await page.waitForTimeout(60);
        const colorState = await page.evaluate(() => ({
          html: document.querySelectorAll('#doc-email-richbody p')[1].innerHTML,
          menuOpen: Boolean(document.querySelector('#doc-md-dd-menu[data-dd="color"]')),
          pickerOpen: Boolean(document.querySelector('.cp-popover')),
        }));
        const pickerRect = await page.locator('.cp-popover').evaluate(popover => {
          const rect = popover.getBoundingClientRect();
          return { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom };
        });

        await page.mouse.click(4, viewport.height - 4);
        await selectParagraph(2);
        await openMenu('highlight');
        await page.locator('.rich-toolbar-color-input').click();
        await page.locator('.cp-hex').fill('#abcdef');
        await page.waitForTimeout(60);
        const highlightState = await page.evaluate(() => ({
          html: document.querySelectorAll('#doc-email-richbody p')[2].innerHTML,
          stored: document.querySelector('#doc-editor-textarea').value,
          pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        }));

        await page.close();
        return { initialSize, sizeState, colorInputState, colorState, pickerRect, highlightState };
      }

      const desktop = await exercise({ width: 900, height: 700 }, 'desktop');
      const mobile = await exercise({ width: 390, height: 844 }, 'mobile');
      console.log(JSON.stringify({ desktop, mobile }));
      await browser.close();
    """
    script = script.replace("__ODY_STYLESHEETS__", stylesheet_link_tags())
    data = run_node_module(script, timeout=120)

    for state in data.values():
        assert state["initialSize"] == {
            "value": "2",
            "label": "13 pixels",
            "output": "13",
        }
        assert state["sizeState"]["html"] == '<font size="5">Font target</font>'
        assert state["sizeState"]["icon"] == "24"
        assert state["sizeState"]["output"] == "24"
        assert state["sizeState"]["menuOpen"] is True
        assert '<font size="5">Font target</font>' in state["sizeState"]["stored"]
        assert state["colorInputState"] == {
            "type": "text",
            "attached": "1",
            "label": "Custom text color",
        }
        assert state["colorState"]["html"] == '<font color="#123456">Color target</font>'
        assert state["colorState"]["menuOpen"] is True
        assert state["colorState"]["pickerOpen"] is True
        assert state["pickerRect"]["left"] >= 8
        assert state["pickerRect"]["right"] <= 892
        assert state["pickerRect"]["top"] >= 8
        assert state["pickerRect"]["bottom"] <= 836
        assert "Highlight target" in state["highlightState"]["html"]
        assert "background-color" in state["highlightState"]["html"]
        assert "#abcdef" in state["highlightState"]["stored"] or "rgb(171, 205, 239)" in state["highlightState"]["stored"]
        assert state["highlightState"]["pageOverflow"] == 0
