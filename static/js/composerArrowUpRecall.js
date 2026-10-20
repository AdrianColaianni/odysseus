/**
 * ArrowUp on the composer recalls previous user messages from this chat.
 */

/**
 * User bubbles in the active chat surface (#chat-history), newest first, using
 * dataset.raw (same source as resend/regenerate in chat.js).
 *
 * @param {Document | Element} [root=document]
 * @returns {string[]}
 */
export function getUserMessagesFromChatHistory(root = document) {
  const chatBox =
    root && root.id === 'chat-history' && typeof root.querySelectorAll === 'function'
      ? root
      : (root.getElementById ? root.getElementById('chat-history') : null);
  if (!chatBox) return [];

  const users = chatBox.querySelectorAll('.msg-user');
  const prompts = [];
  for (let i = users.length - 1; i >= 0; i--) {
    const msg = users[i];
    const bodyEl = msg.querySelector('.body');
    const text = msg.dataset?.raw || (bodyEl ? bodyEl.textContent : '') || '';
    if (text) prompts.push(text);
  }
  return prompts;
}

/**
 * Last user bubble in the active chat surface (#chat-history).
 *
 * @param {Document | Element} [root=document]
 * @returns {string}
 */
export function getLastUserMessageFromChatHistory(root = document) {
  return getUserMessagesFromChatHistory(root)[0] || '';
}

/**
 * @param {HTMLTextAreaElement} composer
 * @param {() => string|string[]} getUserMessages
 * @param {{ autoResize?: (el: HTMLTextAreaElement) => void }} [options]
 * @returns {boolean} true when wired (or already wired)
 */
export function wireArrowUpRecall(composer, getUserMessages, options = {}) {
  if (!composer) return false;
  if (composer._arrowUpRecallWired) return true;
  composer._arrowUpRecallWired = true;

  const { autoResize } = options;
  let recallIndex = -1;
  let applyingRecall = false;
  let lastRecalledValue = '';
  let recallHistory = [];

  const readHistory = () => {
    const value = getUserMessages?.();
    if (Array.isArray(value)) return value.filter(Boolean);
    return value ? [value] : [];
  };
  const norm = (value) => String(value || '').replace(/\r\n/g, '\n').trimEnd();
  composer.addEventListener('input', () => {
    if (applyingRecall) return;
    if (norm(composer.value) === norm(lastRecalledValue)) return;
    recallIndex = -1;
    lastRecalledValue = '';
    recallHistory = [];
    delete composer.dataset.odysseusRecallIndex;
  });

  composer.addEventListener('keydown', (e) => {
    // Prompt history: ArrowUp walks older, ArrowDown walks newer/back to blank.
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    if (e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.isComposing) return;
    if (typeof window !== 'undefined' && window._ghostAutocomplete?.isActive?.()) return;

    const freshHistory = readHistory();
    const history = freshHistory.length ? freshHistory : recallHistory;
    if (!history.length) return;

    const rawCurrentValue = String(composer.value || '');
    const currentValue = norm(rawCurrentValue);
    const recalledValue = norm(lastRecalledValue);
    let currentIndex = rawCurrentValue === ''
      ? -1
      : history.findIndex((item) => norm(item) === currentValue);
    if (currentIndex < 0 && currentValue && currentValue === recalledValue) {
      currentIndex = recallIndex;
    }
    if (currentIndex < 0 && currentValue) {
      const markedIndex = Number(composer.dataset.odysseusRecallIndex);
      if (Number.isInteger(markedIndex) && markedIndex >= 0 && markedIndex < history.length) {
        currentIndex = markedIndex;
      }
    }
    if (rawCurrentValue !== '' && currentIndex < 0) return;
    e.preventDefault();
    e.stopPropagation?.();
    e.stopImmediatePropagation?.();
    if (e.key === 'ArrowDown') {
      if (currentIndex < 0) return;
      const nextIndex = currentIndex - 1;
      if (nextIndex < 0) {
        recallIndex = -1;
        recallHistory = history;
        applyingRecall = true;
        lastRecalledValue = '';
        delete composer.dataset.odysseusRecallIndex;
        composer.value = '';
        composer.selectionStart = composer.selectionEnd = 0;
        if (autoResize) autoResize(composer);
        setTimeout(() => { applyingRecall = false; }, 0);
        return;
      }
      const recalled = history[nextIndex];
      recallIndex = nextIndex;
      recallHistory = history;
      applyingRecall = true;
      lastRecalledValue = recalled;
      composer.dataset.odysseusRecallIndex = String(nextIndex);
      composer.value = recalled;
      composer.selectionStart = composer.selectionEnd = recalled.length;
      if (autoResize) autoResize(composer);
      setTimeout(() => { applyingRecall = false; }, 0);
      return;
    }

    // ArrowUp walks older prompts. An unmatched draft already returned above,
    // so reaching here means the composer is empty or holds a recalled prompt
    // — the caret-navigation case is never hijacked.
    const nextIndex = currentIndex >= 0 ? Math.min(currentIndex + 1, history.length - 1) : 0;
    const recalled = history[nextIndex];
    if (!recalled) return;

    recallIndex = nextIndex;
    recallHistory = history;
    applyingRecall = true;
    lastRecalledValue = recalled;
    composer.dataset.odysseusRecallIndex = String(nextIndex);
    composer.value = recalled;
    composer.selectionStart = composer.selectionEnd = recalled.length;
    if (autoResize) autoResize(composer);
    setTimeout(() => { applyingRecall = false; }, 0);
  }, true);

  return true;
}
