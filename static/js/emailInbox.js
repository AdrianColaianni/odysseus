// Sidebar email section: unread dot, compose, and reply drafts opened from the library.

import sessionModule from './sessions.js';
import { initEmailLibrary, openEmailLibrary, isOpen as isLibOpen, prewarmEmailLibrary, prewarmUnreadEmails } from './emailLibrary.js?v=20260915trashmove2';
import * as Modals from './modalManager.js';
import { applyEdgeDock } from './modalSnap.js';
import { buildReplyAllCc, extractEmail } from './emailLibrary/replyRecipients.js';
import { emailApiUrl } from './emailShared.js';
import { jsonRequest } from './shared/http.js';
import { showError, showToast } from './ui.js?v=20260916largetoolscroll1';

const API_BASE = window.location.origin;

const _replySeparator = '---------- Previous message ----------';

function _splitEmailAddresses(raw) {
  return (typeof raw === 'string' ? raw : '')
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);
}

function _isMyEmailAddress(addr, myAddresses) {
  const email = extractEmail(addr);
  if (!email) return false;
  return new Set((myAddresses || []).map(a => String(a || '').trim().toLowerCase()).filter(Boolean)).has(email);
}

function _withoutMyAddresses(raw, myAddresses) {
  return _splitEmailAddresses(raw).filter(addr => !_isMyEmailAddress(addr, myAddresses));
}

function _cleanAiReplyText(text) {
  if (!text) return '';
  let t = String(text);
  const open = /<<<\s*(?:REPLY|SUMMARY|OUTPUT)\s*>>+/i;
  const close = /<<<\s*END\s*>>+/i;
  const m = open.exec(t);
  if (m) {
    const rest = t.slice(m.index + m[0].length);
    const c = close.exec(rest);
    t = c ? rest.slice(0, c.index) : rest;
  }
  return t
    .replace(/<<<\s*(?:REPLY|SUMMARY|OUTPUT)\s*>>+/gi, '')
    .replace(/<<<\s*END\s*>>+/gi, '')
    .replace(/<\/?\|(?:assistant|assistan|user|system|tool)\|>?|<\/\|end\|>?/gi, '')
    .trim();
}

let _currentFolder = 'INBOX';
let _docModule = null;
let _openEmailRequestSeq = 0;

export function init(documentModule) {
  _docModule = documentModule;
  _bindEvents();
  // Init the library popup with a callback to open emails
  initEmailLibrary({
    documentModule,
    onEmailClick: async (opts) => {
      // Reply / AI Reply / Compose open a draft in the doc editor.
      //  - Desktop: dock the email to the LEFT so it stays visible beside the
      //    reply draft (which opens on the right) — read-while-you-reply.
      //  - Mobile: there's no room for a split, so minimize the email modal;
      //    the draft comes to the front and the inbox stays a tap away as a
      //    minimized chip.
      // Never call closeEmailLibrary() here — that destroys state.
      try {
        if (Modals.isRegistered('email-lib-modal')) {
          const emailModal = document.getElementById('email-lib-modal');
          if (window.innerWidth > 768 && emailModal && !emailModal.classList.contains('hidden')) {
            applyEdgeDock(emailModal, 'left');
          }
          // Mobile: no pre-mount here; the load path mounts the pane once the doc is ready.
        }
      } catch (_) {}
      if (opts.compose) { _composeNew(); return; }
      if (opts.email) {
        return await _openEmail(opts.email, opts.emailData, opts.mode || 'reply', opts.noteHint || '', '', opts.mailboxContext || null);
      }
      return false;
    },
  });
  prewarmEmailLibrary({ delay: 1800 });
  _watchDocOpenToReDockEmail();
}

export async function openReplyDraft(uid, folder = 'INBOX', mode = 'reply', prefilledBody = '') {
  if (!uid) return;
  const previousFolder = _currentFolder;
  _currentFolder = folder || 'INBOX';
  try {
    await _openEmail({ uid: String(uid), subject: '' }, null, mode || 'reply', '', prefilledBody || '');
  } finally {
    _currentFolder = previousFolder || _currentFolder;
  }
}

function _bringEmailReplyDraftToFrontOnMobile() {
  if (window.innerWidth > 768) return;
  document.body.classList.remove('email-front', 'email-doc-split-active');
  document.documentElement.style.removeProperty('--email-doc-split-left-x');
  document.documentElement.style.removeProperty('--email-doc-split-email-w');
  document.documentElement.style.removeProperty('--email-doc-split-right-x');
  // Keep the email sheet visible behind the reply document on mobile. The
  // document panel sits above it via the normal doc-view z-index rules, and
  // swiping the document down minimizes it to a chip to reveal the email.
  document.querySelectorAll('#email-lib-modal, .modal[id^="email-reader-"]').forEach(modal => {
    modal.classList.remove('email-snap-left', 'modal-left-docked', 'modal-right-docked');
    modal.style.removeProperty('z-index');
  });
  const docPane = document.getElementById('doc-editor-pane');
  if (docPane) docPane.style.setProperty('z-index', '10010', 'important');
}

function _focusMobileReplyBody() {
  if (window.innerWidth > 768 || !_docModule?.focusEmailReplyBody) return;
  // injectFreshDoc switches tabs on the next frame; wait for that render
  // before focusing so the rich body exists and the caret lands in the reply,
  // not in the previous document.
  requestAnimationFrame(() => requestAnimationFrame(() => {
    _docModule.focusEmailReplyBody();
  }));
}

// When the document editor pane opens (body.doc-view turns on), make sure the
// email modal is on the LEFT — even if it was previously docked RIGHT or
// floating — so the email and the doc always end up side-by-side. The actual
// width math lives in modalSnap.js (`_anchorLeftDock` shrinks the email when
// the doc is rendered to the right).
let _docOpenObs = null;
function _watchDocOpenToReDockEmail() {
  if (_docOpenObs) return;
  if (typeof MutationObserver === 'undefined') return;
  let last = document.body.classList.contains('doc-view');
  _docOpenObs = new MutationObserver(() => {
    const cur = document.body.classList.contains('doc-view');
    if (cur && !last) {
      if (window.innerWidth > 768) {
        const emailModal = document.getElementById('email-lib-modal');
        if (emailModal && !emailModal.classList.contains('hidden')) {
          // Already left-docked → nothing to do (modalSnap re-anchors on its own).
          if (!emailModal.classList.contains('modal-left-docked')) {
            try { applyEdgeDock(emailModal, 'left'); } catch (_) {}
          }
        }
        // Same treatment for an open email-reader modal (one specific email
        // open standalone — typical "click email, click doc" flow).
        document.querySelectorAll('.modal[id^="email-reader-"]').forEach(m => {
          if (m.classList.contains('hidden')) return;
          if (m.classList.contains('modal-left-docked')) return;
          try { applyEdgeDock(m, 'left'); } catch (_) {}
        });
      }
    }
    last = cur;
  });
  _docOpenObs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
}

function _bindEvents() {
  // Clicking anywhere in the email section header opens the popup
  // (except the compose button which has its own handler)
  const section = document.getElementById('email-section');
  const header = section?.querySelector('.section-header-flex');
  if (header) {
    header.style.cursor = 'pointer';
    header.addEventListener('click', (e) => {
      if (e.target.closest('#email-compose-btn')) return;
      openEmailLibrary();
      markInboxAsSeen();
    });
  }

  // Compose button creates a new email document
  const composeBtn = document.getElementById('email-compose-btn');
  if (composeBtn) {
    composeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      _composeNew();
    });
  }

  // Delay the lightweight unread badge check so opening Odysseus doesn't
  // compete with the initial chat/session paint. The full email list now loads
  // only when the inbox is actually opened.
  setTimeout(_refreshUnreadCount, 8000);
  setInterval(_refreshUnreadCount, 60000);

  // Deep-link: #email=<folder>:<uid> opens the library and expands that card
  _maybeOpenFromHash();
  window.addEventListener('hashchange', _maybeOpenFromHash);
}

function _maybeOpenFromHash() {
  const h = window.location.hash || '';
  const m = h.match(/^#email=([^:]+):(\d+)/);
  if (!m) return;
  const folder = decodeURIComponent(m[1]);
  const uid = m[2];
  try { openEmailLibrary({ folder, uid }); } catch (e) { console.error(e); }
  // Clear the hash so reloads don't reopen
  try { history.replaceState(null, '', window.location.pathname + window.location.search); } catch (_) {}
}

// Tint helper — turns the urgent-email-scanner's max_score into a dot color.
// Falls back to the default (blue / unset) when scanner is off or no urgent.
function _urgencyColor(score) {
  if (score >= 3) return 'var(--color-error, #e06c75)';   // red — urgent now
  if (score === 2) return '#f0ad4e';                       // orange — reply soon
  return '';                                                // default (blue / theme)
}

async function _refreshUnreadCount() {
  // Default the dot to hidden — only the verified "new mail above threshold"
  // path below should turn it on. Without this, a fetch error or a backend
  // returning malformed data left a stale dot from a previous account/session.
  const dot = document.getElementById('email-unread-dot');
  if (dot && !dot._stickyState) dot.style.display = 'none';
  try {
    // Parallel: cheap unread state + urgency state.
    const [stateRes, urgRes] = await Promise.all([
      fetch(emailApiUrl('/api/email/unread-state', { folder: 'INBOX' })),
      fetch(`${API_BASE}/api/email/urgency-state`, { credentials: 'same-origin' }).catch(() => null),
    ]);
    if (!stateRes || !stateRes.ok) return;
    const data = await stateRes.json();
    if (!dot) return;

    const unreadCount = Number(data.unread_count || 0);
    if (unreadCount <= 0) {
      dot.style.display = 'none';
      return;
    }

    // Compare highest unread UID to the last-seen threshold in localStorage
    const lastSeen = parseInt(localStorage.getItem('odysseus-email-last-seen-uid') || '0', 10);
    const maxUid = parseInt(data.max_uid || '0', 10) || 0;

    // Only show dot if there's a new email above the threshold
    const hasNewUnread = maxUid > lastSeen;
    dot.style.display = hasNewUnread ? '' : 'none';
    if (hasNewUnread && !isLibOpen()) {
      prewarmUnreadEmails({ limit: Math.min(10, Math.max(1, unreadCount)), maxUid }).catch(() => {});
    }

    // Color the dot by urgency tier. Cache the per-uid map so the per-row
    // renderer can reuse it without a second fetch.
    if (dot.style.display !== 'none' && urgRes && urgRes.ok) {
      try {
        const ud = await urgRes.json();
        window._emailUrgencyState = ud;
        const tint = _urgencyColor(ud.max_score || 0);
        if (tint) dot.style.backgroundColor = tint;
        else dot.style.backgroundColor = '';
      } catch (_) {}
    } else if (dot.style.display !== 'none') {
      dot.style.backgroundColor = '';
    }
  } catch (e) {
    // Network/parse error — keep the dot hidden (default at the top).
    if (dot) dot.style.display = 'none';
  }
}

// Records the current max UID so only later arrivals light the unread dot.
export function markInboxAsSeen() {
  fetch(emailApiUrl('/api/email/unread-state', { folder: 'INBOX' }))
    .then(r => r.json())
    .then(data => {
      const maxUid = parseInt(data.max_uid || '0', 10) || 0;
      if (maxUid > 0) {
        localStorage.setItem('odysseus-email-last-seen-uid', String(maxUid));
      }
      const dot = document.getElementById('email-unread-dot');
      if (dot) dot.style.display = 'none';
    })
    .catch(() => {});
}

async function _openEmail(em, preloadedData = null, mode = 'reply', noteHint = '', prefilledBody = '', mailboxContext = null) {
  const openRequestSeq = ++_openEmailRequestSeq;
  const folderAtStart = mailboxContext?.messageFolder || _currentFolder;
  const accountAtStart = mailboxContext?.accountId ?? (window.__odysseusActiveEmailAccount || '');
  const accountQueryAtStart = accountAtStart ? `&account_id=${encodeURIComponent(accountAtStart)}` : '';
  const mailboxContextIsCurrent = typeof mailboxContext?.isCurrent === 'function'
    ? mailboxContext.isCurrent
    : () => (
        folderAtStart === _currentFolder &&
        accountAtStart === (window.__odysseusActiveEmailAccount || '')
      );
  const isCurrentOpen = () => (
    openRequestSeq === _openEmailRequestSeq &&
    mailboxContextIsCurrent()
  );
  const aiReplyMode = mode === 'ai-reply-fast' ? 'fast' : '';
  const wantsAiReply = mode === 'ai-reply' || !!aiReplyMode;
  // Body pre-fill from the agent's open_email_reply tool call takes the
  // same insertion slot as an AI-suggested body — both land just before
  // the quoted-original block.
  let aiSuggestedBody = (typeof prefilledBody === 'string' && prefilledBody.trim()) ? prefilledBody.trim() : null;
  if (wantsAiReply) {
    // Fall through to reply-all (not plain reply) so the generated AI
    // draft addresses everyone on the original thread. On single-
    // recipient emails this collapses to a regular reply since there's
    // no one else to CC.
    mode = 'reply-all';
  }
  try {
    let data = preloadedData;
    if (!data) {
      const fullQS = mode === 'forward' ? '&full=1' : '';
      const res = await fetch(`${API_BASE}/api/email/read/${em.uid}?folder=${encodeURIComponent(folderAtStart)}${accountQueryAtStart}&mark_seen=true${fullQS}`);
      data = await res.json();
    }
    if (!isCurrentOpen()) return;
    if (data.error) {
      console.error('Failed to read email:', data.error);
      showError('Could not load email: ' + data.error);
      return;
    }
    // The list row is already populated from the durable email index. Some
    // IMAP/read paths can return a partial object for long Outlook threads;
    // never let that create a reply draft with blank To/Subject.
    const _fallback = (primary, fallback) => {
      const p = primary == null ? '' : String(primary).trim();
      if (p) return primary;
      return fallback == null ? '' : fallback;
    };
    data = {
      ...em,
      ...data,
      uid: data.uid || em.uid,
      subject: _fallback(data.subject, em.subject),
      from_name: _fallback(data.from_name, em.from_name || em.from_address),
      from_address: _fallback(data.from_address, em.from_address),
      to: _fallback(data.to, em.to),
      cc: _fallback(data.cc, em.cc),
      date: _fallback(data.date, em.date),
      message_id: _fallback(data.message_id, em.message_id),
    };
    // A Drafts mailbox item is already a composed message. Opening it should
    // load that message into the composer, never create a reply to the draft.
    if (/draft/i.test(String(folderAtStart || '')) && _docModule?.openEmailDraft) {
      await _docModule.openEmailDraft(data);
      return;
    }
    if (wantsAiReply && _docModule?.generateEmailReply) {
      const opened = await _openEmail(em, data, 'reply-all', '', '', mailboxContext);
      if (!opened) return false;
      return await _docModule.generateEmailReply({ mode: 'ai-reply-fast', noteHint, originalBody: data.body }) === true;
    }
    if (wantsAiReply) {
      const activeReplyAccount = data.account_id || em.account_id || accountAtStart;
      if (data.cached_ai_reply && !noteHint && !activeReplyAccount) {
        aiSuggestedBody = _cleanAiReplyText(data.cached_ai_reply);
      } else {
        showToast('Writing AI reply', {
          duration: 8000,
          leadingIcon: 'spinner',
          aiReplyProgress: true,
        });
        try {
          let currentModel = '';
          let currentSessionId = '';
          try {
            currentModel = sessionModule?.getCurrentModel() || '';
            currentSessionId = sessionModule?.getCurrentSessionId() || '';
          } catch (_) {}
          const res = await fetch(`${API_BASE}/api/email/ai-reply`, jsonRequest('POST', {
            to: data.from_address,
            subject: `Re: ${data.subject}`,
            original_body: data.body,
            model: currentModel,
            session_id: currentSessionId,
            message_id: data.message_id || '',
            uid: String(em.uid || ''),
            folder: folderAtStart,
            account_id: activeReplyAccount,
            // The regular AI Reply action should use the full reply path.
            // Keep the explicit fast variant available for callers that
            // still request it, but do not silently downgrade normal
            // replies to the short-context generation budget.
            fast: aiReplyMode === 'fast',
            user_hint: (noteHint || '').trim() || undefined,
          }));
          const result = await res.json().catch(() => ({}));
          if (!res.ok) {
            throw new Error(result.error || `AI reply service returned HTTP ${res.status}`);
          }
          if (!isCurrentOpen()) return;
          if (result.success && result.reply) {
            aiSuggestedBody = _cleanAiReplyText(result.reply);
          } else {
            const _rawMsg = result.error || 'AI reply could not be generated';
            const _msg = /empty response/i.test(_rawMsg)
              ? 'AI returned empty response.'
              : _rawMsg;
            console.error('AI reply generation failed:', _msg);
            showError('AI reply failed: ' + _msg);
            return;
          }
        } catch (e) {
          if (!isCurrentOpen()) return;
          console.error('AI reply generation failed:', e);
          showError('AI reply failed: ' + (e.message || e));
          return;
        }
      }
    }

    if (!isCurrentOpen()) return;
    // Only claim the message is read when the provider accepted the \Seen
    // transition. A failed STORE still opens the message; it just stays unread.
    const markedSeen = !data.mark_seen_failed;
    em.is_read = markedSeen;

    // Addresses to exclude from Reply All. Prefer the full set of configured
    // accounts (so a multi-account user's other mailboxes are excluded too),
    // falling back to the single active address. Empty ⇒ no exclusion.
    const myAddresses = (Array.isArray(window._myEmailAddresses) && window._myEmailAddresses.length)
      ? window._myEmailAddresses
      : (window._myEmailAddress ? [window._myEmailAddress] : []);

    const fromIsMe = _isMyEmailAddress(data.from_address, myAddresses);
    const originalToWithoutMe = _withoutMyAddresses(data.to, myAddresses);
    const originalCcWithoutMe = _withoutMyAddresses(data.cc, myAddresses);

    let toAddress = fromIsMe
      ? (originalToWithoutMe.join(', ') || originalCcWithoutMe[0] || data.from_address)
      : data.from_address;
    let ccAddresses = '';
    let subjectPrefix = 'Re: ';

    if (mode === 'reply-all') {
      if (fromIsMe) {
        // Replying from Sent should go back to the people I originally wrote
        // to, not to myself. Keep original Cc recipients on Cc.
        toAddress = originalToWithoutMe.join(', ') || originalCcWithoutMe[0] || data.from_address;
        ccAddresses = originalCcWithoutMe.filter(addr => !originalToWithoutMe.some(t => extractEmail(t) === extractEmail(addr))).join(', ');
      } else {
        // Build reply-all: TO = original sender, CC = everyone else (To + Cc minus me)
        ccAddresses = buildReplyAllCc(data, myAddresses);
      }
    } else if (mode === 'forward') {
      toAddress = '';
      subjectPrefix = 'Fwd: ';
    }

    // Don't double-prefix `Re:` / `Fwd:` when the subject already starts with one.
    // Replies to replies were producing `Re: Re: Re: …` which can also break
    // some IMAP servers' header parsing on very long subject lines.
    let _baseSubject = (data.subject || '').trim();
    if (subjectPrefix === 'Re: ' && /^re\s*:/i.test(_baseSubject)) subjectPrefix = '';
    else if (subjectPrefix === 'Fwd: ' && /^fwd?\s*:/i.test(_baseSubject)) subjectPrefix = '';
    if (mode !== 'forward' && !String(toAddress || '').trim()) {
      throw new Error('Cannot create reply: sender address is missing from this email.');
    }
    let content = `To: ${toAddress}\nSubject: ${subjectPrefix}${_baseSubject}`;
    if (ccAddresses) content += `\nCc: ${ccAddresses}`;
    if (mode !== 'forward' && data.message_id) content += `\nIn-Reply-To: ${data.message_id}`;
    if (mode !== 'forward' && data.message_id) content += `\nReferences: ${data.references ? data.references + ' ' + data.message_id : data.message_id}`;
    content += `\nX-Source-UID: ${em.uid}`;
    content += `\nX-Source-Folder: ${folderAtStart}`;
    const forwardedAttachments = mode === 'forward'
      ? (data.attachments || []).filter(a => {
          const name = String(a?.filename || '').toLowerCase();
          const size = Number(a?.size) || 0;
          if (!/\.(png|jpe?g|gif|bmp|svg|webp)$/i.test(name)) return true;
          if (/^image\d{3,}\.(png|jpe?g|gif)$/i.test(name)) return false;
          if (/^(signature|logo|sig|footer|banner)[-_\d]*\.(png|jpe?g|gif|svg)$/i.test(name)) return false;
          return !(size > 0 && size < 30 * 1024);
        })
      : [];
    if (forwardedAttachments.length > 0) {
      const attStr = forwardedAttachments.map(a => `${a.index}:${a.filename}:${a.size}`).join('|');
      content += `\nX-Attachments: ${attStr}`;
      content += `\nX-Forward-Attachments: 1`;
    }
    content += '\n---\n';

    // Format the original date in a human-readable way for the quote header
    let niceDate = data.date || '';
    try {
      if (data.date) {
        const d = new Date(data.date);
        if (!isNaN(d.getTime())) {
          niceDate = d.toLocaleString([], {
            weekday: 'short', month: 'short', day: 'numeric', year: 'numeric',
            hour: '2-digit', minute: '2-digit',
          });
        }
      }
    } catch (_) {}

    // Plain-text body, with HTML fallback stripped if no text part exists.
    // Without this, an HTML-only email gives data.body === null/undefined
    // and the reply doc opens empty (data.body.split throws).
    let _origBody = (typeof data.body === 'string' && data.body.length) ? data.body : '';
    if (!_origBody && typeof data.body_html === 'string' && data.body_html) {
      _origBody = data.body_html
        .replace(/<style[\s\S]*?<\/style>/gi, '')
        .replace(/<script[\s\S]*?<\/script>/gi, '')
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<\/p>/gi, '\n\n')
        .replace(/<[^>]+>/g, '')
        .replace(/&nbsp;/g, ' ')
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/\n{3,}/g, '\n\n')
        .trim();
    }

    if (mode === 'forward') {
      content += `\n\n---------- Forwarded message ----------\n`;
      content += `From: ${data.from_name} <${data.from_address}>\n`;
      content += `Date: ${niceDate}\n`;
      content += `Subject: ${data.subject}\n`;
      if (data.to) content += `To: ${data.to}\n`;
      content += `\n${_origBody}`;
    } else {
      const quotedBody = _origBody.split('\n').map(l => '> ' + l).join('\n');
      // Inject AI-suggested body if present. No leading newline — the header
      // block already ends with "---\n", so the reply must start on the very
      // first body line, not one row down.
      if (aiSuggestedBody) {
        content += `${aiSuggestedBody}\n\n`;
      } else {
        // Two real editable rows make the empty reply target easy to tap on
        // mobile. Plain leading newlines are trimmed by the rich-email
        // renderer, whereas empty paragraphs survive as editable blocks.
        content += '<p><br></p><p><br></p>\n';
      }
      content += `${_replySeparator}\nOn ${niceDate}, ${data.from_name} <${data.from_address}> wrote:\n${quotedBody}`;
    }

    let replyDraftOpened = false;
    if (_docModule) {
      // Agent-provided reply text should land in the email draft the user
      // already has open. Plain Reply clicks must create a fresh draft: reusing
      // old source-UID drafts can reopen stale quote-only/malformed compose docs
      // and block Send on long threads.
      const reuseExisting = mode !== 'forward' && !!aiSuggestedBody;
      const existingDocId = (reuseExisting && _docModule.findEmailDocId)
        ? _docModule.findEmailDocId(em.uid, folderAtStart)
        : null;
      if (existingDocId) {
        if (!_docModule.isPanelOpen()) _docModule.openPanel();
        await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
        if (!isCurrentOpen()) return;
        await _docModule.loadDocument(existingDocId);
        if (!isCurrentOpen()) return;
        if (typeof _docModule.ensureEmailDraftEnvelope === 'function') {
          await _docModule.ensureEmailDraftEnvelope(existingDocId, content);
          if (!isCurrentOpen()) return;
        }
        if (aiSuggestedBody && typeof _docModule.replaceEmailReplyBody === 'function') {
          await _docModule.replaceEmailReplyBody(existingDocId, aiSuggestedBody, { force: false });
          if (!isCurrentOpen()) return;
        }
        _bringEmailReplyDraftToFrontOnMobile();
        if (mode !== 'forward') _focusMobileReplyBody();
        replyDraftOpened = true;
      } else {
        if (!isCurrentOpen()) return;
        // A reply is another document in the chat the user is currently in.
        // Creating an email-scoped session here made Reply unexpectedly switch
        // chats and hid the rest of the conversation from the active context.
        // The document module will add the new draft as the active tab, so the
        // agent sees the reply draft when the user writes in it.
        let activeSid = sessionModule?.getCurrentSessionId?.() || '';
        if (!activeSid) {
          activeSid = await _createEmailChat(data);
        }
        if (!isCurrentOpen()) return;
        if (!activeSid) {
          console.error('reply: could not obtain a session_id');
          showError('Could not start a reply chat.');
          return;
        }

        const createReplyDoc = (sessionId) => fetch(`${API_BASE}/api/document`, jsonRequest('POST', {
          session_id: sessionId,
          title: data.subject,
          content: content,
          language: 'email',
        }));
        let docRes = await createReplyDoc(activeSid);
        if (!isCurrentOpen()) return;
        if (docRes.status === 404) {
          console.warn('[reply-debug] draft session rejected; retrying in a fresh email chat', activeSid);
          if (!isCurrentOpen()) return;
          activeSid = await _createEmailChat(data, { forceNew: true });
          if (!isCurrentOpen()) return;
          if (activeSid) {
            docRes = await createReplyDoc(activeSid);
            if (!isCurrentOpen()) return;
          }
        }
        if (!docRes.ok) {
          const errText = await docRes.text();
          if (!isCurrentOpen()) return;
          console.error('[reply-debug] POST /api/document failed', docRes.status, errText);
          showError('Failed to create reply draft (' + docRes.status + ')');
          return;
        }
        const doc = await docRes.json();
        if (!isCurrentOpen()) return;
        if (doc.id) {
          const wasOpen = _docModule.isPanelOpen();
          if (!wasOpen) _docModule.openPanel();
          await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
          if (!isCurrentOpen()) return;
          // Use the doc dict from the POST directly — avoids a 404 race
          // when the GET fires before the new row is visible to the read
          // connection (or when caching is interfering). loadDocument's
          // GET path can still be used as a fallback.
          if (_docModule.injectFreshDoc) {
            await _docModule.injectFreshDoc(doc);
            if (!isCurrentOpen()) return;
          } else {
            await _docModule.loadDocument(doc.id);
            if (!isCurrentOpen()) return;
          }
          _bringEmailReplyDraftToFrontOnMobile();
          if (mode !== 'forward') _focusMobileReplyBody();
          replyDraftOpened = true;
        }
      }
    }
    return replyDraftOpened;
  } catch (e) {
    if (!isCurrentOpen()) return;
    console.error('Failed to open email:', e);
    const msg = e && e.message ? e.message : String(e);
    showError('Reply failed: ' + msg);
  }
}

async function _createEmailChat(emailData, opts = {}) {
  const subject = String(emailData?.subject || 'New Email').trim() || 'New Email';
  const title = subject === 'New Email' ? 'New Email' : `Email: ${subject.slice(0, 60)}`;
  const forceNew = !!opts.forceNew;
  try {
    const currentSid = sessionModule.getCurrentSessionId?.() || '';
    const current = sessionModule.getSessions?.().find(s => s.id === currentSid);
    const currentIsBlank = !!current
      && !current.archived
      && !current.has_documents
      && !current.has_images
      && Number(current.message_count || 0) === 0
      && current.folder !== 'Assistant'
      && current.folder !== 'Tasks';
    if (!forceNew && currentIsBlank) {
      const meta = document.getElementById('current-meta');
      if (meta) meta.textContent = title;
      return current.id;
    }
    let url = current?.endpoint_url || '';
    let model = current?.model || '';
    let endpointId = current?.endpoint_id || '';
    if (!url || !model) {
      try {
        const dcRes = await fetch(`${API_BASE}/api/default-chat`, { credentials: 'same-origin' });
        const dc = dcRes.ok ? await dcRes.json() : {};
        url = dc.endpoint_url || '';
        model = dc.model || '';
        endpointId = dc.endpoint_id || '';
      } catch (_) {}
    }

    const fd = new FormData();
    fd.append('name', title);
    fd.append('skip_validation', 'true');
    if (url) fd.append('endpoint_url', url);
    if (model) fd.append('model', model);
    if (endpointId) fd.append('endpoint_id', endpointId);
    const res = await fetch(`${API_BASE}/api/session`, { method: 'POST', body: fd, credentials: 'same-origin' });
    if (!res.ok) {
      console.error('email chat create failed', res.status, await res.text().catch(() => ''));
      return '';
    }
    const payload = await res.json().catch(() => ({}));
    const sid = payload?.id || '';
    if (!sid) return '';
    if (sessionModule?.loadSessions) await sessionModule.loadSessions();
    if (sessionModule?.selectSession) await sessionModule.selectSession(sid);
    const meta = document.getElementById('current-meta');
    if (meta) meta.textContent = title;
    return sid;
  } catch (e) {
    console.error('Failed to create email chat:', e);
    return '';
  }
}

async function _composeNew() {
  if (!_docModule) return;
  // Don't open the panel yet: creating the chat below can switch sessions,
  // which tears the panel down. injectFreshDoc mounts it once the doc exists.
  try {
    let sid = await _createEmailChat({ subject: 'New Email' });
    if (!sid) {
      console.error('compose: could not obtain a session_id');
      showError('Could not start a new email (no session).');
      return;
    }
    const createComposeDoc = (sessionId) => fetch(`${API_BASE}/api/document`, jsonRequest('POST', {
      session_id: sessionId,
      title: 'New Email',
      content: 'To: \nSubject: \n---\n',
      language: 'email',
    }));
    let res = await createComposeDoc(sid);
    if (res.status === 404) {
      console.warn('[compose-debug] draft session rejected; retrying in a fresh email chat', sid);
      sid = await _createEmailChat({ subject: 'New Email' }, { forceNew: true });
      if (sid) res = await createComposeDoc(sid);
    }
    if (!res.ok) {
      console.error('compose POST failed', res.status, await res.text().catch(() => ''));
      showError('Failed to create new email (' + res.status + ')');
      return;
    }
    const doc = await res.json();
    if (doc.id) {
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      // Use the doc dict from POST directly to avoid the GET 404 race that
      // hits a freshly-created doc on a separate read connection.
      if (_docModule.injectFreshDoc) {
        _docModule.injectFreshDoc(doc);
      } else {
        _docModule.loadDocument(doc.id);
      }
    }
  } catch (e) {
    console.error('Failed to create email:', e);
  }
}
