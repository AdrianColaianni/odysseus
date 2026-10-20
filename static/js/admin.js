// static/js/admin.js — Admin panel module (ES6)
// Admin-only: users, endpoints, built-in tools, backup, logs

import uiModule, { esc } from './ui.js?v=20260916largetoolscroll1';
import settingsModule from './settings.js?v=20260912writingstyle3';
import { providerLogo, providerLogoFromUrl } from './providers.js';
import { sortModelObjects } from './modelSort.js';
import { PROVIDER_DEVICE_FLOWS, formatDeviceFlowError, runProviderDeviceFlow } from './providerDeviceFlow.js';
import {
  accountTitle as chatgptAccountTitle,
  buildUsageViewModel as buildChatgptUsageViewModel,
  isChatgptSubscriptionEndpoint,
  renderUsageCardHtml as renderChatgptUsageCardHtml,
} from './chatgptSubscriptionUsage.js';
import { getSettings, getTools, invalidateSettings, invalidateTools } from './appConfig.js';

let initialized = false;
let modalEl = null;
// Id of the endpoint just added, so the next render flashes a glow on its row.
let _recentlyAddedEpId = null;
let _authPolicy = { password_min_length: 8, reserved_usernames: [] };
let _endpointSelectMode = false;
const _selectedEndpointIds = new Set();

function el(id) { return document.getElementById(id); }
function _setMsg(node, text, ok) { node.textContent = text; node.className = ok ? 'admin-success' : 'admin-error'; }

const PRIV_LABELS = {
  can_use_agent: 'Agent mode',
  can_use_browser: 'Browser automation',
  can_use_bash: 'Shell / Python / Files',
  can_use_documents: 'Document editor',
  can_use_research: 'Deep research',
  can_generate_images: 'Image generation',
  can_manage_memory: 'Memory & skills',
};

async function loadUsers() {
  const list = el('adm-userList');
  try {
    const res = await fetch('/api/auth/users', { credentials: 'same-origin' });
    if (res.status === 401 || res.status === 403) { list.innerHTML = '<div class="admin-empty">Access denied</div>'; return; }
    const data = await res.json();
    if (!data.users || data.users.length === 0) { list.innerHTML = '<div class="admin-empty">No users found</div>'; return; }
    list.innerHTML = '';
    data.users.forEach(u => {
      const row = document.createElement('div');
      row.className = 'admin-user-row';

      // Header: name + badges + delete
      const header = document.createElement('div');
      header.style.cssText = 'display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;cursor:pointer;padding:4px 0;';
      const initial = u.username.charAt(0).toUpperCase();
      header.innerHTML = `
        <div class="admin-user-info">
          <div style="width:28px;height:28px;border-radius:50%;background:color-mix(in srgb, var(--accent) 20%, var(--panel));display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex-shrink:0;color:var(--accent);">${esc(initial)}</div>
          <div>
            <span class="admin-user-name">${esc(u.username)}</span>
            ${u.is_admin ? '<span class="admin-badge" style="margin-left:6px;">ADMIN</span>' : '<span style="font-size:10px;opacity:0.4;display:block;">Click to manage privileges</span>'}
          </div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
          <button class="admin-btn-sm" data-adm-toggle-admin="${esc(u.username)}" data-make-admin="${u.is_admin ? '0' : '1'}" style="font-size:11px;">${u.is_admin ? 'Revoke admin' : 'Make admin'}</button>
          <button class="admin-btn-sm" data-adm-rename-user="${esc(u.username)}" style="font-size:11px;">Rename</button>
          ${u.is_admin ? '' : '<button class="admin-btn-sm" data-adm-reset-password style="font-size:11px;">Change password</button>'}
          ${u.is_admin ? '' : `<button class="admin-btn-delete" data-adm-del-user="${esc(u.username)}" style="font-size:11px;">Remove</button>`}
          ${u.is_admin ? '' : '<svg class="admin-user-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.3;transition:transform 0.2s,opacity 0.2s;"><polyline points="6 9 12 15 18 9"/></svg>'}
        </div>
      `;
      row.appendChild(header);

      // Privileges panel (hidden by default, not for admins)
      if (!u.is_admin) {
        const privPanel = document.createElement('div');
        privPanel.className = 'admin-priv-panel hidden';
        privPanel.style.cssText = 'padding:8px 0 4px;border-top:1px solid var(--border);margin-top:8px;';

        // Boolean toggles
        let html = '<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;opacity:0.35;font-weight:600;margin-bottom:4px;">Features</div>';
        for (const [key, label] of Object.entries(PRIV_LABELS)) {
          const checked = u.privileges && u.privileges[key] ? 'checked' : '';
          html += `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;">
            <span style="font-size:12px;">${label}</span>
            <label class="admin-switch" style="transform:scale(0.85);"><input type="checkbox" data-priv="${key}" data-user="${esc(u.username)}" ${checked}><span class="admin-slider"></span></label>
          </div>`;
        }
        // Rate limit
        html += '<div style="font-size:10px;text-transform:uppercase;letter-spacing:0.5px;opacity:0.35;font-weight:600;margin:10px 0 4px;">Limits</div>';
        const maxMsg = (u.privileges && u.privileges.max_messages_per_day) || 0;
        html += `<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;">
          <div>
            <span style="font-size:12px;">Daily message limit</span>
            <div style="font-size:10px;opacity:0.4;">0 = no limit</div>
          </div>
          <input type="number" min="0" value="${maxMsg}" data-priv="max_messages_per_day" data-user="${esc(u.username)}" style="width:70px;padding:4px 6px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--fg);font-size:12px;text-align:center;">
        </div>`;
        // Allowed models — checkbox list
        const allowedModels = Array.isArray(u.privileges && u.privileges.allowed_models)
          ? u.privileges.allowed_models
          : [];
        const allowedSet = new Set(allowedModels);
        const modelsRestricted = !!(u.privileges && u.privileges.allowed_models_restricted);
        const blockAllModels = !!(u.privileges && u.privileges.block_all_models);
        html += `<div style="padding:4px 0;">
          <div style="display:flex;align-items:center;justify-content:space-between;">
            <span style="font-size:12px;">Allowed models</span>
            <div style="display:flex;gap:8px;">
              <a href="#" class="priv-models-all" data-user="${esc(u.username)}" style="font-size:10px;opacity:0.5;">All</a>
              <a href="#" class="priv-models-none" data-user="${esc(u.username)}" style="font-size:10px;opacity:0.5;">None</a>
            </div>
          </div>
          <div style="font-size:10px;opacity:0.4;margin-bottom:4px;">${blockAllModels ? 'No models allowed' : (!modelsRestricted ? 'All models allowed (no restrictions)' : (allowedSet.size === 0 ? 'No models allowed' : allowedSet.size + ' model(s) allowed'))}</div>
          <div class="priv-models-list" data-user="${esc(u.username)}">
            <span style="opacity:0.4;font-size:11px;">Loading models...</span>
          </div>
        </div>`;
        privPanel.innerHTML = html;
        row.appendChild(privPanel);

        // Toggle panel visibility + rotate chevron + load models
        let _modelsLoaded = false;
        header.addEventListener('click', (e) => {
          if (e.target.closest('.admin-btn-delete, [data-adm-rename-user], [data-adm-toggle-admin], [data-adm-reset-password]')) return;
          privPanel.classList.toggle('hidden');
          const chevron = header.querySelector('.admin-user-chevron');
          if (chevron) {
            const isOpen = !privPanel.classList.contains('hidden');
            chevron.style.transform = isOpen ? 'rotate(180deg)' : '';
            chevron.style.opacity = isOpen ? '0.7' : '0.3';
          }
          // Load models list on first expand
          if (!_modelsLoaded && !privPanel.classList.contains('hidden')) {
            _modelsLoaded = true;
            _loadModelsForUser(u.username, allowedSet, modelsRestricted, blockAllModels, privPanel);
          }
        });

        // Wire privilege changes (boolean + number inputs, not model checkboxes)
        privPanel.querySelectorAll('[data-priv]').forEach(input => {
          const handler = async () => {
            const username = input.dataset.user;
            const key = input.dataset.priv;
            let value;
            if (input.type === 'checkbox') value = input.checked;
            else if (input.type === 'number') value = parseInt(input.value) || 0;
            else value = input.value;
            try {
              await fetch(`/api/auth/users/${encodeURIComponent(username)}/privileges`, {
                method: 'PUT', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ [key]: value }),
              });
            } catch (e) { uiModule.showError('Failed to update privilege'); }
          };
          if (input.type === 'checkbox') input.addEventListener('change', handler);
          else input.addEventListener('change', handler);
        });
      }

      const passwordBtn = row.querySelector('[data-adm-reset-password]');
      passwordBtn?.addEventListener('click', async (e) => {
        e.stopPropagation();
        const options = { title: 'Change password', inputType: 'password', maxLength: 72 };
        const password = await uiModule.styledPrompt(`New password for "${u.username}". Their existing sessions will be signed out.`, options);
        if (password === null) return;
        const confirmation = await uiModule.styledPrompt('Confirm the new password', options);
        if (confirmation === null) return;
        if (password !== confirmation) { uiModule.showError('Passwords do not match'); return; }
        passwordBtn.disabled = true;
        try {
          const res = await fetch(`/api/auth/users/${encodeURIComponent(u.username)}/password`, {
            method: 'PUT', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_password: password }),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) { uiModule.showError(data.detail || 'Failed to change password'); return; }
          uiModule.showToast('Password changed. Existing sessions signed out.');
        } catch { uiModule.showError('Failed to change password'); }
        finally { passwordBtn.disabled = false; }
      });

      // Rename button
      const renameBtn = row.querySelector('[data-adm-rename-user]');
      if (renameBtn) {
        renameBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const oldUsername = renameBtn.dataset.admRenameUser;
          const next = await uiModule.styledPrompt(`Rename "${oldUsername}"`, {
            defaultValue: oldUsername,
            placeholder: 'New username',
            confirmText: 'Rename',
          });
          const username = (next || '').trim();
          if (!username || username === oldUsername) return;
          try {
            const res = await fetch(`/api/auth/users/${encodeURIComponent(oldUsername)}/rename`, {
              method: 'PUT',
              credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ username }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
              uiModule.showError(data.detail || 'Failed to rename user');
              return;
            }
            if (data.renamed_self) {
              window.location.reload();
              return;
            }
            loadUsers();
          } catch (err) {
            uiModule.showError('Failed to rename user');
          }
        });
      }

      // Delete button
      const delBtn = row.querySelector('[data-adm-del-user]');
      if (delBtn) {
        delBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const username = delBtn.dataset.admDelUser;
          if (!await uiModule.styledConfirm(`Remove user "${username}"?`, { confirmText: 'Remove', danger: true })) return;
          const res = await fetch('/api/auth/users', { method: 'DELETE', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username }) });
          if (res.ok) loadUsers();
          else uiModule.showError('Failed to delete user');
        });
      }

      // Promote / demote (admin toggle) — present on every row
      const adminToggleBtn = row.querySelector('[data-adm-toggle-admin]');
      if (adminToggleBtn) {
        adminToggleBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const username = adminToggleBtn.dataset.admToggleAdmin;
          const makeAdmin = adminToggleBtn.dataset.makeAdmin === '1';
          const confirmMsg = makeAdmin
            ? `Grant admin rights to "${username}"? They'll get full access to all settings and users — including the power to demote or remove other admins (you included).`
            : `Revoke admin rights from "${username}"? They'll lose access to the admin panel.`;
          if (!await uiModule.styledConfirm(confirmMsg, { confirmText: makeAdmin ? 'Make admin' : 'Revoke admin', danger: !makeAdmin })) return;
          adminToggleBtn.disabled = true;
          try {
            const res = await fetch(`/api/auth/users/${encodeURIComponent(username)}/admin`, {
              method: 'PUT',
              credentials: 'same-origin',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ is_admin: makeAdmin }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
              uiModule.showError(data.detail || 'Failed to change admin status');
              adminToggleBtn.disabled = false;
              return;
            }
            // Demoting yourself drops your own admin access — reload into the
            // normal-user view (mirrors the rename-self reload above).
            if (data.self) { window.location.reload(); return; }
            loadUsers();
          } catch (err) {
            uiModule.showError('Failed to change admin status');
            adminToggleBtn.disabled = false;
          }
        });
      }

      list.appendChild(row);
    });
  } catch (e) { list.innerHTML = '<div class="admin-error">Failed to load users</div>'; }
}

async function _loadModelsForUser(username, allowedSet, modelsRestricted, blockAllModels, privPanel) {
  const listEl = privPanel.querySelector(`.priv-models-list[data-user="${username}"]`);
  if (!listEl) return;
  try {
    // /api/models comes from `cached_models`, which misses endpoints not yet probed.
    const res = await fetch('/api/model-endpoints', { credentials: 'same-origin' });
    const data = await res.json();
    const allModels = [];
    (Array.isArray(data) ? data : []).forEach(ep => {
      if (!ep.online) return;
      (ep.models || []).forEach(mid => {
        allModels.push({ mid, epName: ep.name || '', display: mid.split('/').pop() });
      });
    });
    if (!allModels.length) {
      listEl.innerHTML = '<span style="opacity:0.4;font-size:11px;">No models available</span>';
      return;
    }
    let restricted = modelsRestricted;
    let blockAll = blockAllModels;
    listEl.innerHTML = sortModelObjects(allModels).map(m => {
      const checked = !blockAll && (!restricted || allowedSet.has(m.mid)) ? 'checked' : '';
      return `<label>
        <input type="checkbox" class="priv-model-cb" data-mid="${esc(m.mid)}" ${checked}>
        <span>${esc(m.display)}</span>
        <span style="opacity:0.3;font-size:10px;margin-left:auto;">${esc(m.epName)}</span>
      </label>`;
    }).join('');

    // Save on change
    function _saveModels() {
      const checked = [];
      listEl.querySelectorAll('.priv-model-cb').forEach(cb => {
        if (cb.checked) checked.push(cb.dataset.mid);
      });
      // Three distinct states the backend must be able to tell apart:
      //  - all checked   -> no restriction (allowed_models: [], block_all_models: false)
      //  - none checked  -> block everything (allowed_models: [], block_all_models: true)
      //  - some checked  -> allowlist (allowed_models: checked, block_all_models: false)
      let value, hintText;
      if (checked.length === allModels.length) {
        restricted = false;
        blockAll = false;
        value = [];
        hintText = 'All models allowed (no restrictions)';
      } else if (checked.length === 0) {
        restricted = true;
        blockAll = true;
        value = [];
        hintText = 'No models allowed';
      } else {
        restricted = true;
        blockAll = false;
        value = checked;
        hintText = value.length + ' model(s) allowed';
      }
      const hint = privPanel.querySelector('.priv-models-list[data-user]')?.previousElementSibling?.querySelector('div[style*="opacity"]');
      if (hint) hint.textContent = hintText;
      fetch(`/api/auth/users/${encodeURIComponent(username)}/privileges`, {
        method: 'PUT', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ allowed_models: value, allowed_models_restricted: restricted, block_all_models: blockAll }),
      }).catch(e => console.warn('Failed to save model privileges for', username, e));
    }
    listEl.querySelectorAll('.priv-model-cb').forEach(cb => cb.addEventListener('change', _saveModels));

    // All / None buttons
    privPanel.querySelector(`.priv-models-all[data-user="${username}"]`)?.addEventListener('click', (e) => {
      e.preventDefault();
      listEl.querySelectorAll('.priv-model-cb').forEach(cb => cb.checked = true);
      _saveModels();
    });
    privPanel.querySelector(`.priv-models-none[data-user="${username}"]`)?.addEventListener('click', (e) => {
      e.preventDefault();
      listEl.querySelectorAll('.priv-model-cb').forEach(cb => cb.checked = false);
      _saveModels();
    });
  } catch (e) {
    listEl.innerHTML = '<span style="opacity:0.4;font-size:11px;">Failed to load models</span>';
  }
}

function initSignupToggle() {
  const toggle = el('adm-signupToggle');
  fetch('/api/auth/status', { credentials: 'same-origin' })
    .then(r => r.json())
    .then(d => { toggle.checked = !!d.signup_enabled; })
    .catch(e => console.warn('Auth status fetch failed:', e));
  toggle.addEventListener('change', async () => {
    try {
      const res = await fetch('/api/auth/signup-toggle', { method: 'POST', credentials: 'same-origin' });
      const data = await res.json();
      toggle.checked = data.signup_enabled;
    } catch (e) { toggle.checked = !toggle.checked; }
  });
}

function initShareDefaultsToggle() {
  const toggle = el('adm-shareDefaultsToggle');
  getSettings()
    .then(d => { toggle.checked = !!d.share_defaults_with_users; })
    .catch(e => console.warn('Settings fetch failed:', e));
  toggle.addEventListener('change', async () => {
    try {
      const res = await fetch('/api/auth/settings', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ share_defaults_with_users: toggle.checked }),
      });
      const data = await res.json();
      toggle.checked = !!data.share_defaults_with_users;
    } catch (e) {
      toggle.checked = !toggle.checked;
    } finally {
      // Drop the shared snapshot: it still says what this toggle used to be.
      invalidateSettings();
    }
  });
}

function initAddUser() {
  fetch('/api/auth/policy', { credentials: 'same-origin' })
    .then(r => r.ok ? r.json() : null)
    .then(policy => {
      if (!policy) return;
      _authPolicy = policy;
      const admPw = el('adm-newPassword');
      if (admPw) admPw.placeholder = `Password (min ${policy.password_min_length})`;
    })
    .catch(() => {});
  el('adm-addBtn').addEventListener('click', async () => {
    const msg = el('adm-addMsg');
    msg.textContent = ''; msg.className = '';
    const username = el('adm-newUsername').value.trim();
    const password = el('adm-newPassword').value;
    const is_admin = el('adm-newIsAdmin').checked;
    if (!username) { _setMsg(msg, 'Username required', false); return; }
    if (password.length < _authPolicy.password_min_length) { _setMsg(msg, `Password must be at least ${_authPolicy.password_min_length} characters`, false); return; }
    if (_authPolicy.reserved_usernames.includes(username.toLowerCase())) { _setMsg(msg, 'This username is reserved', false); return; }
    el('adm-addBtn').disabled = true;
    try {
      const res = await fetch('/api/auth/users', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password, is_admin }) });
      const data = await res.json();
      if (res.ok) { _setMsg(msg, 'User created', true); el('adm-newUsername').value = ''; el('adm-newPassword').value = ''; el('adm-newIsAdmin').checked = false; loadUsers(); }
      else { _setMsg(msg, data.detail || 'Failed', false); }
    } catch (e) { _setMsg(msg, 'Request failed', false); }
    el('adm-addBtn').disabled = false;
  });
}

function _isLocalEndpoint(url) {
  if (!url) return false;
  try {
    const u = new URL(url);
    const h = u.hostname.toLowerCase();
    if (h === 'localhost' || h === '127.0.0.1' || h === '0.0.0.0') return true;
    if (h.endsWith('.local')) return true;
    if (/^10\./.test(h)) return true;
    if (/^192\.168\./.test(h)) return true;
    if (/^172\.(1[6-9]|2[0-9]|3[01])\./.test(h)) return true;
    // Tailscale CGNAT range (100.64.0.0/10 → 100.64.x–100.127.x). Servers
    // found via "Scan for Servers" come back as tailnet IPs, which are still
    // your own machines, so group them under Local rather than API.
    if (/^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(h)) return true;
    // Single-label hostnames are LAN by convention.
    if (!h.includes('.')) return true;
    return false;
  } catch { return false; }
}

async function _refreshAfterEndpointChange(deletedEndpointId) {
  try {
    const sm = window.sessionModule;
    const pending = sm && sm.getPendingChat ? sm.getPendingChat() : null;
    if (deletedEndpointId && pending && String(pending.endpointId || '') === String(deletedEndpointId)) {
      if (sm.setPendingChat) sm.setPendingChat(null);
    }
  } catch (_) {}
  try {
    if (window.modelsModule && window.modelsModule.refreshModels) {
      await window.modelsModule.refreshModels(true);
    }
  } catch (_) {}
  window.dispatchEvent(new CustomEvent('ge:model-endpoints-updated', {
    detail: { deletedEndpointId: deletedEndpointId || null }
  }));
  if (window.sessionModule && window.sessionModule.updateModelPicker) {
    window.sessionModule.updateModelPicker();
  }
}

async function _selectAddedModelInChat(endpoint) {
  const modelId = endpoint && Array.isArray(endpoint.models) ? endpoint.models[0] : '';
  if (!modelId) return;
  try {
    if (window.modelsModule && window.modelsModule.refreshModels) {
      await window.modelsModule.refreshModels(true);
    }
  } catch (_) {}
  document.dispatchEvent(new CustomEvent('odysseus:auto-select-model', {
    detail: {
      endpointId: endpoint.id || '',
      endpointName: endpoint.name || '',
      modelId,
      url: endpoint.base_url || '',
    }
  }));
}

function _updateEndpointBulkControls() {
  const selectBtn = el('adm-epSelectBtn');
  const probeBtn = el('adm-epProbeAllBtn');
  const bulk = el('adm-epBulkActions');
  const count = el('adm-epSelectedCount');
  if (selectBtn) {
    selectBtn.classList.toggle('active', _endpointSelectMode);
    selectBtn.setAttribute('aria-pressed', _endpointSelectMode ? 'true' : 'false');
    selectBtn.style.display = _endpointSelectMode ? 'none' : 'inline-flex';
  }
  if (probeBtn) probeBtn.style.display = _endpointSelectMode ? 'none' : 'inline-flex';
  if (bulk) bulk.style.display = _endpointSelectMode ? 'inline-flex' : 'none';
  if (count) count.textContent = `${_selectedEndpointIds.size} selected`;
  const deleteBtn = el('adm-epDeleteSelectedBtn');
  if (deleteBtn) deleteBtn.disabled = _selectedEndpointIds.size === 0;
}

function _ensureEndpointBulkControls() {
  const probeBtn = el('adm-epProbeAllBtn');
  if (!probeBtn || el('adm-epSelectBtn')) {
    _updateEndpointBulkControls();
    return;
  }
  const selectBtn = document.createElement('button');
  selectBtn.type = 'button';
  selectBtn.id = 'adm-epSelectBtn';
  selectBtn.className = 'admin-btn-sm';
  selectBtn.title = 'Select endpoints to delete';
  selectBtn.setAttribute('aria-pressed', 'false');
  selectBtn.style.cssText = 'font-size:11px;font-weight:normal;display:inline-flex;align-items:center;gap:4px;';
  selectBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/></svg>Select';

  const bulk = document.createElement('span');
  bulk.id = 'adm-epBulkActions';
  bulk.style.cssText = 'display:none;align-items:center;gap:5px;';
  bulk.innerHTML = `
    <span id="adm-epSelectedCount" style="font-size:11px;font-weight:normal;opacity:.65;white-space:nowrap;">0 selected</span>
    <button type="button" class="admin-btn-sm" id="adm-epSelectAllBtn" style="font-size:11px;font-weight:normal;">All</button>
    <button type="button" class="admin-btn-delete" id="adm-epDeleteSelectedBtn" disabled style="font-size:11px;display:inline-flex;align-items:center;gap:4px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>Delete</button>
    <button type="button" class="admin-btn-sm" id="adm-epCancelSelectBtn" style="font-size:11px;font-weight:normal;display:inline-flex;align-items:center;gap:4px;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>Cancel</button>`;
  probeBtn.before(selectBtn, bulk);

  selectBtn.addEventListener('click', () => {
    _endpointSelectMode = true;
    _selectedEndpointIds.clear();
    loadEndpoints();
  });
  el('adm-epCancelSelectBtn')?.addEventListener('click', () => {
    _endpointSelectMode = false;
    _selectedEndpointIds.clear();
    loadEndpoints();
  });
  el('adm-epSelectAllBtn')?.addEventListener('click', () => {
    document.querySelectorAll('[data-adm-ep-select]').forEach(cb => {
      cb.checked = true;
      _selectedEndpointIds.add(cb.dataset.admEpSelect);
    });
    _updateEndpointBulkControls();
  });
  el('adm-epDeleteSelectedBtn')?.addEventListener('click', async () => {
    const ids = Array.from(_selectedEndpointIds);
    if (!ids.length) return;
    const ok = await uiModule.styledConfirm(
      `Delete ${ids.length} selected endpoint${ids.length === 1 ? '' : 's'}?`,
      { confirmText: 'Delete', danger: true }
    );
    if (!ok) return;
    const deleteBtn = el('adm-epDeleteSelectedBtn');
    if (deleteBtn) deleteBtn.disabled = true;
    document.querySelectorAll('[data-adm-ep-id]').forEach(row => {
      if (_selectedEndpointIds.has(row.dataset.admEpId)) row.remove();
    });
    const results = await Promise.all(ids.map(async id => {
      try {
        const res = await fetch(`/api/model-endpoints/${encodeURIComponent(id)}`, {
          method: 'DELETE', credentials: 'same-origin'
        });
        return res.ok;
      } catch (_) {
        return false;
      }
    }));
    const deletedCount = results.filter(Boolean).length;
    _endpointSelectMode = false;
    _selectedEndpointIds.clear();
    await _refreshAfterEndpointChange(ids.length === 1 ? ids[0] : null);
    await loadEndpoints();
    if (uiModule?.showToast) {
      const failedCount = ids.length - deletedCount;
      uiModule.showToast(
        failedCount
          ? `Deleted ${deletedCount}/${ids.length} endpoints; ${failedCount} failed`
          : `Deleted ${deletedCount} endpoint${deletedCount === 1 ? '' : 's'}`,
        failedCount ? 4200 : 1800
      );
    }
  });
  _updateEndpointBulkControls();
}

function shouldDisplayEndpointBaseUrl(ep) {
  if (!ep || !ep.base_url) return false;
  if (isChatgptSubscriptionEndpoint(ep)) return false;
  if (isFeatherlessEndpoint(ep)) return false;
  return true;
}

function isFeatherlessEndpoint(ep) {
  if (!ep) return false;
  if (ep.provider === 'featherless') return true;
  const url = String(ep.base_url || '').toLowerCase();
  try {
    const host = new URL(url).hostname;
    return host === 'api.featherless.ai' || host.endsWith('.featherless.ai');
  } catch (_) {
    return url.includes('api.featherless.ai');
  }
}

function endpointDetailHtml(ep, category) {
  const showUrl = shouldDisplayEndpointBaseUrl(ep);
  const copyBtn = (showUrl && category === 'local')
    ? `<button type="button" class="admin-ep-copy-btn" data-adm-copy-url="${esc(ep.base_url)}" title="Copy URL" aria-label="Copy URL" style="background:none;border:none;padding:0 2px;margin-left:6px;cursor:pointer;color:inherit;opacity:0.45;vertical-align:-2px;line-height:1;"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg></button>`
    : '';
  const keyLabel = ep.has_key
    ? (ep.api_key_fingerprint ? ` (key ${esc(ep.api_key_fingerprint)})` : ' (key set)')
    : '';
  const parts = [];
  if (showUrl) {
    parts.push(esc(ep.base_url) + copyBtn);
    if (keyLabel) parts.push(keyLabel);
  } else if (keyLabel) {
    parts.push(keyLabel.trim());
  }
  if (!parts.length) return '';
  return `<div class="admin-ep-detail">${parts.join('')}</div>`;
}

function renderFeatherlessPanel(panel, ep, row) {
  const epId = ep.id;
  const initialPinned = Array.isArray(ep.pinned_models)
    ? ep.pinned_models
    : (typeof ep.pinned_models === 'string' ? JSON.parse(ep.pinned_models || '[]') : []);
  const enabledSet = new Set(initialPinned);
  const toolModes = typeof ep.model_tool_modes === 'object' && ep.model_tool_modes !== null
    ? { ...ep.model_tool_modes }
    : {};
  panel.dataset.pickerMode = 'pinned';

  panel.innerHTML = `<div class="mcp-tools-header">
    <span>Featherless Catalog</span>
  </div>
  <div class="featherless-panel" style="display:flex;flex-direction:column;gap:12px;padding:6px 0;">
    <div class="featherless-search-bar" style="position:relative;display:flex;align-items:center;">
      <input type="search" class="mcp-tools-search featherless-search-input" placeholder="Search Featherless models (min 2 chars)..." style="width:100%;box-sizing:border-box;" data-featherless-search="${esc(epId)}">
      <span class="featherless-spinner-host" style="display:none;position:absolute;right:8px;font-size:10px;opacity:0.55;">Searching...</span>
    </div>
    <div class="featherless-enabled-section">
      <div style="font-size:11px;font-weight:600;opacity:0.8;margin-bottom:4px;">
        Enabled models (<span class="featherless-enabled-count">${enabledSet.size}</span>)
      </div>
      <div class="featherless-enabled-list mcp-tools-list" style="max-height:160px;overflow-y:auto;"></div>
    </div>
    <div class="featherless-results-section">
      <div style="font-size:11px;font-weight:600;opacity:0.8;margin-bottom:4px;">
        Search results
      </div>
      <div class="featherless-results-list mcp-tools-list" style="max-height:280px;overflow-y:auto;">
        <span class="featherless-search-hint" style="opacity:0.5;font-size:11px;padding:4px 0;display:block;">Type at least 2 characters to search over 20,000+ models.</span>
      </div>
      <div class="featherless-pagination" style="display:none;margin-top:6px;text-align:center;">
        <button type="button" class="admin-btn-sm featherless-load-more" style="width:100%;">Load more</button>
      </div>
    </div>
  </div>`;

  const searchInput = panel.querySelector('.featherless-search-input');
  const spinnerHost = panel.querySelector('.featherless-spinner-host');
  const enabledListEl = panel.querySelector('.featherless-enabled-list');
  const enabledCountSpan = panel.querySelector('.featherless-enabled-count');
  const resultsList = panel.querySelector('.featherless-results-list');
  const paginationHost = panel.querySelector('.featherless-pagination');
  const loadMoreBtn = panel.querySelector('.featherless-load-more');

  const showSpinner = () => { if (spinnerHost) spinnerHost.style.display = 'inline-flex'; };
  const hideSpinner = () => { if (spinnerHost) spinnerHost.style.display = 'none'; };

  const formatTokens = (tokens) => {
    if (!tokens || typeof tokens !== 'number') return '';
    if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(tokens % 1000000 === 0 ? 0 : 1)}M`;
    if (tokens >= 1000) return `${Math.round(tokens / 1024)}k`;
    return String(tokens);
  };

  const updateHeaderCount = () => {
    const countBadge = row ? row.querySelector(`[data-adm-ep-models-count="${epId}"]`) : null;
    if (countBadge) {
      countBadge.textContent = `${enabledSet.size} models enabled`;
    }
    if (enabledCountSpan) {
      enabledCountSpan.textContent = String(enabledSet.size);
    }
    ep.pinned_models = Array.from(enabledSet);
  };

  const saveState = async () => {
    try {
      await fetch(`/api/model-endpoints/${epId}/models`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          pinned_models: Array.from(enabledSet),
          model_tool_modes: toolModes,
        }),
      });
      if (typeof _refreshAfterEndpointChange === 'function') {
        _refreshAfterEndpointChange();
      }
    } catch (err) {
      console.error('Failed to save Featherless model state', err);
    }
  };

  const syncSearchCheckboxes = () => {
    resultsList.querySelectorAll('input[data-featherless-search-id]').forEach(cb => {
      const id = cb.dataset.featherlessSearchId;
      cb.checked = enabledSet.has(id);
    });
  };

  const renderEnabledList = () => {
    if (!enabledListEl) return;
    if (enabledSet.size === 0) {
      enabledListEl.innerHTML = '<span style="opacity:0.5;font-size:11px;padding:4px 0;display:block;">No models enabled. Search below to add models.</span>';
      return;
    }
    const sortedIds = Array.from(enabledSet).sort((a, b) => a.localeCompare(b));
    enabledListEl.innerHTML = sortedIds.map(id => {
      const displayName = id.split('/').pop() || id;
      const mode = ['none', 'compact', 'full'].includes(String(toolModes[id] || '').toLowerCase())
        ? String(toolModes[id]).toLowerCase()
        : '';
      return `<div title="${esc(id)}" data-ep-model-row data-model-id="${esc(id)}" class="adm-model-row">
        <label class="adm-model-label">
          <input type="checkbox" class="adm-cb-hidden" data-featherless-enabled-id="${esc(id)}" checked>
          <span class="adm-check-dot" aria-hidden="true"></span>
          <span class="adm-model-name">${esc(displayName)}</span>
        </label>
        <div class="adm-model-tools-col">
          <span class="adm-model-tools-label" title="Select the tool schema profile for this model">Tools</span>
          <select class="adm-model-tool-mode admin-tools-select" data-ep-model-id="${esc(id)}" data-original-tool-mode="${esc(toolModes[id] || '')}">
            <option value="" ${mode === '' ? 'selected' : ''}>Auto</option>
            <option value="full" ${mode === 'full' ? 'selected' : ''}>Regular tools</option>
            <option value="compact" ${mode === 'compact' ? 'selected' : ''}>Odysseus compact</option>
            <option value="none" ${mode === 'none' ? 'selected' : ''}>Tools off</option>
          </select>
        </div>
      </div>`;
    }).join('');

    enabledListEl.querySelectorAll('input[data-featherless-enabled-id]').forEach(cb => {
      cb.addEventListener('change', () => {
        const id = cb.dataset.featherlessEnabledId;
        if (!cb.checked) {
          enabledSet.delete(id);
          updateHeaderCount();
          renderEnabledList();
          syncSearchCheckboxes();
          saveState();
        }
      });
    });

    enabledListEl.querySelectorAll('.adm-model-tool-mode').forEach(sel => {
      sel.addEventListener('change', () => {
        const id = sel.dataset.epModelId;
        const val = String(sel.value || '').toLowerCase();
        if (val) toolModes[id] = val;
        else delete toolModes[id];
        saveState();
      });
    });
  };

  renderEnabledList();

  let currentQuery = '';
  let currentPage = 1;
  let searchAbortController = null;
  let searchTimeout = null;
  let isSearching = false;

  const renderSearchResults = (items, append = false, hasMore = false) => {
    if (!append) {
      resultsList.innerHTML = '';
    }
    if (!items || items.length === 0) {
      if (!append) {
        resultsList.innerHTML = '<span style="opacity:0.5;font-size:11px;padding:4px 0;display:block;">No models found matching your search.</span>';
      }
      if (paginationHost) paginationHost.style.display = 'none';
      return;
    }

    const itemsHtml = items.map(item => {
      const isChecked = enabledSet.has(item.id);
      const displayName = item.name || item.id;
      const ctx = item.context_length ? `${formatTokens(item.context_length)} ctx` : '';
      return `<div title="${esc(item.id)}" data-ep-model-row data-model-id="${esc(item.id)}" class="adm-model-row">
        <label class="adm-model-label" style="width:100%;">
          <input type="checkbox" class="adm-cb-hidden" data-featherless-search-id="${esc(item.id)}" ${isChecked ? 'checked' : ''}>
          <span class="adm-check-dot" aria-hidden="true"></span>
          <span class="adm-model-name" style="flex:1;">${esc(displayName)}</span>
          ${ctx ? `<span class="admin-badge" style="margin-left:auto;font-size:9px;opacity:0.6;">${esc(ctx)}</span>` : ''}
        </label>
      </div>`;
    }).join('');

    if (append) {
      resultsList.insertAdjacentHTML('beforeend', itemsHtml);
    } else {
      resultsList.innerHTML = itemsHtml;
    }

    resultsList.querySelectorAll('input[data-featherless-search-id]').forEach(cb => {
      if (cb.dataset.listenerAttached) return;
      cb.dataset.listenerAttached = '1';
      cb.addEventListener('change', () => {
        const id = cb.dataset.featherlessSearchId;
        if (cb.checked) {
          enabledSet.add(id);
        } else {
          enabledSet.delete(id);
        }
        updateHeaderCount();
        renderEnabledList();
        syncSearchCheckboxes();
        saveState();
      });
    });

    if (paginationHost) {
      paginationHost.style.display = hasMore ? '' : 'none';
    }
  };

  if (searchInput) {
    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
      }
    });

    searchInput.addEventListener('input', () => {
      if (searchTimeout) clearTimeout(searchTimeout);
      searchTimeout = setTimeout(async () => {
        const q = searchInput.value.trim();
        if (q.length < 2) {
          if (searchAbortController) searchAbortController.abort();
          hideSpinner();
          resultsList.innerHTML = '<span class="featherless-search-hint" style="opacity:0.5;font-size:11px;padding:4px 0;display:block;">Type at least 2 characters to search over 20,000+ models.</span>';
          if (paginationHost) paginationHost.style.display = 'none';
          return;
        }

        if (searchAbortController) {
          searchAbortController.abort();
        }
        searchAbortController = new AbortController();
        currentQuery = q;
        currentPage = 1;
        showSpinner();

        try {
          const res = await fetch(`/api/model-endpoints/${epId}/catalog-search?q=${encodeURIComponent(q)}&page=1&per_page=50`, {
            credentials: 'same-origin',
            signal: searchAbortController.signal,
          });
          if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || `HTTP ${res.status}`);
          }
          const data = await res.json();
          renderSearchResults(data.items, false, data.has_more);
        } catch (err) {
          if (err.name === 'AbortError') return;
          resultsList.innerHTML = `<span class="admin-error" style="font-size:11px;padding:4px 0;display:block;">Search failed: ${esc(err.message)}</span>`;
          if (paginationHost) paginationHost.style.display = 'none';
        } finally {
          hideSpinner();
        }
      }, 250);
    });
  }

  if (loadMoreBtn) {
    loadMoreBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (!currentQuery || isSearching) return;
      isSearching = true;
      loadMoreBtn.disabled = true;
      loadMoreBtn.textContent = 'Loading...';
      currentPage += 1;

      try {
        const res = await fetch(`/api/model-endpoints/${epId}/catalog-search?q=${encodeURIComponent(currentQuery)}&page=${currentPage}&per_page=50`, {
          credentials: 'same-origin',
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }
        const data = await res.json();
        renderSearchResults(data.items, true, data.has_more);
      } catch (err) {
        if (typeof uiModule !== 'undefined' && uiModule?.showToast) {
          uiModule.showToast(`Failed to load more models: ${err.message}`, 4000);
        }
      } finally {
        isSearching = false;
        loadMoreBtn.disabled = false;
        loadMoreBtn.textContent = 'Load more';
      }
    });
  }
}

// ChatGPT per-endpoint usage panel expanded state persistence.
// Preserves only endpoint/auth identifiers, never tokens, secrets, or labels.
// providerAuthSessionId is ProviderAuthSession.id, independently UUID-generated
// by routes/chatgpt_subscription_routes.py, not an OAuth token or account ID.
const CHATGPT_USAGE_EXPANDED_KEY = 'odysseus-chatgpt-usage-expanded';

function _loadExpandedUsageEndpoints() {
  try {
    const raw = localStorage.getItem(CHATGPT_USAGE_EXPANDED_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      return new Set(parsed.filter(x => typeof x === 'string' && x.length > 0));
    }
  } catch (_) {}
  return new Set();
}

function _saveExpandedUsageEndpoints(set) {
  try {
    const arr = Array.from(set).filter(x => typeof x === 'string' && x.length > 0);
    localStorage.setItem(CHATGPT_USAGE_EXPANDED_KEY, JSON.stringify(arr));
  } catch (_) {}
}

function _isChatgptUsageExpanded(endpointId, providerAuthSessionId) {
  const set = _loadExpandedUsageEndpoints();
  if (endpointId != null && set.has(String(endpointId))) return true;
  if (providerAuthSessionId != null && set.has(String(providerAuthSessionId))) return true;
  return false;
}

function _setChatgptUsageExpanded(endpointId, providerAuthSessionId, expanded) {
  const set = _loadExpandedUsageEndpoints();
  const epKey = endpointId != null ? String(endpointId) : null;
  const providerAuthSessionRowId = providerAuthSessionId != null ? String(providerAuthSessionId) : null;
  if (expanded) {
    if (epKey) set.add(epKey);
    if (providerAuthSessionRowId) set.add(providerAuthSessionRowId);
  } else {
    if (epKey) set.delete(epKey);
    if (providerAuthSessionRowId) set.delete(providerAuthSessionRowId);
  }
  _saveExpandedUsageEndpoints(set);
}

async function loadEndpoints() {
  const listLocal = el('adm-epList-local');
  const listApi = el('adm-epList-api');
  _ensureEndpointBulkControls();
  // Render endpoint rows first. Do not make Added Models wait on /api/models or
  // endpoint probes; explicit Refresh/Probe actions do that work.
  const refreshDependentModelUi = (force = false) => {
    setTimeout(() => {
      if (window.modelsModule && window.modelsModule.refreshModels) {
        window.modelsModule.refreshModels(!!force, force ? {} : { cacheOnly: true }).then(() => {
          if (window.sessionModule && window.sessionModule.updateModelPicker) {
            window.sessionModule.updateModelPicker();
          }
        }).catch(() => {});
      }
      if (settingsModule && typeof settingsModule.refreshAiModelEndpoints === 'function') {
        settingsModule.refreshAiModelEndpoints();
      }
    }, 0);
  };
  try {
    const res = await fetch('/api/model-endpoints', { credentials: 'same-origin' });
    // A non-OK response (401/403 for non-admins) shows the empty state, not "Failed to load".
    let data = [];
    if (res.ok) {
      try { data = await res.json(); } catch { data = []; }
    }
    if (!Array.isArray(data) || data.length === 0) {
      const empty = '<div class="admin-empty">None</div>';
      if (listLocal) listLocal.innerHTML = empty;
      if (listApi) listApi.innerHTML = '<div class="admin-empty">None</div>';
      refreshDependentModelUi();
      return;
    }
    const rowHtml = data.map(ep => {
      const epModels = Array.isArray(ep.models) ? ep.models : [];
      const pinnedModels = Array.isArray(ep.pinned_models) ? ep.pinned_models : [];
      const visibleCount = ep.picker_requires_pinning ? pinnedModels.length : epModels.length;
      const totalCount = Number.isFinite(Number(ep.model_count))
        ? Number(ep.model_count)
        : visibleCount + (ep.hidden_count || 0);
      // `ep.models` is the *visible* set — when every model is hidden it's
      // empty, but we still need to render the expand panel so the user can
      // un-hide them. Gate on the total instead.
      const isChatgptAccount = isChatgptSubscriptionEndpoint(ep);
      const isFeatherless = isFeatherlessEndpoint(ep);
      const hasModels = ep.online && (totalCount > 0 || isFeatherless);
      const countText = (isChatgptAccount || isFeatherless)
        ? `${visibleCount} models enabled`
        : `${visibleCount}/${totalCount} models enabled`;
      const statusBadge = ep.status === 'empty'
        ? '<span class="admin-badge">no models</span>'
        : ep.online
          ? `<span class="admin-badge" data-adm-ep-models-count="${ep.id}">${countText}</span>`
          : '<span class="admin-badge admin-badge-off">offline</span>';
      const justAddedClass = (_recentlyAddedEpId && String(ep.id) === _recentlyAddedEpId) ? ' adm-ep-just-added' : '';
      const category = ep.category || (_isLocalEndpoint(ep.base_url) ? 'local' : 'api');
      const kindLabel = ep.endpoint_kind && ep.endpoint_kind !== 'auto' ? ep.endpoint_kind.toUpperCase() : '';
      const isUsageExpanded = isChatgptAccount && _isChatgptUsageExpanded(ep.id, ep.provider_auth_id);
      const epTitle = isChatgptAccount
        ? chatgptAccountTitle(ep)
        : (isFeatherless && (!ep.name || ep.name === 'api.featherless.ai') ? 'Featherless.ai' : ep.name);
      return `
        <div class="admin-user-row${ep.is_enabled ? '' : ' admin-ep-disabled'}${justAddedClass}" data-adm-ep-id="${ep.id}">
          <div style="display:flex;align-items:center;justify-content:space-between;${hasModels ? 'cursor:pointer;' : ''}padding:4px 0;" data-adm-ep-header="${ep.id}">
            <div class="admin-user-info" style="flex:1;flex-wrap:wrap;gap:0.3rem;align-items:center;">
              ${_endpointSelectMode ? `<label class="adm-model-row adm-endpoint-select-label" title="Select ${esc(ep.name)}">
                <input type="checkbox" class="adm-cb-hidden" data-adm-ep-select="${ep.id}" aria-label="Select ${esc(ep.name)}" ${_selectedEndpointIds.has(String(ep.id)) ? 'checked' : ''}>
                <span class="adm-check-dot adm-endpoint-select-dot" aria-hidden="true"></span>
              </label>` : ''}
              <span class="adm-ep-row-logo" style="display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;flex-shrink:0;opacity:0.9;">${providerLogoFromUrl(ep.base_url) || ''}</span>
              <span class="admin-user-name">${esc(epTitle)}</span>
              ${ep.model_type === 'image' ? '<span class="admin-badge" style="background:color-mix(in srgb, var(--accent) 20%, transparent);color:var(--accent);">Image</span>' : ''}
              ${kindLabel ? `<span class="admin-badge">${esc(kindLabel)}</span>` : ''}
              ${statusBadge}
              ${ep.is_enabled ? '' : '<span class="admin-badge admin-badge-off">disabled</span>'}
              ${hasModels ? `<span style="font-size:10px;opacity:0.4;${category === 'api' ? 'flex-basis:100%;' : ''}">Click to manage models</span>` : ''}
            </div>
            <div style="display:flex;gap:4px;align-items:center;">
              ${_endpointSelectMode ? '' : `
                <button class="admin-btn-sm" data-adm-toggle-ep="${ep.id}">${ep.is_enabled ? 'Disable' : 'Enable'}</button>
                <button class="admin-btn-delete" data-adm-del-ep="${ep.id}" data-adm-ep-online="${ep.online ? '1' : '0'}">Delete</button>
                ${hasModels ? '<svg class="admin-user-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.3;transition:transform 0.2s,opacity 0.2s;"><polyline points="6 9 12 15 18 9"/></svg>' : ''}`}
            </div>
          </div>
          ${isChatgptAccount ? `
          <div class="adm-chatgpt-controls">
            <button type="button" class="admin-btn-sm adm-chatgpt-usage-toggle" data-adm-chatgpt-usage-toggle="${esc(ep.provider_auth_id)}" data-chatgpt-endpoint-id="${esc(ep.id)}" aria-expanded="${isUsageExpanded ? 'true' : 'false'}" aria-controls="adm-chatgpt-usage-${esc(ep.id)}">
              Usage <span class="adm-chatgpt-usage-chevron" aria-hidden="true">${isUsageExpanded ? '▴' : '▾'}</span>
            </button>
            <button type="button" class="admin-btn-sm" data-adm-chatgpt-reconnect="${esc(ep.provider_auth_id)}" data-chatgpt-endpoint-id="${esc(ep.id)}">Reconnect</button>
          </div>
          <div id="adm-chatgpt-usage-${esc(ep.id)}" class="adm-chatgpt-usage-host${isUsageExpanded ? '' : ' hidden'}" data-adm-chatgpt-usage-host="${esc(ep.provider_auth_id)}" data-chatgpt-endpoint-id="${esc(ep.id)}"${isUsageExpanded ? '' : ' style="display:none;"'}><div class="adm-chatgpt-usage adm-chatgpt-usage-loading"><div class="adm-chatgpt-usage-status">Loading usage...</div></div></div>` : ''}
          ${endpointDetailHtml(ep, category)}
          ${hasModels ? `<div class="mcp-tools-panel hidden" data-adm-ep-models-panel="${ep.id}"></div>` : ''}
        </div>`;
    });
    // Partition rows into Local vs API for the split sections.
    // Subsections without any rows are hidden entirely (heading + all)
    // so empty groups don't take up vertical real estate.
    const _renderInto = (container, indices) => {
      if (!container) return;
      const section = container.closest('.adm-ep-section');
      if (!indices.length) {
        if (section) section.style.display = 'none';
        container.innerHTML = '';
        return;
      }
      if (section) section.style.display = '';
      container.innerHTML = indices.map(i => rowHtml[i]).join('');
    };
    const localIdx = [], apiIdx = [];
    data.forEach((ep, i) => ((ep.category || (_isLocalEndpoint(ep.base_url) ? 'local' : 'api')) === 'local' ? localIdx : apiIdx).push(i));
    // Sort each section: enabled endpoints first, disabled at the bottom.
    // Preserve original order within each group via stable sort.
    const _sortByEnabled = (a, b) => Number(!!data[b].is_enabled) - Number(!!data[a].is_enabled);
    localIdx.sort(_sortByEnabled);
    apiIdx.sort(_sortByEnabled);
    _renderInto(listLocal, localIdx);
    _renderInto(listApi, apiIdx);
    const availableIds = new Set(data.map(ep => String(ep.id)));
    Array.from(_selectedEndpointIds).forEach(id => {
      if (!availableIds.has(String(id))) _selectedEndpointIds.delete(id);
    });
    _updateEndpointBulkControls();
    // Iterate matching nodes across both containers.
    const queryAll = (sel) => {
      const out = [];
      [listLocal, listApi].forEach(c => {
        if (c) c.querySelectorAll(sel).forEach(n => out.push(n));
      });
      return out;
    };
    // One usage card per ChatGPT account: each fetch targets that card's own
    // auth id, so account A's refresh can never repaint account B.
    queryAll('[data-adm-chatgpt-usage-host]').forEach(host => {
      host.addEventListener('click', (e) => e.stopPropagation());
      const epId = host.dataset.chatgptEndpointId;
      const authId = host.dataset.admChatgptUsageHost;
      if (_isChatgptUsageExpanded(epId, authId)) {
        _loadChatgptUsage(host, host.dataset.admChatgptUsageHost, host.dataset.chatgptEndpointId);
      }
    });
    queryAll('[data-adm-chatgpt-usage-toggle]').forEach(toggleBtn => {
      toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const epId = toggleBtn.dataset.chatgptEndpointId;
        const authId = toggleBtn.dataset.admChatgptUsageToggle;
        const row = toggleBtn.closest('.admin-user-row');
        const host = row ? row.querySelector('[data-adm-chatgpt-usage-host]') : null;
        if (!host) return;
        const isHidden = host.classList.contains('hidden') || host.style.display === 'none';
        if (isHidden) {
          host.classList.remove('hidden');
          host.style.display = '';
          toggleBtn.setAttribute('aria-expanded', 'true');
          const chevron = toggleBtn.querySelector('.adm-chatgpt-usage-chevron');
          if (chevron) chevron.textContent = '▴';
          _setChatgptUsageExpanded(epId, authId, true);
          if (!host.dataset.usageLoaded) {
            _loadChatgptUsage(host, authId, epId);
          }
        } else {
          host.classList.add('hidden');
          host.style.display = 'none';
          toggleBtn.setAttribute('aria-expanded', 'false');
          const chevron = toggleBtn.querySelector('.adm-chatgpt-usage-chevron');
          if (chevron) chevron.textContent = '▾';
          _setChatgptUsageExpanded(epId, authId, false);
        }
      });
    });
    queryAll('.adm-chatgpt-controls [data-adm-chatgpt-reconnect]').forEach(reconnectBtn => {
      reconnectBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const epId = reconnectBtn.dataset.chatgptEndpointId;
        const authId = reconnectBtn.dataset.admChatgptReconnect;
        const row = reconnectBtn.closest('.admin-user-row');
        const host = row ? row.querySelector('[data-adm-chatgpt-usage-host]') : null;
        if (host) {
          host.classList.remove('hidden');
          host.style.display = '';
          const toggleBtn = row ? row.querySelector('[data-adm-chatgpt-usage-toggle]') : null;
          if (toggleBtn) {
            toggleBtn.setAttribute('aria-expanded', 'true');
            const chevron = toggleBtn.querySelector('.adm-chatgpt-usage-chevron');
            if (chevron) chevron.textContent = '▴';
          }
          _setChatgptUsageExpanded(epId, authId, true);
          await _reconnectChatgptAccount(host, authId, epId);
        }
      });
    });
    queryAll('[data-adm-toggle-ep]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await fetch(`/api/model-endpoints/${btn.dataset.admToggleEp}`, { method: 'PATCH' });
        await _refreshAfterEndpointChange();
        loadEndpoints();
      });
    });
    queryAll('[data-adm-copy-url]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const url = btn.dataset.admCopyUrl || '';
        if (!url) return;
        uiModule.copyToClipboard(url).then(() => {
          const prev = btn.innerHTML;
          btn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
          btn.style.opacity = '1';
          setTimeout(() => { btn.innerHTML = prev; btn.style.opacity = ''; }, 1400);
        });
      });
    });
    queryAll('[data-adm-del-ep]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        var epId = btn.dataset.admDelEp;
        var isOffline = btn.dataset.admEpOnline === '0';
        // Offline endpoints are already broken, so they skip the confirm dialog.
        if (!isOffline) {
          var deps = [];
          try {
            var depRes = await fetch('/api/model-endpoints/' + epId + '/dependents', { credentials: 'same-origin' });
            var depData = await depRes.json();
            deps = depData.dependents || [];
          } catch (e) { /* proceed without warning */ }
          var msg = 'Delete this endpoint?';
          if (deps.length) {
            msg += '\n\nThe following settings use this endpoint and will be reset:\n— ' + deps.join('\n— ');
          }
          if (!await uiModule.styledConfirm(msg, { confirmText: 'Delete', danger: true })) return;
        }
        // Optimistic: remove from UI immediately
        const row = btn.closest('[data-adm-ep-id]');
        if (row) row.remove();
        fetch('/api/model-endpoints/' + epId, { method: 'DELETE' })
          .then(() => _refreshAfterEndpointChange(epId))
          .then(() => loadEndpoints())
          .catch(() => loadEndpoints());
      });
    });
    queryAll('[data-adm-ep-select]').forEach(cb => {
      cb.addEventListener('click', e => e.stopPropagation());
      cb.addEventListener('change', () => {
        const id = String(cb.dataset.admEpSelect || '');
        if (cb.checked) _selectedEndpointIds.add(id);
        else _selectedEndpointIds.delete(id);
        _updateEndpointBulkControls();
      });
    });
    // Clear the marker so the glow does not re-fire on the next loadEndpoints().
    if (_recentlyAddedEpId) _recentlyAddedEpId = null;
    // Models expand/collapse (click anywhere on card)
    queryAll('[data-adm-ep-id]').forEach(row => {
      const header = row.querySelector('[data-adm-ep-header]');
      if (!header) return;
      let _modelsLoaded = false;
      row.style.cursor = 'pointer';
      row.addEventListener('click', async (e) => {
        if (_endpointSelectMode && !e.target.closest('button, input, select, a, label')) {
          const cb = row.querySelector('[data-adm-ep-select]');
          if (cb) {
            cb.checked = !cb.checked;
            cb.dispatchEvent(new Event('change'));
          }
          return;
        }
        // Clicks inside the expanded panel must not toggle it.
        if (e.target.closest('.admin-btn-sm, .admin-btn-delete, .mcp-tools-list, .mcp-tools-header, .mcp-tools-search, input, select, label, button, .featherless-panel, .featherless-search-bar, [data-ep-model-row]')) return;
        const epId = header.dataset.admEpHeader;
        const panel = row.querySelector(`[data-adm-ep-models-panel="${epId}"]`);
        if (!panel) return;
        panel.classList.toggle('hidden');
        const chevron = row.querySelector('.admin-user-chevron');
        const isOpen = !panel.classList.contains('hidden');
        if (chevron) {
          chevron.style.transform = isOpen ? 'rotate(180deg)' : '';
          chevron.style.opacity = isOpen ? '0.7' : '0.3';
        }
        if (!_modelsLoaded && isOpen) {
          _modelsLoaded = true;
          const ep = data.find(x => String(x.id) === String(epId));
          if (ep && isFeatherlessEndpoint(ep)) {
            renderFeatherlessPanel(panel, ep, row);
            return;
          }
          // Our shared whirlpool spinner (consistent with the rest of the app).
          panel.innerHTML = '';
          let _modelsSpin = null;
          const _ld = document.createElement('span');
          _ld.style.cssText = 'opacity:0.55;font-size:11px;display:inline-flex;align-items:center;gap:8px;';
          _ld.appendChild(document.createTextNode('Loading models…'));
          try {
            const _sp = (await import('./spinner.js')).default;
            _modelsSpin = _sp.createWhirlpool(14);
            _modelsSpin.element.style.cssText = 'width:14px;height:14px;margin:0;display:inline-block;';
            _ld.appendChild(_modelsSpin.element);
          } catch (_) {}
          panel.appendChild(_ld);
          const _stopSpin = () => { try { _modelsSpin && _modelsSpin.stop(); } catch (_) {} };
          const _loadingHtml = (label) => `<span style="opacity:0.55;font-size:11px;display:inline-flex;align-items:center;gap:8px;">${esc(label)}</span>`;
          const renderModels = (models, warning = '') => {
            const sortedModels = sortModelObjects(models);
            const usesPinnedPicker = sortedModels.some(m => !!m.picker_requires_pinning);
            panel.dataset.pickerMode = usesPinnedPicker ? 'pinned' : 'hidden';
            const warningHtml = warning ? `<div class="admin-error" style="font-size:11px;margin:6px 0;">${esc(warning)}</div>` : '';
            const attachRefresh = () => {
              panel.querySelector(`[data-ep-refresh-models="${epId}"]`)?.addEventListener('click', async (e) => {
                e.preventDefault();
                panel.innerHTML = _loadingHtml('Refreshing models...');
                try {
                  const res = await fetch(`/api/model-endpoints/${epId}/models?refresh=true&refresh_timeout=60`, { credentials: 'same-origin' });
                  const refreshWarning = res.headers.get('X-Model-Refresh-Warning') || '';
                  if (!res.ok) throw new Error(`HTTP ${res.status}`);
                  const refreshedModels = await res.json();
                  renderModels(refreshedModels, refreshWarning);
                  _refreshAfterEndpointChange();
                  if (refreshWarning && uiModule?.showToast) uiModule.showToast(refreshWarning, 6000);
                } catch (_) {
                  renderModels(sortedModels, 'Model refresh failed; kept cached models.');
                }
              });
            };
            if (!sortedModels.length) {
              panel.innerHTML = `<div class="mcp-tools-header">
                <span>Models</span>
                <span style="display:flex;gap:8px;align-items:center;">
                  <a href="#" data-ep-refresh-models="${epId}">Refresh</a>
                </span>
              </div>${warningHtml}<span style="opacity:0.5;font-size:11px;">No models</span>`;
              attachRefresh();
              return;
            }
            const enabledCount = usesPinnedPicker
              ? sortedModels.filter(m => m.is_pinned).length
              : sortedModels.filter(m => !m.is_hidden).length;
            const showSearch = sortedModels.length >= 8;
            panel.innerHTML = `<div class="mcp-tools-header">
              <span>Models</span>
              <span style="display:flex;gap:8px;align-items:center;">
                <a href="#" data-ep-refresh-models="${epId}">Refresh</a>
                <a href="#" data-ep-select-all="${epId}">All</a>
                <a href="#" data-ep-select-none="${epId}">None</a>
              </span>
            </div>${warningHtml}${showSearch ? `<input type="search" class="mcp-tools-search" placeholder="Search ${sortedModels.length} models..." data-ep-search="${epId}">` : ''}<div class="mcp-tools-list">` + sortedModels.map(m => {
              const mode = ['none', 'compact', 'full'].includes(String(m.tool_mode || '').toLowerCase())
                ? String(m.tool_mode).toLowerCase()
                : '';
              return `<div title="${esc(m.id)}" data-ep-model-row data-search="${esc((m.display + ' ' + m.id).toLowerCase())}" class="adm-model-row">
                <label class="adm-model-label">
                  <input type="checkbox" class="adm-cb-hidden" data-ep-model-id="${esc(m.id)}" ${(usesPinnedPicker ? m.is_pinned : !m.is_hidden) ? 'checked' : ''}>
                  <span class="adm-check-dot" aria-hidden="true"></span>
                  <span class="adm-model-name">${esc(m.display)}</span>
                </label>
                <div class="adm-model-tools-col">
                  <span class="adm-model-tools-label" title="Select the tool schema profile for this model">Tools</span>
                  <select class="adm-model-tool-mode admin-tools-select" data-ep-model-id="${esc(m.id)}" data-original-tool-mode="${esc(m.tool_mode || '')}" data-tool-mode-touched="0" title="Auto uses Odysseus compact for Odysseus/Ajax names and Regular tools for every other model">
                    <option value="" ${mode === '' ? 'selected' : ''}>Auto</option>
                    <option value="full" ${mode === 'full' ? 'selected' : ''}>Regular tools</option>
                    <option value="compact" ${mode === 'compact' ? 'selected' : ''}>Odysseus compact</option>
                    <option value="none" ${mode === 'none' ? 'selected' : ''}>Tools off</option>
                  </select>
                </div>
              </div>`;
            }
            ).join('') + '</div>';
            const filterRows = (q) => {
              const needle = q.trim().toLowerCase();
              panel.querySelectorAll('[data-ep-model-row]').forEach(row => {
                row.style.display = (!needle || row.dataset.search.includes(needle)) ? '' : 'none';
              });
            };
            attachRefresh();
            panel.querySelector(`[data-ep-search="${epId}"]`)?.addEventListener('input', (e) => filterRows(e.target.value));
            panel.querySelector(`[data-ep-select-all="${epId}"]`)?.addEventListener('click', (e) => {
              e.preventDefault();
              panel.querySelectorAll('[data-ep-model-row]').forEach(row => {
                if (row.style.display !== 'none') row.querySelector('input[type=checkbox]').checked = true;
              });
              _saveEpModelState(epId, panel);
            });
            panel.querySelector(`[data-ep-select-none="${epId}"]`)?.addEventListener('click', (e) => {
              e.preventDefault();
              panel.querySelectorAll('[data-ep-model-row]').forEach(row => {
                if (row.style.display !== 'none') row.querySelector('input[type=checkbox]').checked = false;
              });
              _saveEpModelState(epId, panel);
            });
            panel.querySelectorAll('input[type=checkbox]').forEach(cb => {
              cb.addEventListener('change', () => _saveEpModelState(epId, panel));
            });
            panel.querySelectorAll('.adm-model-tool-mode').forEach(sel => {
              sel.addEventListener('change', () => {
                sel.dataset.toolModeTouched = '1';
                _saveEpModelState(epId, panel);
              });
            });
          };
          try {
            const res = await fetch(`/api/model-endpoints/${epId}/models`, { credentials: 'same-origin' });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const models = await res.json();
            _stopSpin();
            renderModels(models);
          } catch (e) { _stopSpin(); panel.innerHTML = '<span class="admin-error" style="font-size:11px;">Failed to load models</span>'; }
        }
      });
    });
    refreshDependentModelUi();
  } catch (e) {
    const err = '<div class="admin-error">Failed to load</div>';
    [listLocal, listApi].forEach(c => { if (c) c.innerHTML = err; });
  }
}

async function _saveEpModelState(epId, panel) {
  const hidden = [];
  const pinned = [];
  const modelToolModes = {};
  const usesPinnedPicker = panel && panel.dataset && panel.dataset.pickerMode === 'pinned';
  panel.querySelectorAll('input.adm-cb-hidden[type=checkbox]').forEach(cb => {
    if (cb.checked) pinned.push(cb.dataset.epModelId);
    else hidden.push(cb.dataset.epModelId);
  });
  panel.querySelectorAll('.adm-model-tool-mode').forEach(sel => {
    const modelId = sel.dataset.epModelId || '';
    const value = String(sel.value || '').toLowerCase();
    const original = String(sel.dataset.originalToolMode || '').toLowerCase();
    if (modelId && (sel.dataset.toolModeTouched === '1' || original)) {
      modelToolModes[modelId] = ['none', 'compact', 'full'].includes(value) ? value : '';
    }
  });
  const total = panel.querySelectorAll('input.adm-cb-hidden[type=checkbox]').length;
  const enabled = usesPinnedPicker ? pinned.length : total - hidden.length;
  const body = usesPinnedPicker ? { pinned_models: pinned } : { hidden };
  if (Object.keys(modelToolModes).length) body.model_tool_modes = modelToolModes;
  try {
    await fetch(`/api/model-endpoints/${epId}/models`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(body),
    });
    const row = panel.closest('[data-adm-ep-id]');
    if (row) {
      const badge = row.querySelector('.admin-badge');
      if (badge && !badge.classList.contains('admin-badge-off')) {
        const match = String(badge.textContent || '').match(/\/(\d+)/);
        const canonicalTotal = match ? Number(match[1]) : total;
        badge.textContent = `${enabled}/${canonicalTotal} models enabled`;
      }
    }
    if (settingsModule && typeof settingsModule.refreshAiModelEndpoints === 'function') {
      settingsModule.refreshAiModelEndpoints();
    }
    _refreshAfterEndpointChange();
  } catch (e) { console.warn('Failed to save endpoint model state', epId, e); }
}

// Render the shared "waiting for authorization" panel (code + manual link).
// Built for both the Add Models flow and per-account Reconnect. Never opens a
// tab automatically; the user clicks the Authorize link.
function _renderDeviceAuthWaitPanel(status, providerKey, start, authUrl) {
  if (!status) return;
  status.className = '';
  const authLabel = providerKey === 'copilot' ? 'Authorize on GitHub' : 'Authorize with OpenAI';
  const waitLabel = providerKey === 'copilot' ? 'Waiting for GitHub authorization...' : 'Waiting for ChatGPT authorization...';
  status.innerHTML =
    '<div class="adm-copilot-panel">' +
      '<div class="adm-copilot-wait"><span class="admin-spinner"></span>' +
        '<span>' + esc(waitLabel) + '</span></div>' +
      '<div class="adm-copilot-coderow">' +
        '<span class="adm-copilot-code-label">Code</span>' +
        '<code class="adm-copilot-code">' + esc(start.user_code) + '</code>' +
        '<button type="button" class="admin-btn-sm adm-device-auth-copy">Copy</button>' +
      '</div>' +
      '<a class="admin-btn-add adm-copilot-auth" href="' + esc(authUrl || '') + '" target="_blank" rel="noopener">' + esc(authLabel) + ' ↗</a>' +
    '</div>';
  const copyBtn = status.querySelector('.adm-device-auth-copy');
  if (copyBtn) copyBtn.addEventListener('click', async () => {
    const ok = await uiModule.copyToClipboard(start.user_code || '', { toast: false });
    copyBtn.textContent = ok ? 'Copied' : 'Failed';
    setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
  });
}

// ── ChatGPT Subscription per-account usage + reconnect ─────────────────────
// Each ChatGPT account (ProviderAuthSession) is addressed by its stable
// auth id; the endpoint id pins which row the action came from. Usage is
// read-only telemetry: a failed read never disables the endpoint.
const _chatgptReconnectInflight = new Set();

async function _loadChatgptUsage(container, authId, epId, { refresh = false } = {}) {
  if (!container || !authId) return;
  const url = '/api/chatgpt-subscription/accounts/' + encodeURIComponent(authId) + '/usage' + (refresh ? '?refresh=1' : '');
  let payload = null;
  try {
    const res = await fetch(url, { credentials: 'same-origin' });
    if (res.ok) {
      try { payload = await res.json(); } catch (_) { payload = null; }
    } else {
      let reason = 'upstream';
      if (res.status === 404) reason = 'upstream';
      payload = { available: false, reason, account: { auth_id: authId } };
    }
  } catch (_) {
    payload = { available: false, reason: 'network', account: { auth_id: authId } };
  }
  if (!payload || typeof payload !== 'object') payload = { available: false, reason: 'malformed', account: { auth_id: authId } };
  const vm = buildChatgptUsageViewModel(payload);
  vm.authId = authId;
  if (!container.dataset) container.dataset = {};
  container.dataset.usageLoaded = '1';
  container.innerHTML = renderChatgptUsageCardHtml(vm, { esc, endpointId: epId, includeReconnect: false });
  const refreshBtn = container.querySelector('[data-adm-chatgpt-usage-refresh]');
  if (refreshBtn) refreshBtn.addEventListener('click', async (e) => {
    e.stopPropagation();
    refreshBtn.disabled = true;
    refreshBtn.textContent = 'Refreshing...';
    await _loadChatgptUsage(container, refreshBtn.dataset.admChatgptUsageRefresh, refreshBtn.dataset.chatgptEndpointId, { refresh: true });
  });
  const reconnectBtn = container.querySelector('[data-adm-chatgpt-reconnect]');
  if (reconnectBtn) reconnectBtn.addEventListener('click', async (e) => {
    e.stopPropagation();
    await _reconnectChatgptAccount(container, reconnectBtn.dataset.admChatgptReconnect, reconnectBtn.dataset.chatgptEndpointId);
  });
}

async function _reconnectChatgptAccount(container, authId, epId) {
  if (!container || !authId) return;
  if (_chatgptReconnectInflight.has(authId)) return;
  _chatgptReconnectInflight.add(authId);
  const status = document.createElement('div');
  status.className = 'adm-chatgpt-reconnect-status';
  const actions = container.querySelector('.adm-chatgpt-usage-actions');
  if (actions) actions.replaceWith(status); else container.appendChild(status);
  status.textContent = 'Starting ChatGPT sign-in...';
  try {
    // Reconnect targets exactly this auth session + endpoint. The backend
    // re-checks ownership on start and on every poll.
    const formData = new FormData();
    formData.append('reconnect_auth_id', authId);
    if (epId) formData.append('reconnect_endpoint_id', epId);
    const result = await runProviderDeviceFlow('chatgpt-subscription', {
      openWindow: () => {},
      formData,
      onStart: ({ start, authUrl }) => _renderDeviceAuthWaitPanel(status, 'chatgpt-subscription', start, authUrl),
    });
    if (result.status === 'authorized') {
      status.className = 'admin-success';
      status.textContent = 'Reconnected.';
      await loadEndpoints();
      return;
    }
    status.className = 'admin-error';
    status.textContent = result.status === 'expired'
      ? 'Authorization expired.'
      : 'Authorization failed (' + (result.error || 'denied') + ').';
  } catch (e) {
    status.className = 'admin-error';
    status.textContent = formatDeviceFlowError(e);
  } finally {
    _chatgptReconnectInflight.delete(authId);
    // Re-render the card so Refresh/Reconnect buttons come back.
    setTimeout(() => { _loadChatgptUsage(container, authId, epId); }, 1200);
  }
}

function initEndpointForm() {
  const provider = el('adm-epProvider');
  const urlInput = el('adm-epUrl');
  const kindSel = el('adm-epKind');

  // Custom provider picker; mirrors the hidden <select id="adm-epProvider">, which the rest of this function reads.
  const picker = el('adm-provider-picker');
  const pickerBtn = el('adm-provider-btn');
  const pickerMenu = el('adm-provider-menu');
  const pickerCurrent = picker ? picker.querySelector('.adm-provider-current') : null;
  const DEVICE_AUTH_PROVIDER_VALUES = new Set(Object.keys(PROVIDER_DEVICE_FLOWS));
  let deviceAuthPolling = false;
  // True while the URL box is repurposed as the ChatGPT account-label input.
  let _chatgptLabelMode = false;
  function _selectedProviderOption() {
    return provider && provider.selectedOptions ? provider.selectedOptions[0] : null;
  }
  function _selectedDeviceAuthProvider() {
    const opt = _selectedProviderOption();
    const flow = opt && opt.dataset ? opt.dataset.authFlow : '';
    if (flow && DEVICE_AUTH_PROVIDER_VALUES.has(flow)) return flow;
    return DEVICE_AUTH_PROVIDER_VALUES.has(provider.value) ? provider.value : '';
  }
  function _isDeviceAuthSelected() {
    return !!_selectedDeviceAuthProvider();
  }
  function _setApiFormForProvider() {
    const deviceAuthProvider = _selectedDeviceAuthProvider();
    const deviceAuthConfig = PROVIDER_DEVICE_FLOWS[deviceAuthProvider] || null;
    const apiKey = el('adm-epApiKey');
    const testBtn = el('adm-epApiTestBtn');
    const addBtn = el('adm-epAddBtn');
    const status = el('adm-deviceAuthStatus');
    const msg = _endpointMsg('api');
    if (deviceAuthConfig) {
      if (deviceAuthProvider === 'chatgpt-subscription') {
        // The URL box doubles as the optional account label so several
        // ChatGPT subscriptions stay distinguishable ("ChatGPT · codex00").
        if (!_chatgptLabelMode) urlInput.value = '';
        urlInput.placeholder = 'Account label, e.g. codex00 (optional)';
        urlInput.readOnly = false;
        urlInput.maxLength = 40;
        urlInput.setAttribute('aria-label', 'ChatGPT account label (optional)');
        _chatgptLabelMode = true;
      } else {
        _chatgptLabelMode = false;
        urlInput.value = '';
        urlInput.placeholder = 'GitHub Copilot uses GitHub account sign-in';
        urlInput.readOnly = true;
        urlInput.removeAttribute('maxlength');
      }
      if (apiKey) {
        apiKey.value = '';
        apiKey.placeholder = 'No API key needed';
        apiKey.disabled = true;
      }
      if (testBtn) {
        testBtn.disabled = true;
        testBtn.style.opacity = '0.45';
        testBtn.style.cursor = 'not-allowed';
      }
      if (addBtn) {
        addBtn.disabled = false;
        addBtn.textContent = 'Add';
        addBtn.style.width = '55px';
        addBtn.style.display = '';
      }
      if (kindSel) kindSel.value = 'api';
      if (msg) {
        msg.textContent = '';
        msg.className = '';
      }
    } else {
      if (_chatgptLabelMode) urlInput.value = '';
      _chatgptLabelMode = false;
      urlInput.placeholder = 'Base URL or pick provider';
      urlInput.readOnly = false;
      urlInput.removeAttribute('maxlength');
      urlInput.setAttribute('aria-label', 'Model endpoint URL');
      if (apiKey) {
        apiKey.placeholder = 'API key';
        apiKey.disabled = false;
      }
      if (testBtn) {
        testBtn.disabled = false;
        testBtn.style.opacity = '';
        testBtn.style.cursor = '';
      }
      if (addBtn) {
        addBtn.disabled = false;
        addBtn.textContent = 'Add';
        addBtn.style.width = '55px';
        addBtn.style.display = '';
      }
      if (msg) {
        msg.textContent = '';
        msg.className = '';
      }
      if (!deviceAuthPolling && status) status.textContent = '';
    }
  }
  function _renderPickerMenu() {
    if (!pickerMenu) return;
    pickerMenu.innerHTML = Array.from(provider.options).map(o => {
      const logo = o.dataset.logo ? (providerLogo(o.dataset.logo) || '') : '';
      const active = o.value === provider.value ? ' active' : '';
      return `<div class="adm-provider-item${active}" role="option" data-value="${o.value.replace(/"/g, '&quot;')}">
        <span class="adm-provider-logo">${logo}</span>
        <span>${o.textContent}</span>
      </div>`;
    }).join('');
  }
  function _syncPickerCurrent() {
    if (!pickerCurrent) return;
    const opt = provider.selectedOptions[0] || provider.options[0];
    const logo = opt.dataset.logo ? (providerLogo(opt.dataset.logo) || '') : '';
    pickerCurrent.querySelector('.adm-provider-logo').innerHTML = logo;
    pickerCurrent.querySelector('.adm-provider-name').textContent = opt.textContent;
  }
  if (picker && pickerBtn && pickerMenu && pickerCurrent) {
    _renderPickerMenu();
    _syncPickerCurrent();
    if (provider.value && !urlInput.value) urlInput.value = provider.value;
    pickerBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      pickerMenu.classList.toggle('hidden');
    });
    pickerMenu.addEventListener('click', (e) => {
      const item = e.target.closest('.adm-provider-item');
      if (!item) return;
      provider.value = item.dataset.value;
      provider.dispatchEvent(new Event('change', { bubbles: true }));
      pickerMenu.classList.add('hidden');
      _renderPickerMenu();
      _syncPickerCurrent();
    });
    document.addEventListener('click', (e) => {
      if (!picker.contains(e.target)) pickerMenu.classList.add('hidden');
    });
    // Capture-phase Esc: dismiss the picker menu without bubbling to the
    // settings-modal handler that would otherwise close the whole modal.
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      if (pickerMenu.classList.contains('hidden')) return;
      e.stopPropagation();
      pickerMenu.classList.add('hidden');
    }, { capture: true });
  }

  provider.addEventListener('change', () => {
    if (_isDeviceAuthSelected()) {
      _setApiFormForProvider();
      _renderPickerMenu();
      _syncPickerCurrent();
      return;
    }
    if (provider.value) urlInput.value = provider.value;
    else urlInput.value = '';
    if (kindSel) kindSel.value = provider.value ? 'api' : 'proxy';
    _setApiFormForProvider();
  });
  urlInput.addEventListener('input', () => {
    // Typing an account label must not flip the picker back to "Custom URL".
    if (_isDeviceAuthSelected()) return;
    if (provider.value && urlInput.value.trim() !== provider.value) {
      provider.value = '';
      if (kindSel) kindSel.value = 'api';
      _renderPickerMenu();
      _syncPickerCurrent();
    }
  });
  if (kindSel) kindSel.value = kindSel.value || 'api';
  function _apiEndpointKind() {
    return (kindSel && kindSel.value) ? kindSel.value : 'api';
  }
  function _modelRefreshModeForApiEndpoint(url, endpointKind) {
    if (endpointKind === 'proxy') return 'manual';
    try {
      if ((new URL(url)).hostname.toLowerCase() === 'generativelanguage.googleapis.com') return '';
    } catch (_) {}
    return 'auto';
  }
  function _normalizeBaseUrl(raw) {
    let u = raw.trim();
    // Fix common protocol typos
    u = u.replace(/^https?:\/(?!\/)/, m => m + '/');  // https:/ → https://
    u = u.replace(/^htp:/, 'http:').replace(/^htps:/, 'https:');
    u = u.replace(/^http:\/\/\//, 'http://');  // http:/// → http://
    u = u.replace(/^https:\/\/\//, 'https://');
    // Add http:// if no protocol
    if (!/^https?:\/\//.test(u)) u = 'http://' + u;
    // Strip trailing slashes
    u = u.replace(/\/+$/, '');
    // Strip trailing paths that shouldn't be in a base URL
    u = u.replace(/\/v1\/(models|chat\/completions|completions|messages)\/?$/i, '/v1');
    u = u.replace(/\/(models|chat\/completions|completions|v1\/messages)\/?$/i, '');
    u = u.replace(/\/api\/(chat|tags|generate)\/?$/i, '/api');
    // Fix double /v1/v1
    u = u.replace(/\/v1\/v1$/, '/v1');
    // Strip query params and fragments
    u = u.split('?')[0].split('#')[0];
    try {
      const parsed = new URL(u);
      if (parsed.hostname.endsWith('ollama.com')) {
        u = 'https://ollama.com/api';
      }
    } catch(e) {}
    // Ensure /v1 suffix for bare host:port URLs (not cloud providers)
    if (!u.includes('api.') && !u.includes('openrouter') && !u.includes('opencode.ai') && !u.includes('ollama.com') && !u.endsWith('/v1')) {
      try {
        const parsed = new URL(u);
        if (!parsed.pathname || parsed.pathname === '/') {
          u += '/v1';
        }
      } catch(e) {}
    }
    return u;
  }

  async function _defaultOllamaUrl() {
    try {
      const res = await fetch('/api/runtime', { credentials: 'same-origin' });
      if (res.ok) {
        const data = await res.json();
        if (data && data.ollama_base_url) return data.ollama_base_url;
      }
    } catch (_) {}
    return 'http://127.0.0.1:11434/v1';
  }

  function _renderEndpointTestResult(msg, res, d) {
    const isFeatherless = d && d.base_url && /featherless\.ai/i.test(d.base_url);
    if (res.ok && isFeatherless && d.online) {
      _setMsg(msg, 'Online — Featherless.ai catalog ready (search to enable models)', true);
      return;
    }
    if (res.ok && d.status === 'empty') {
      _setMsg(msg, 'Online — no models found', true);
      return;
    }
    if (res.ok && d.online) {
      const models = d.models || [];
      const preview = models.slice(0, 3).map(m => esc(String(m).split('/').pop())).join(', ');
      msg.innerHTML = `Online — found ${models.length} model${models.length !== 1 ? 's' : ''}${preview ? `: ${preview}${models.length > 3 ? ', …' : ''}` : ''}`;
      msg.className = 'admin-success';
      return;
    }
    _setMsg(msg, (d && d.detail) || (d && d.ping_error ? `Offline — ${d.ping_error}` : 'Offline'), false);
  }

  function _endpointMsg(kind) {
    return el(kind === 'local' ? 'adm-epLocalMsg' : 'adm-epApiMsg') || el('adm-epMsg');
  }

  let apiTestController = null;
  const apiTestBtn = el('adm-epApiTestBtn');
  const apiCancelTestBtn = el('adm-epApiCancelTestBtn');
  if (apiTestBtn) {
    apiTestBtn.addEventListener('click', async () => {
      if (_isDeviceAuthSelected()) {
        const msg = _endpointMsg('api');
        msg.textContent = '';
        msg.className = '';
        return;
      }
      const msg = _endpointMsg('api');
      msg.textContent = ''; msg.className = '';
      const rawUrl = (urlInput.value || provider.value).trim();
      const apiKey = el('adm-epApiKey').value.trim();
      if (!rawUrl) { _setMsg(msg, 'Select a provider or enter a base URL', false); return; }
      if (provider.value && !apiKey) { _setMsg(msg, 'API key is required for cloud providers', false); return; }
      const url = provider.value && rawUrl === provider.value ? rawUrl : _normalizeBaseUrl(rawUrl);
      apiTestController = new AbortController();
      apiTestBtn.disabled = true;
      apiTestBtn.textContent = 'Testing...';
      if (apiCancelTestBtn) apiCancelTestBtn.classList.remove('hidden');
      try {
        const fd = new FormData();
        fd.append('base_url', url);
        fd.append('endpoint_kind', _apiEndpointKind());
        fd.append('model_refresh_timeout', '30');
        if (apiKey) fd.append('api_key', apiKey);
        const res = await fetch('/api/model-endpoints/test', {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
          signal: apiTestController.signal,
        });
        const d = await res.json();
        _renderEndpointTestResult(msg, res, d);
      } catch (e) {
        if (e && e.name === 'AbortError') {
          msg.textContent = 'Test canceled';
          msg.className = '';
        } else {
          _setMsg(msg, 'Test failed: ' + (e && e.message ? e.message : 'request failed'), false);
        }
      }
      apiTestController = null;
      apiTestBtn.disabled = false;
      apiTestBtn.textContent = 'Test';
      if (apiCancelTestBtn) apiCancelTestBtn.classList.add('hidden');
    });
  }
  if (apiCancelTestBtn) {
    apiCancelTestBtn.addEventListener('click', () => {
      if (apiTestController) apiTestController.abort();
    });
  }

  el('adm-epAddBtn').addEventListener('click', async () => {
    const deviceAuthProvider = _selectedDeviceAuthProvider();
    if (deviceAuthProvider) {
      await _startProviderDeviceAuth(deviceAuthProvider, el('adm-epAddBtn'));
      return;
    }
    const msg = _endpointMsg('api');
    msg.textContent = ''; msg.className = '';
    const rawUrl = (urlInput.value || provider.value).trim();
    const apiKey = el('adm-epApiKey').value.trim();
    if (!rawUrl) { _setMsg(msg, 'Select a provider or enter a base URL', false); return; }
    if (provider.value && !apiKey) { _setMsg(msg, 'API key is required for cloud providers', false); return; }
    // Normalize URL (fix typos, add /v1, strip wrong paths)
    const url = provider.value && rawUrl === provider.value ? rawUrl : _normalizeBaseUrl(rawUrl);
    const btn = el('adm-epAddBtn');
    btn.disabled = true; btn.textContent = 'Adding...';
    try {
      const fd = new FormData();
      fd.append('base_url', url);
      const endpointKind = _apiEndpointKind();
      fd.append('endpoint_kind', endpointKind);
      const refreshMode = _modelRefreshModeForApiEndpoint(url, endpointKind);
      if (refreshMode) fd.append('model_refresh_mode', refreshMode);
      fd.append('model_refresh_timeout', '30');
      if (apiKey) fd.append('api_key', apiKey);
      if (provider.value && provider.selectedOptions && provider.selectedOptions[0]) {
        fd.append('name', provider.selectedOptions[0].textContent.trim());
      }
      const epType = el('adm-epType');
      if (epType) fd.append('model_type', epType.value);
      if (provider.value && /openrouter\.ai|ollama\.com/i.test(provider.value)) fd.append('require_models', 'true');
      else fd.append('skip_probe', 'false');
      const res = await fetch('/api/model-endpoints', { method: 'POST', body: fd, credentials: 'same-origin' });
      const d = await res.json();
      if (res.ok) {
        const count = d.models ? d.models.length : 0;
        urlInput.value = ''; urlInput.style.display = '';
        el('adm-epApiKey').value = ''; provider.value = '';
        if (kindSel) kindSel.value = 'proxy';
        if (epType) epType.value = 'llm';
        if (d.id) _recentlyAddedEpId = String(d.id);
        await loadEndpoints();
        await _selectAddedModelInChat(d);
        const goLink = ' <a href="#" data-go-added-models style="margin-left:6px;text-decoration:underline;color:inherit;font-weight:600;">Added Models →</a>';
        const isFeatherless = d && d.base_url && /featherless\.ai/i.test(d.base_url);
        if (!d.online) {
          msg.innerHTML = 'Added (endpoint offline — will retry on next load)' + goLink;
          msg.className = 'admin-error';
        } else if (isFeatherless) {
          msg.innerHTML = 'Added Featherless.ai — search catalog to enable models' + goLink;
          msg.className = 'admin-success';
        } else if (d.status === 'empty') {
          msg.innerHTML = 'Added — endpoint reachable, no models found' + goLink;
          msg.className = 'admin-success';
        } else {
          msg.innerHTML = `Added — found ${count} model${count !== 1 ? 's' : ''}` + goLink;
          msg.className = 'admin-success';
        }
      } else { _setMsg(msg, d.detail || 'Failed', false); }
    } catch (e) { _setMsg(msg, 'Request failed', false); }
    btn.disabled = false; btn.textContent = 'Add';
  });

  async function _startProviderDeviceAuth(providerKey, triggerEl = null) {
    if (deviceAuthPolling) return;
    const config = PROVIDER_DEVICE_FLOWS[providerKey];
    if (!config) return;
    const status = el('adm-deviceAuthStatus') || _endpointMsg('api');
    if (!status) return;
    const triggerText = triggerEl ? triggerEl.textContent : '';
    // Render an error with an inline "Try again" (the top button is hidden for
    // device-auth providers, so retry lives here). Built with DOM methods, not
    // innerHTML. Call reset() first so the deviceAuthPolling guard is cleared.
    const showAuthError = (text) => {
      status.className = 'admin-error';
      status.textContent = text + ' ';
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'admin-btn-sm';
      retry.textContent = 'Try again';
      retry.addEventListener('click', () => { _startProviderDeviceAuth(providerKey, triggerEl); });
      status.appendChild(retry);
    };
    const reset = () => {
      if (triggerEl) {
        triggerEl.disabled = false;
        triggerEl.textContent = triggerText || 'Add';
      }
      deviceAuthPolling = false;
      _setApiFormForProvider();
    };
    status.textContent = '';
    status.className = 'adm-ep-inline-msg';
    if (triggerEl) {
      triggerEl.disabled = true;
      triggerEl.textContent = 'Starting...';
    }
    deviceAuthPolling = true;
    _setApiFormForProvider();
    status.textContent = `Starting ${config.label} sign-in...`;

    try {
      // New ChatGPT connections carry the optional account label. Only the
      // label travels: the backend creates fresh auth/endpoint rows and never
      // reuses another account's credentials.
      const formData = new FormData();
      if (providerKey === 'chatgpt-subscription' && _chatgptLabelMode) {
        const label = (urlInput.value || '').trim();
        if (label) formData.append('label', label);
      }
      const result = await runProviderDeviceFlow(providerKey, {
        openWindow: () => {},
        formData,
        onStart: ({ start, authUrl }) => {
          if (triggerEl) triggerEl.textContent = 'Waiting...';
          _renderDeviceAuthWaitPanel(status, providerKey, start, authUrl);
        },
      });
      if (result.status === 'authorized') {
        const endpoint = result.endpoint || {};
        const n = ((endpoint && endpoint.models) || []).length;
        status.className = 'admin-success';
        const connectedName = endpoint && endpoint.name ? endpoint.name : config.label;
        status.textContent = 'Connected ' + connectedName + ' - ' + n + ' model' + (n !== 1 ? 's' : '') + ' available.';
        if (endpoint && endpoint.id) _recentlyAddedEpId = String(endpoint.id);
        if (_chatgptLabelMode) urlInput.value = '';
        await loadEndpoints();
        await _selectAddedModelInChat(endpoint || {});
        reset();
        return;
      }
      if (result.status === 'failed') {
        reset();
        showAuthError('Authorization failed (' + (result.error || 'denied') + ').');
        return;
      }
      if (result.status === 'expired') {
        reset();
        showAuthError('Authorization expired.');
        return;
      }
    } catch (e) {
      reset();
      showAuthError(formatDeviceFlowError(e));
    }
  }

  // API Key reveal toggle. The key inputs are hidden by default so the Add
  // form reads as a single action row; the Key button toggles the input row
  // and flips aria-expanded for screen readers / CSS pseudo-classes.
  const _wireKeyToggle = (btnId, rowId) => {
    const btn = el(btnId);
    const row = el(rowId);
    if (!btn || !row) return;
    btn.addEventListener('click', () => {
      const showing = row.style.display !== 'none';
      row.style.display = showing ? 'none' : '';
      btn.setAttribute('aria-expanded', showing ? 'false' : 'true');
      btn.style.opacity = showing ? '0.75' : '1';
      if (!showing) {
        const inp = row.querySelector('input');
        if (inp) inp.focus();
      }
    });
  };
  _wireKeyToggle('adm-epLocalKeyBtn', 'adm-epLocalApiKey-row');

  // Delegated link handler for jumping between settings tabs.
  //   [data-go-added-models]              → quick shortcut for the Added Models tab
  //   [data-go-settings-tab="X"]          → any tab whose nav button has data-settings-tab="X"
  //   [data-go-scroll-to="#elementId"]    → after switching, scroll the element into view
  document.addEventListener('click', (e) => {
    const explicit = e.target.closest('[data-go-settings-tab]');
    if (explicit) {
      e.preventDefault();
      const tab = explicit.getAttribute('data-go-settings-tab');
      const scrollTo = explicit.getAttribute('data-go-scroll-to');
      const btn = document.querySelector(`[data-settings-tab="${tab}"]`);
      if (btn) btn.click();
      if (scrollTo) {
        // Defer to the next frame so the panel has actually become visible
        // before we try to scroll into it.
        requestAnimationFrame(() => {
          const target = document.querySelector(scrollTo);
          if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      }
      return;
    }
    const link = e.target.closest('[data-go-added-models]');
    if (!link) return;
    e.preventDefault();
    const btn = document.querySelector('[data-settings-tab="added-models"]');
    if (btn) btn.click();
  });

  // Esc closes any open kebab menu in the admin panel, whichever _wireKebab owns it.
  if (!document._admKebabEscWired) {
    document._admKebabEscWired = true;
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      // Any visible kebab dropdown in the admin panel — match by id pattern
      // so adding a new kebab elsewhere automatically benefits.
      const menus = document.querySelectorAll(
        '#adm-epLocalMoreMenu, #adm-epApiMoreMenu'
      );
      let closed = false;
      menus.forEach((m) => {
        if (m && m.style.display !== 'none') {
          m.style.display = 'none';
          // Sync the associated button's aria-expanded when we can find it.
          const btn = document.getElementById(m.id.replace('Menu', 'Btn'));
          if (btn) btn.setAttribute('aria-expanded', 'false');
          closed = true;
        }
      });
      if (closed) e.stopPropagation();
    }, { capture: true });
  }

  const _wireKebab = (btnId, menuId, onItem) => {
    const btn = el(btnId);
    const menu = el(menuId);
    if (!btn || !menu) return;
    const isOpen = () => menu.style.display !== 'none';
    const close = () => { menu.style.display = 'none'; btn.setAttribute('aria-expanded', 'false'); };
    const open = () => { menu.style.display = 'flex'; btn.setAttribute('aria-expanded', 'true'); };
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (isOpen()) close(); else open();
    });
    menu.addEventListener('click', (e) => {
      const item = e.target.closest('.adm-more-item');
      if (!item) return;
      if (onItem) onItem(item, e);
      close();
    });
    document.addEventListener('click', (e) => {
      if (!isOpen()) return;
      if (e.target.closest('#' + menuId + ', #' + btnId)) return;
      close();
    });
    // Use capture phase so this fires before the settings-modal Esc handler
    // (which is in bubble phase). stopPropagation prevents the modal from
    // closing when the user only meant to dismiss this menu.
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && isOpen()) {
        e.stopPropagation();
        close();
      }
    }, { capture: true });
  };

  // API card "..." menu: contains the Proxy/API connection-mode toggle.
  // Sync the visible checkmarks with the hidden #adm-epKind select so
  // downstream code (which reads kindSel.value) keeps working.
  (function wireApiKindMenu() {
    const kind = el('adm-epKind');
    if (!kind) return;
    const opts = document.querySelectorAll('#adm-epApiMoreMenu .adm-kind-opt');
    const sync = () => {
      opts.forEach((o) => {
        const check = o.querySelector('.adm-kind-check');
        if (check) check.style.visibility = (o.dataset.kind === kind.value) ? 'visible' : 'hidden';
      });
    };
    sync();
    kind.addEventListener('change', sync);
    _wireKebab('adm-epApiMoreBtn', 'adm-epApiMoreMenu', (item) => {
      const k = item.dataset.kind;
      if (!k) return;
      kind.value = k;
      kind.dispatchEvent(new Event('change'));
    });
  })();

  // Local card "..." kebab: holds Scan network / Ollama / API key reveal.
  // Item buttons keep their own click handlers; the helper just handles
  // open/close + outside-click + Esc.
  _wireKebab('adm-epLocalMoreBtn', 'adm-epLocalMoreMenu');

  // Probe and Clear offline act on the rendered rows; loadEndpoints() stamps [data-adm-ep-online].
  const _refreshOfflineCount = () => {
    const lbl = el('adm-epOfflineCount');
    if (!lbl) return;
    const n = document.querySelectorAll('[data-adm-ep-id] [data-adm-ep-online="0"]').length;
    lbl.textContent = n > 0 ? `(${n})` : '';
    // Hide the button entirely when there's nothing offline — no point
    // showing an action that has nothing to act on.
    const btn = el('adm-epClearOfflineBtn');
    if (btn) btn.style.display = n === 0 ? 'none' : '';
  };
  // Wire after every loadEndpoints() run by patching the render hook —
  // simplest path: MutationObserver on the two list containers.
  const _obsRoots = ['adm-epList-local', 'adm-epList-api']
    .map(id => el(id)).filter(Boolean);
  if (_obsRoots.length) {
    const mo = new MutationObserver(_refreshOfflineCount);
    _obsRoots.forEach(r => mo.observe(r, { childList: true, subtree: true }));
    _refreshOfflineCount();
  }

  const _fetchWithTimeout = async (url, opts = {}, timeoutMs = 25000) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      return await fetch(url, { ...opts, signal: ctrl.signal });
    } finally {
      clearTimeout(timer);
    }
  };
  const _collectAddedEndpointIds = async () => {
    const domIds = Array.from(document.querySelectorAll('[data-adm-ep-id]'))
      .map(r => r.getAttribute('data-adm-ep-id'))
      .filter(Boolean);
    if (domIds.length) return Array.from(new Set(domIds));
    try {
      const res = await fetch('/api/model-endpoints', { credentials: 'same-origin' });
      const data = await res.json().catch(() => []);
      return (Array.isArray(data) ? data : []).map(ep => ep && ep.id).filter(Boolean);
    } catch (_) {
      return [];
    }
  };
  const _setProbeAllButtonLabel = async (btn, text, whirlpoolRef) => {
    btn.innerHTML = '';
    if (whirlpoolRef && whirlpoolRef.element) btn.appendChild(whirlpoolRef.element);
    btn.appendChild(document.createTextNode(text));
  };
  if (!window.__admEpProbeAllWired) {
    window.__admEpProbeAllWired = true;
    document.addEventListener('click', async (ev) => {
      const probeAllBtn = ev.target.closest('#adm-epProbeAllBtn');
      if (!probeAllBtn || probeAllBtn.disabled) return;
      ev.preventDefault();
      probeAllBtn.disabled = true;
      const origHTML = probeAllBtn.innerHTML;
      let _wp = null;
      try {
        try {
          const sp = window.spinnerModule || (await import('./spinner.js')).default;
          _wp = sp.createWhirlpool(11);
          _wp.element.style.cssText = 'display:inline-flex;width:11px;height:11px;margin:0 4px 0 0;';
          await _setProbeAllButtonLabel(probeAllBtn, 'Probing', _wp);
        } catch (_) {
          probeAllBtn.innerHTML = '<span style="opacity:0.7;">Probing...</span>';
        }
        await _fetchWithTimeout('/api/model-endpoints/probe-local', { credentials: 'same-origin' }, 12000).catch(() => null);
        const ids = await _collectAddedEndpointIds();
        if (!ids.length) {
          await loadEndpoints();
          if (uiModule && uiModule.showToast) uiModule.showToast('No endpoints to probe', 1800);
          return;
        }
        let done = 0;
        let failed = 0;
        const lane = async (id) => {
          try {
            const res = await _fetchWithTimeout(`/api/model-endpoints/${encodeURIComponent(id)}/models?refresh=true&refresh_timeout=20`, {
              credentials: 'same-origin'
            }, 25000);
            if (!res || !res.ok || res.headers.get('X-Model-Refresh-Status') === 'failed') failed += 1;
            else await res.json().catch(() => null);
          } catch (err) {
            failed += 1;
            console.warn('Endpoint probe failed', id, err);
          } finally {
            done += 1;
            try { await _setProbeAllButtonLabel(probeAllBtn, `Probing ${done}/${ids.length}`, _wp); } catch (_) {}
          }
        };
        const queue = [...ids];
        const workers = Array.from({ length: Math.min(4, queue.length) }, () => (async () => {
          while (queue.length) {
            const id = queue.shift();
            if (id) await lane(id);
          }
        })());
        await Promise.all(workers);
        await loadEndpoints();
        await _refreshAfterEndpointChange();
        _refreshOfflineCount();
        if (uiModule && uiModule.showToast) {
          const ok = Math.max(0, ids.length - failed);
          uiModule.showToast(failed ? `Probed ${ok}/${ids.length} endpoints; ${failed} failed` : `Probed ${ids.length} endpoints`, failed ? 4200 : 1800);
        }
      } finally {
        if (_wp) { try { _wp.destroy(); } catch (_) {} }
        probeAllBtn.innerHTML = origHTML;
        probeAllBtn.disabled = false;
      }
    });
  }

  const clearOfflineBtn = el('adm-epClearOfflineBtn');
  if (clearOfflineBtn) {
    clearOfflineBtn.addEventListener('click', async () => {
      const offlineBtns = Array.from(document.querySelectorAll('[data-adm-del-ep][data-adm-ep-online="0"]'));
      const ids = offlineBtns.map(b => b.getAttribute('data-adm-del-ep')).filter(Boolean);
      if (!ids.length) {
        if (uiModule && uiModule.showToast) {
          uiModule.showToast('No offline endpoints — nothing to clear', 1800);
        }
        return;
      }
      const confirmMsg = ids.length === 1
        ? 'Remove 1 offline endpoint?'
        : `Remove ${ids.length} offline endpoints?`;
      if (uiModule && uiModule.styledConfirm) {
        const ok = await uiModule.styledConfirm(confirmMsg, { confirmText: 'Remove', danger: true });
        if (!ok) return;
      } else if (!confirm(confirmMsg)) {
        return;
      }
      clearOfflineBtn.disabled = true;
      offlineBtns.forEach(b => {
        const row = b.closest('[data-adm-ep-id]');
        if (row) row.remove();
      });
      await Promise.all(ids.map(id =>
        fetch('/api/model-endpoints/' + id, { method: 'DELETE', credentials: 'same-origin' })
          .catch(e => console.warn('Failed to delete offline endpoint', id, e))
      ));
      await _refreshAfterEndpointChange();
      try { await loadEndpoints(); } catch (_) {}
      _refreshOfflineCount();
      if (uiModule && uiModule.showToast) uiModule.showToast(`Removed ${ids.length} offline endpoint${ids.length === 1 ? '' : 's'}`, 1800);
    });
  }

  // The key inputs are masked, so focus clears them for a fresh key.
  const _wireClearOnFocus = (id) => {
    const inp = el(id);
    if (!inp) return;
    inp.addEventListener('focus', () => {
      if (inp.value) inp.value = '';
    });
  };
  _wireClearOnFocus('adm-epLocalApiKey');
  _wireClearOnFocus('adm-epApiKey');

  // Drop the Ollama provider logo into the Ollama Quickstart button. Reuses
  // the same SVG the provider picker uses, so brand parity stays free.
  try {
    const _ollamaLogoSlot = document.querySelector('#adm-epOllamaBtn .adm-ollama-logo');
    if (_ollamaLogoSlot) {
      const svg = providerLogo('ollama') || '';
      if (svg) _ollamaLogoSlot.innerHTML = svg;
    }
  } catch (_) {}

  // Local "Add" button — sibling form for self-hosted base URLs.
  const localAddBtn = el('adm-epLocalAddBtn');
  const localTestBtn = el('adm-epLocalTestBtn');
  if (localTestBtn) {
    localTestBtn.addEventListener('click', async () => {
      const testOriginalHtml = localTestBtn.innerHTML || '>Test';
      const msg = _endpointMsg('local');
      msg.textContent = ''; msg.className = 'adm-ep-inline-msg';
      const raw = (el('adm-epLocalUrl').value || '').trim();
      if (!raw) { _setMsg(msg, 'Enter a base URL to test', false); return; }
      const url = _normalizeBaseUrl(raw);
      const keyEl = el('adm-epLocalApiKey');
      const apiKey = keyEl ? keyEl.value.trim() : '';
      localTestBtn.disabled = true;
      localTestBtn.innerHTML = testOriginalHtml.replace(/>Test\s*$/, '>Testing...');
      try {
        const fd = new FormData();
        fd.append('base_url', url);
        if (apiKey) fd.append('api_key', apiKey);
        const res = await fetch('/api/model-endpoints/test', { method: 'POST', body: fd, credentials: 'same-origin' });
        const d = await res.json();
        _renderEndpointTestResult(msg, res, d);
      } catch (e) {
        _setMsg(msg, 'Test failed: ' + (e && e.message ? e.message : 'request failed'), false);
      }
      localTestBtn.disabled = false;
      localTestBtn.innerHTML = testOriginalHtml;
    });
  }
  if (localAddBtn) {
    localAddBtn.addEventListener('click', async () => {
      const addOriginalHtml = localAddBtn.innerHTML || '>Add';
      const msg = _endpointMsg('local');
      msg.textContent = ''; msg.className = 'adm-ep-inline-msg';
      const raw = (el('adm-epLocalUrl').value || '').trim();
      if (!raw) { _setMsg(msg, 'Enter a base URL (e.g. http://localhost:8002/v1)', false); return; }
      const url = _normalizeBaseUrl(raw);
      const keyEl = el('adm-epLocalApiKey');
      const apiKey = keyEl ? keyEl.value.trim() : '';
      localAddBtn.disabled = true;
      localAddBtn.innerHTML = addOriginalHtml.replace(/>Add\s*$/, '>Adding...');
      try {
        const fd = new FormData();
        fd.append('base_url', url);
        if (apiKey) fd.append('api_key', apiKey);
        fd.append('endpoint_kind', 'local');
        fd.append('model_refresh_mode', 'auto');
        const lt = el('adm-epLocalType');
        if (lt) fd.append('model_type', lt.value);
        fd.append('skip_probe', 'false');
        const res = await fetch('/api/model-endpoints', { method: 'POST', body: fd, credentials: 'same-origin' });
        const d = await res.json();
        if (res.ok) {
          el('adm-epLocalUrl').value = '';
          if (keyEl) keyEl.value = '';
          if (lt) lt.value = 'llm';
          if (d.id) _recentlyAddedEpId = String(d.id);
          await loadEndpoints();
          await _selectAddedModelInChat(d);
          const count = (d.models || []).length;
          const baseText = d.status === 'empty'
            ? 'Added — Ollama is running, no models pulled yet'
            : d.online
            ? `Added — found ${count} model${count !== 1 ? 's' : ''}`
            : 'Added (offline — will retry on next load)';
          msg.innerHTML = `${baseText} <a href="#" data-go-added-models style="margin-left:6px;text-decoration:underline;color:inherit;font-weight:600;">Added Models →</a>`;
          msg.className = d.online ? 'admin-success' : 'admin-error';
        } else { _setMsg(msg, d.detail || 'Failed', false); }
      } catch (e) { _setMsg(msg, 'Request failed', false); }
      localAddBtn.disabled = false;
      localAddBtn.innerHTML = addOriginalHtml;
    });
  }

  const ollamaBtn = el('adm-epOllamaBtn');
  if (ollamaBtn) {
    ollamaBtn.addEventListener('click', async () => {
      const input = el('adm-epLocalUrl');
      if (input) {
        input.value = await _defaultOllamaUrl();
        input.focus();
      }
      const msg = _endpointMsg('local');
      if (msg) {
        msg.innerHTML = '<span style="font-size:11px;opacity:0.55;">Ollama ready to test.</span>';
        msg.className = '';
      }
    });
  }

  // Discover local models button
  const discoverBtn = el('adm-epDiscoverBtn');
  if (discoverBtn) {
    discoverBtn.addEventListener('click', async () => {
      const msg = _endpointMsg('local');
      discoverBtn.disabled = true;
      msg.className = 'adm-ep-inline-msg';
      msg.innerHTML = '';
      try {
        const sp = window.spinnerModule || (await import('./spinner.js')).default;
        const wp = sp.createWhirlpool(20);
        wp.element.style.cssText = 'display:inline-block;vertical-align:middle;margin:0 8px 0 0;';
        const wrap = document.createElement('div');
        wrap.style.cssText = 'display:flex;align-items:center;padding:8px 0;';
        wrap.appendChild(wp.element);
        const txt = document.createElement('span');
        txt.textContent = 'Scanning ports 8000-8020, 8080, 1234, 11434, and 11435 for model servers...';
        txt.style.cssText = 'font-size:12px;opacity:0.7;';
        wrap.appendChild(txt);
        msg.appendChild(wrap);
        discoverBtn._wp = wp;
      } catch(e) { msg.textContent = 'Scanning...'; }
      try {
        const res = await fetch('/api/discover');
        const data = await res.json();
        const items = data.items || [];
        if (!items.length) {
          _setMsg(msg, 'No model servers found. Make sure vLLM, llama.cpp, SGLang, or Ollama is running. Docker users may need Ollama bound to a trusted reachable interface.', false);
        } else {
          // Auto-add each discovered endpoint. Server dedupes on base_url
          // and returns `existing: true` for already-registered ones.
          // Map fingerprinted provider IDs to friendly display names.
          const _PROVIDER_DISPLAY = {
            llamacpp: 'llama.cpp', lmstudio: 'LM Studio', vllm: 'vLLM',
            ollama: 'Ollama',
          };
          let added = 0;
          let skipped = 0;
          for (const item of items) {
            const base = item.url.replace('/chat/completions', '').replace(/\/$/, '');
            const providerDisplay = _PROVIDER_DISPLAY[item.provider] || null;
            const fd = new FormData();
            fd.append('base_url', base);
            if (providerDisplay) {
              // Use "Provider (host:port)" so the endpoint is immediately
              // identifiable in the list, e.g. "llama.cpp (localhost:8080)".
              const hostPart = base.replace(/^https?:\/\//, '').split('/')[0];
              fd.append('name', `${providerDisplay} (${hostPart})`);
            }
            fd.append('endpoint_kind', 'local');
            fd.append('model_refresh_mode', 'auto');
            fd.append('skip_probe', 'false');
            const r = await fetch('/api/model-endpoints', { method: 'POST', body: fd });
            if (r.ok) {
              try {
                const dd = await r.json();
                if (dd && dd.existing) { skipped++; }
                else { added++; if (dd && dd.id) _recentlyAddedEpId = String(dd.id); }
              } catch (_) { added++; }
            }
          }
          const totalModels = items.reduce((n, i) => n + (i.models ? i.models.length : 0), 0);
          const serverNames = items.map(i =>
            (_PROVIDER_DISPLAY[i.provider] || i.url.replace(/^https?:\/\//, '').split('/')[0])
          );
          const parts = [
            `Found ${items.length} server${items.length !== 1 ? 's' : ''} (${serverNames.join(', ')}) with ${totalModels} model${totalModels !== 1 ? 's' : ''}`,
          ];
          if (added) parts.push(`added ${added} new`);
          if (skipped) parts.push(`${skipped} already added`);
          msg.innerHTML = parts.join(' — ');
          msg.className = 'admin-success';
          loadEndpoints();
        }
      } catch (e) {
        _setMsg(msg, 'Scan failed: ' + e.message, false);
      }
      if (discoverBtn._wp) { discoverBtn._wp.destroy(); discoverBtn._wp = null; }
      discoverBtn.disabled = false;
      discoverBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" style="vertical-align:-1px;margin-right:4px;"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>Scan for Servers';
    });
  }

  document.querySelectorAll('.adm-quickstart-section').forEach((sec) => {
    const head = sec.querySelector('.adm-quickstart-toggle');
    if (!head) return;
    const key = 'odysseus.addModels.' + sec.id + '.open';
    let open = false;
    try { open = localStorage.getItem(key) === '1'; } catch {}
    const apply = () => {
      sec.classList.toggle('collapsed', !open);
      head.setAttribute('aria-expanded', open ? 'true' : 'false');
    };
    apply();
    const toggle = () => {
      open = !open;
      try { localStorage.setItem(key, open ? '1' : '0'); } catch {}
      apply();
    };
    head.addEventListener('click', toggle);
    head.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
  });
}

const TOOL_META = {
  bash:              { name: 'Shell',            desc: 'Execute bash commands',           cat: 'Code',       ctx: '~200' },
  python:            { name: 'Python',           desc: 'Run Python scripts',              cat: 'Code',       ctx: '~200' },
  read_file:         { name: 'Read File',        desc: 'Read files from disk',            cat: 'Code',       ctx: '~150' },
  write_file:        { name: 'Write File',       desc: 'Write/create files',              cat: 'Code',       ctx: '~150' },
  web_search:        { name: 'Web Search',       desc: 'Search the web via SearXNG',      cat: 'Search',     ctx: '~300' },
  search_chats:      { name: 'Search Chats',     desc: 'Search conversation history',     cat: 'Search',     ctx: '~150' },
  create_document:   { name: 'Create Document',  desc: 'Create new documents',            cat: 'Documents',  ctx: '~200' },
  update_document:   { name: 'Update Document',  desc: 'Modify existing documents',       cat: 'Documents',  ctx: '~200' },
  edit_document:     { name: 'Edit Document',    desc: 'Find & replace in documents',     cat: 'Documents',  ctx: '~200' },
  suggest_document:  { name: 'Suggest Changes',  desc: 'Propose document edits',          cat: 'Documents',  ctx: '~200' },
  manage_documents:  { name: 'Manage Documents', desc: 'List, delete, organize docs',     cat: 'Documents',  ctx: '~150' },
  generate_image:    { name: 'Generate Image',   desc: 'Create images via AI',            cat: 'Media',      ctx: '~150' },
  manage_memory:     { name: 'Memory',           desc: 'Save and recall memories',        cat: 'Knowledge',  ctx: '~200' },
  manage_skills:     { name: 'Skills',           desc: 'Learn and use procedures',        cat: 'Knowledge',  ctx: '~200' },
  manage_rag:        { name: 'RAG / Docs',       desc: 'Query indexed documents',         cat: 'Knowledge',  ctx: '~150' },
  chat_with_model:   { name: 'Chat with Model',  desc: 'Talk to another AI model',        cat: 'Multi-Agent', ctx: '~200' },
  pipeline:          { name: 'Pipeline',         desc: 'Multi-step AI workflows',         cat: 'Multi-Agent', ctx: '~200' },
  ask_teacher:       { name: 'Ask Teacher',      desc: 'Query a more capable model',      cat: 'Multi-Agent', ctx: '~150' },
  send_to_session:   { name: 'Send to Session',  desc: 'Send message to another chat',    cat: 'Sessions',   ctx: '~100' },
  create_session:    { name: 'Create Session',   desc: 'Start a new chat session',        cat: 'Sessions',   ctx: '~100' },
  list_sessions:     { name: 'List Sessions',    desc: 'Browse existing sessions',        cat: 'Sessions',   ctx: '~100' },
  manage_session:    { name: 'Manage Session',   desc: 'Rename, archive, configure',      cat: 'Sessions',   ctx: '~100' },
  list_models:       { name: 'List Models',      desc: 'Show available models',           cat: 'System',     ctx: '~100' },
  ui_control:        { name: 'UI Control',       desc: 'Change theme, layout, settings',  cat: 'System',     ctx: '~150' },
  manage_tasks:      { name: 'Tasks',            desc: 'Schedule automated tasks',        cat: 'System',     ctx: '~150' },
  api_call:          { name: 'API Call',         desc: 'Make HTTP requests',              cat: 'System',     ctx: '~200' },
  manage_endpoints:  { name: 'Endpoints',        desc: 'Add/remove model endpoints',      cat: 'System',     ctx: '~100' },
  manage_mcp:        { name: 'MCP Servers',      desc: 'Manage MCP connections',          cat: 'System',     ctx: '~100' },
  manage_webhooks:   { name: 'Webhooks',         desc: 'Configure webhook events',        cat: 'System',     ctx: '~100' },
  manage_tokens:     { name: 'API Tokens',       desc: 'Manage API access tokens',        cat: 'System',     ctx: '~100' },
  manage_settings:   { name: 'Settings',         desc: 'Change app settings',             cat: 'System',     ctx: '~100' },
};

async function loadBuiltinTools() {
  const list = el('adm-builtin-tools-list');
  if (!list) return;
  try {
    // Saves merge onto this state, so it must be fresh: a stale snapshot (another
    // tab, the manage_settings tool) would undo newer changes on the next toggle.
    invalidateTools();
    const data = await getTools();
    const tools = data.tools || [];
    if (!tools.length) { list.innerHTML = '<div class="admin-empty">No tools found</div>'; return; }

    // Group by category
    const groups = {};
    for (const t of tools) {
      const meta = TOOL_META[t.id] || { name: t.id, desc: '', cat: 'Other', ctx: '?' };
      const cat = meta.cat;
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push({ ...t, ...meta });
    }

    // Category order
    const catOrder = ['Code', 'Search', 'Documents', 'Media', 'Knowledge', 'Multi-Agent', 'Sessions', 'System', 'Other'];
    let html = '';
    for (const cat of catOrder) {
      const items = groups[cat];
      if (!items) continue;
      const enabledCount = items.filter(i => i.enabled).length;
      const totalCount = items.length;
      const catId = 'tool-cat-' + cat.replace(/[^a-zA-Z]/g, '');
      const allEnabled = enabledCount === totalCount;
      html += `<div class="admin-tool-category">
        <div class="admin-tool-cat-header" data-tool-cat="${catId}" style="cursor:pointer;display:flex;align-items:center;justify-content:space-between;">
          <span>${esc(cat)}</span>
          <span style="display:flex;align-items:center;gap:6px;" class="admin-tool-cat-right">
            <span class="admin-tool-cat-count" style="font-size:10px;opacity:0.5;">${enabledCount}/${totalCount}</span>
            <label class="admin-switch" style="flex-shrink:0;">
              <input type="checkbox" data-tool-cat-toggle="${catId}" ${allEnabled ? 'checked' : ''}>
              <span class="admin-slider"></span>
            </label>
            <svg class="admin-tool-cat-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.3;transition:transform 0.2s,opacity 0.2s;"><polyline points="6 9 12 15 18 9"/></svg>
          </span>
        </div>
        <div class="admin-tool-cat-body hidden" id="${catId}">`;
      for (const t of items) {
        html += `
        <div class="admin-tool-row">
          <div class="admin-tool-info">
            <span class="admin-tool-name">${esc(t.name)}</span>
            <span class="admin-tool-desc">${esc(t.desc)}</span>
          </div>
          <span class="admin-tool-ctx" title="Approximate context tokens used">${esc(t.ctx)}</span>
          <label class="admin-switch" style="flex-shrink:0;">
            <input type="checkbox" data-tool-id="${esc(t.id)}" ${t.enabled ? 'checked' : ''}>
            <span class="admin-slider"></span>
          </label>
        </div>`;
      }
      html += '</div></div>';
    }
    list.innerHTML = html;

    // Prevent toggle clicks from expanding/collapsing
    list.querySelectorAll('.admin-tool-cat-right').forEach(span => {
      span.addEventListener('click', e => e.stopPropagation());
    });

    // Wire category expand/collapse
    list.querySelectorAll('[data-tool-cat]').forEach(header => {
      header.addEventListener('click', () => {
        const body = el(header.dataset.toolCat);
        if (!body) return;
        body.classList.toggle('hidden');
        const chevron = header.querySelector('.admin-tool-cat-chevron');
        const isOpen = !body.classList.contains('hidden');
        if (chevron) {
          chevron.style.transform = isOpen ? 'rotate(180deg)' : '';
          chevron.style.opacity = isOpen ? '0.7' : '0.3';
        }
      });
    });

    // Merge only the user's intended changes onto authoritative server state.
    // /api/tools replaces the full disabled list, so rebuilding it from this
    // panel's DOM can undo a change made by another tab or manage_settings
    // after the panel was opened.
    async function _saveToolState(changes) {
      invalidateTools();
      const latest = await getTools();
      const state = new Map(
        (latest.tools || []).map(t => [t.id, !!t.enabled])
      );

      for (const change of changes) {
        if (state.has(change.id)) {
          state.set(change.id, !!change.enabled);
        }
      }

      const disabled = Array.from(state.entries())
        .filter(([, enabled]) => !enabled)
        .map(([id]) => id);

      try {
        const res = await fetch('/api/tools', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ disabled }),
          credentials: 'same-origin',
        });
        if (!res.ok) throw new Error(`Failed to update tools (${res.status})`);

        // Bring the still-open editor forward to the same merged snapshot so an
        // out-of-band change is visible instead of leaving stale checkboxes.
        list.querySelectorAll('input[data-tool-id]').forEach(c => {
          if (state.has(c.dataset.toolId)) {
            c.checked = state.get(c.dataset.toolId);
          }
        });
        list.querySelectorAll('.admin-tool-category').forEach(_updateCatCounter);
      } finally {
        // This route persists disabled_tools into the settings store
        // (routes/model_routes.py), so both snapshots are now stale.
        invalidateTools();
        invalidateSettings();
      }
    }
    function _updateCatCounter(catEl) {
      if (!catEl) return;
      const catChecks = catEl.querySelectorAll('input[data-tool-id]');
      const catEnabled = Array.from(catChecks).filter(c => c.checked).length;
      const counter = catEl.querySelector('.admin-tool-cat-count');
      if (counter) counter.textContent = catEnabled + '/' + catChecks.length;
      const catToggle = catEl.querySelector('input[data-tool-cat-toggle]');
      if (catToggle) catToggle.checked = (catEnabled === catChecks.length);
    }

    // Wire individual tool toggles
    list.querySelectorAll('input[data-tool-id]').forEach(chk => {
      chk.addEventListener('change', async () => {
        await _saveToolState([
          { id: chk.dataset.toolId, enabled: chk.checked },
        ]);
        _updateCatCounter(chk.closest('.admin-tool-category'));
      });
    });

    // Wire category-level toggle (enable/disable all in category)
    list.querySelectorAll('input[data-tool-cat-toggle]').forEach(chk => {
      chk.addEventListener('change', async () => {
        const catEl = chk.closest('.admin-tool-category');
        if (!catEl) return;
        const checked = chk.checked;
        const changes = Array.from(catEl.querySelectorAll('input[data-tool-id]'))
          .map(c => ({ id: c.dataset.toolId, enabled: checked }));
        catEl.querySelectorAll('input[data-tool-id]').forEach(c => { c.checked = checked; });
        await _saveToolState(changes);
        _updateCatCounter(catEl);
      });
    });
  } catch (e) {
    console.error('Failed to load tools:', e);
    list.innerHTML = '<div class="admin-empty">Failed to load tools</div>';
  }
}

function initBackup() {
  el('adm-exportDataBtn').addEventListener('click', async () => {
    const btn = el('adm-exportDataBtn');
    const msg = el('adm-backupMsg');
    btn.disabled = true; btn.textContent = 'Exporting...'; msg.textContent = '';
    try {
      const res = await fetch('/api/export', { credentials: 'same-origin' });
      if (!res.ok) throw new Error('Export failed');
      const blob = await res.blob();
      const disposition = res.headers.get('Content-Disposition') || '';
      const match = disposition.match(/filename=(.+)/);
      const filename = match ? match[1] : 'odysseus_backup.json';
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      URL.revokeObjectURL(a.href);
      _setMsg(msg, 'Export downloaded.', true);
    } catch (e) { _setMsg(msg, 'Export failed: ' + e.message, false); }
    btn.disabled = false; btn.textContent = 'Export Data';
  });

  const fileInput = el('adm-importFile');
  el('adm-importDataBtn').addEventListener('click', () => { fileInput.value = ''; fileInput.click(); });
  fileInput.addEventListener('change', async () => {
    const file = fileInput.files[0];
    if (!file) return;
    const msg = el('adm-backupMsg');
    const btn = el('adm-importDataBtn');
    btn.disabled = true; btn.textContent = 'Importing...'; msg.textContent = '';
    try {
      const text = (await file.text()).replace(/^\uFEFF/, '').trim();
      let data;
      try {
        data = JSON.parse(text);
      } catch (e) {
        throw new Error('Invalid backup file: ' + e.message);
      }
      const res = await fetch('/api/import', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const result = await res.json().catch(() => null);
      if (!result) {
        throw new Error(`Import failed: server returned ${res.status}`);
      }
      if (res.ok && result.ok) {
        _setMsg(msg, result.message || 'Import successful.', true);
      } else {
        _setMsg(msg, result.message || result.detail || 'Import failed', false);
      }
    } catch (e) { _setMsg(msg, 'Import failed: ' + e.message, false); }
    btn.disabled = false; btn.textContent = 'Import Data';
  });
}

function initDangerZone() {
  // Per-category Danger Zone wipes. Each button declares its target
  // via data-wipe-kind; one delegated handler handles double-confirm,
  // POSTs to /api/admin/wipe/{kind}, and writes the result.
  const _LABELS = {
    chats: 'chats', memory: 'memory entries', skills: 'skills',
    notes: 'notes', tasks: 'tasks', documents: 'documents',
    gallery: 'gallery images', calendar: 'calendar items',
  };
  const _wipeMsg = el('adm-wipeMsg');
  modalEl.querySelectorAll('[data-wipe-kind]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const kind = btn.dataset.wipeKind;
      const isAll = kind === '__all__';
      const label = isAll ? 'data across every category' : (_LABELS[kind] || kind);
      if (!await uiModule.styledConfirm(`Delete ALL ${label}? This cannot be undone.`, { confirmText: 'Delete', danger: true })) return;
      if (!await uiModule.styledConfirm(`Really delete every one of your ${label}?`, { confirmText: isAll ? 'Yes, delete everything' : 'Yes, delete everything', danger: true })) return;
      btn.disabled = true;
      const prevHtml = btn.innerHTML;
      btn.innerHTML = isAll ? 'Deleting all…' : 'Deleting…';
      if (_wipeMsg) { _wipeMsg.textContent = ''; _wipeMsg.className = ''; }
      try {
        if (isAll) {
          // Iterate every known category. Failures in one shouldn't stop
          // the rest — record per-category counts and surface a summary.
          const kinds = Object.keys(_LABELS);
          const results = [];
          for (const k of kinds) {
            try {
              const r = await fetch(`/api/admin/wipe/${k}`, { method: 'DELETE', credentials: 'same-origin' });
              const d = await r.json().catch(() => ({}));
              results.push({ k, ok: r.ok, count: d.count ?? 0, error: r.ok ? null : (d.detail || 'failed') });
            } catch (e) {
              results.push({ k, ok: false, count: 0, error: e.message });
            }
          }
          const okCount = results.filter(r => r.ok).length;
          const total = results.reduce((n, r) => n + (r.ok ? r.count : 0), 0);
          const fails = results.filter(r => !r.ok).map(r => r.k);
          if (_wipeMsg) {
            if (!fails.length) {
              _setMsg(_wipeMsg, `Deleted ${total} items across all ${okCount} categories.`, true);
            } else {
              _setMsg(_wipeMsg, `Deleted ${total} items; failed: ${fails.join(', ')}.`, false);
            }
          }
        } else {
          const res = await fetch(`/api/admin/wipe/${kind}`, { method: 'DELETE', credentials: 'same-origin' });
          const data = await res.json().catch(() => ({}));
          if (res.ok) {
            if (_wipeMsg) { _setMsg(_wipeMsg, `Deleted ${data.count ?? 0} ${label}.`, true); }
          } else {
            if (_wipeMsg) { _setMsg(_wipeMsg, data.detail || 'Failed', false); }
          }
        }
      } catch (e) {
        if (_wipeMsg) { _setMsg(_wipeMsg, 'Request failed: ' + e.message, false); }
      }
      btn.disabled = false; btn.innerHTML = prevHtml;
    });
  });
}

let logsPollInterval = null;
let isLogsPolling = false;
let cachedLogs = [];
let logsAbortController = null;
let cachedNotificationLogs = [];
let notificationLogsAbortController = null;

function renderLogs(isAutoPoll = false) {
  const consoleContainer = el('log-console-container');
  const levelSelect = el('log-level-select');
  const searchInput = el('log-search-input');

  if (!consoleContainer) return;

  const levelFilter = levelSelect ? levelSelect.value : 'ALL';
  const searchQuery = searchInput ? searchInput.value.trim().toLowerCase() : '';

  let logs = cachedLogs;

  // Filter by level locally
  if (levelFilter !== 'ALL') {
    logs = logs.filter(line => line.includes(` - ${levelFilter} - `));
  }

  // Filter by search query locally
  if (searchQuery) {
    logs = logs.filter(line => line.toLowerCase().includes(searchQuery));
  }

  if (logs.length === 0) {
    consoleContainer.innerHTML = '<div class="settings-system-logs-placeholder">No logs found matching current filters.</div>';
    return;
  }

  // Preserve scroll position if user is reading previous logs
  const atBottom = consoleContainer.scrollHeight - consoleContainer.scrollTop - consoleContainer.clientHeight < 40;

  consoleContainer.innerHTML = logs.map(line => {
    let levelClass = 'log-line-default';

    if (line.includes(' - INFO - ')) {
      levelClass = 'log-line-info';
    } else if (line.includes(' - WARNING - ')) {
      levelClass = 'log-line-warning';
    } else if (line.includes(' - ERROR - ') || line.includes(' - CRITICAL - ')) {
      levelClass = 'log-line-error';
    } else if (line.includes(' - DEBUG - ')) {
      levelClass = 'log-line-debug';
    }

    // XSS safe escape
    const escaped = line
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');

    return `<div class="log-line ${levelClass}">${escaped}</div>`;
  }).join('');

  if (!isAutoPoll || atBottom) {
    consoleContainer.scrollTop = consoleContainer.scrollHeight;
  }
}

async function loadLogs(isAutoPoll = false) {
  const consoleContainer = el('log-console-container');
  const limitSelect = el('log-limit-select');

  if (!consoleContainer) return;

  const limit = limitSelect ? limitSelect.value : 200;

  if (logsAbortController) {
    logsAbortController.abort();
  }
  logsAbortController = new AbortController();
  const { signal } = logsAbortController;

  try {
    const res = await fetch(`/api/diagnostics/logs?limit=${limit}`, {
      credentials: 'same-origin',
      signal
    });

    if (!res.ok) {
      if (!isAutoPoll) {
        consoleContainer.innerHTML = '';
        const errDiv = document.createElement('div');
        errDiv.style.color = 'var(--red)';
        errDiv.style.fontWeight = '600';
        errDiv.textContent = `Failed to load logs: HTTP ${res.status}`;
        consoleContainer.appendChild(errDiv);
      }
      return;
    }

    const data = await res.json();
    if (data.status !== 'success' || !data.logs) {
      if (!isAutoPoll) {
        consoleContainer.innerHTML = '';
        const errDiv = document.createElement('div');
        errDiv.style.color = 'var(--red)';
        errDiv.style.fontWeight = '600';
        errDiv.textContent = 'Failed to parse logs data';
        consoleContainer.appendChild(errDiv);
      }
      return;
    }

    cachedLogs = data.logs;
    renderLogs(isAutoPoll);
  } catch (err) {
    if (err.name === 'AbortError') {
      return; // Silently ignore deliberate abort
    }
    if (!isAutoPoll) {
      consoleContainer.innerHTML = '';
      const errDiv = document.createElement('div');
      errDiv.style.color = 'var(--red)';
      errDiv.style.fontWeight = '600';
      errDiv.textContent = `Error retrieving logs: ${err.message}`;
      consoleContainer.appendChild(errDiv);
    }
  } finally {
    if (logsAbortController?.signal === signal) {
      logsAbortController = null;
    }
  }
}

function renderNotificationLogs() {
  const container = el('notification-log-container');
  const statusSelect = el('notification-log-status-select');
  const searchInput = el('notification-log-search-input');
  if (!container) return;

  const statusFilter = statusSelect ? statusSelect.value : 'ALL';
  const searchQuery = searchInput ? searchInput.value.trim().toLowerCase() : '';
  let logs = cachedNotificationLogs;
  if (statusFilter !== 'ALL') {
    logs = logs.filter(note => String(note.status || '').toLowerCase() === statusFilter);
  }
  if (searchQuery) {
    logs = logs.filter(note => [note.task_name, note.status, note.body, note.task_id]
      .some(value => String(value || '').toLowerCase().includes(searchQuery)));
  }

  container.replaceChildren();
  if (!logs.length) {
    const empty = document.createElement('div');
    empty.className = 'settings-system-logs-placeholder';
    empty.textContent = cachedNotificationLogs.length
      ? 'No notification logs match the current filters.'
      : 'No task notifications recorded yet.';
    container.appendChild(empty);
    return;
  }

  const fragment = document.createDocumentFragment();
  logs.forEach(note => {
    const status = String(note.status || 'success').toLowerCase();
    const entry = document.createElement('article');
    entry.className = `notification-log-entry notification-log-${status === 'error' ? 'error' : 'success'}`;

    const heading = document.createElement('div');
    heading.className = 'notification-log-heading';
    const task = document.createElement('strong');
    task.className = 'notification-log-task';
    task.textContent = note.task_name || 'Untitled task';
    const badge = document.createElement('span');
    badge.className = 'notification-log-status';
    badge.textContent = status === 'error' ? 'Error' : 'Success';
    heading.append(task, badge);

    const meta = document.createElement('div');
    meta.className = 'notification-log-meta';
    const date = note.timestamp ? new Date(note.timestamp) : null;
    meta.textContent = date && !Number.isNaN(date.getTime())
      ? date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
      : '';
    if (note.task_id) meta.textContent += meta.textContent ? ` · ${note.task_id}` : note.task_id;

    entry.append(heading, meta);
    if (note.body) {
      const body = document.createElement('div');
      body.className = 'notification-log-body';
      const bodyText = document.createElement('span');
      bodyText.className = 'notification-log-body-text';
      bodyText.textContent = note.body;
      const copyBtn = document.createElement('button');
      copyBtn.type = 'button';
      copyBtn.className = 'notification-log-copy';
      copyBtn.title = 'Copy notification';
      copyBtn.setAttribute('aria-label', 'Copy notification');
      const copyIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
      copyBtn.innerHTML = copyIcon;
      copyBtn.addEventListener('click', async (event) => {
        event.stopPropagation();
        if (!await uiModule.copyToClipboard(note.body, { toast: false })) {
          uiModule.showToast('Could not copy notification');
          return;
        }
        copyBtn.innerHTML = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
        copyBtn.classList.add('copied');
        setTimeout(() => { copyBtn.innerHTML = copyIcon; copyBtn.classList.remove('copied'); }, 1400);
      });
      body.append(bodyText, copyBtn);
      entry.appendChild(body);
    }
    fragment.appendChild(entry);
  });
  container.appendChild(fragment);
}

async function loadNotificationLogs() {
  const container = el('notification-log-container');
  if (!container) return;
  if (notificationLogsAbortController) notificationLogsAbortController.abort();
  notificationLogsAbortController = new AbortController();
  const { signal } = notificationLogsAbortController;
  try {
    const res = await fetch('/api/tasks/notification-logs?limit=500', {
      credentials: 'same-origin',
      signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    cachedNotificationLogs = Array.isArray(data.notifications) ? data.notifications : [];
    renderNotificationLogs();
  } catch (err) {
    if (err.name === 'AbortError') return;
    container.replaceChildren();
    const error = document.createElement('div');
    error.className = 'admin-error';
    error.textContent = `Failed to load notification logs: ${err.message}`;
    container.appendChild(error);
  } finally {
    if (notificationLogsAbortController?.signal === signal) {
      notificationLogsAbortController = null;
    }
  }
}

function setSystemLogTab(tab) {
  const showNotifications = tab === 'notifications';
  document.querySelectorAll('[data-system-log-tab]').forEach(button => {
    const active = button.dataset.systemLogTab === tab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const terminalPanel = el('system-log-terminal-panel');
  const notificationPanel = el('system-log-notifications-panel');
  if (terminalPanel) {
    terminalPanel.hidden = showNotifications;
    terminalPanel.classList.toggle('hidden', showNotifications);
    terminalPanel.style.display = showNotifications ? 'none' : 'flex';
    terminalPanel.setAttribute('aria-hidden', showNotifications ? 'true' : 'false');
  }
  if (notificationPanel) {
    notificationPanel.hidden = !showNotifications;
    notificationPanel.classList.toggle('hidden', !showNotifications);
    notificationPanel.style.display = showNotifications ? 'flex' : 'none';
    notificationPanel.setAttribute('aria-hidden', showNotifications ? 'false' : 'true');
  }
  if (showNotifications) loadNotificationLogs();
}

function startLogsPolling() {
  if (isLogsPolling) return;
  isLogsPolling = true;
  const toggle = el('log-auto-refresh-toggle');
  if (toggle) toggle.checked = true;

  logsPollInterval = setInterval(() => {
    const modal = el('settings-modal');
    const systemPanel = el('settings-modal')?.querySelector('[data-settings-panel="system"]');

    // Safe self-cleanup if modal or panel is hidden/closed
    if (!modal || modal.classList.contains('hidden') || !systemPanel || systemPanel.classList.contains('hidden')) {
      stopLogsPolling();
      return;
    }

    loadLogs(true);
  }, 3000);
}

function stopLogsPolling() {
  if (!isLogsPolling) return;
  isLogsPolling = false;
  if (logsPollInterval) {
    clearInterval(logsPollInterval);
    logsPollInterval = null;
  }
  const toggle = el('log-auto-refresh-toggle');
  if (toggle) toggle.checked = false;
}

function initLogsView() {
  const refreshBtn = el('log-refresh-btn');
  const levelSelect = el('log-level-select');
  const limitSelect = el('log-limit-select');
  const searchInput = el('log-search-input');
  const autoRefreshToggle = el('log-auto-refresh-toggle');
  const notificationRefreshBtn = el('notification-log-refresh-btn');
  const notificationStatusSelect = el('notification-log-status-select');
  const notificationSearchInput = el('notification-log-search-input');

  document.querySelectorAll('[data-system-log-tab]').forEach(button => {
    button.addEventListener('click', () => setSystemLogTab(button.dataset.systemLogTab || 'terminal'));
  });

  if (refreshBtn) refreshBtn.addEventListener('click', () => loadLogs(false));
  if (levelSelect) levelSelect.addEventListener('change', () => renderLogs(false));
  if (limitSelect) limitSelect.addEventListener('change', () => loadLogs(false));
  if (searchInput) searchInput.addEventListener('input', () => renderLogs(false));
  if (notificationRefreshBtn) notificationRefreshBtn.addEventListener('click', loadNotificationLogs);
  if (notificationStatusSelect) notificationStatusSelect.addEventListener('change', renderNotificationLogs);
  if (notificationSearchInput) notificationSearchInput.addEventListener('input', renderNotificationLogs);

  if (autoRefreshToggle) {
    autoRefreshToggle.addEventListener('change', (e) => {
      if (e.target.checked) {
        startLogsPolling();
      } else {
        stopLogsPolling();
      }
    });
  }

  // Initial fetch on view loading
  setSystemLogTab('terminal');
  loadLogs(false);
}

function initAll() {
  modalEl = el('settings-modal');
  const inits = [
    initSignupToggle, initShareDefaultsToggle, initAddUser, initEndpointForm,
    initBackup, initDangerZone, initLogsView,
  ];
  for (const fn of inits) {
    try { fn(); } catch (e) { console.error('Admin init error in', fn.name || 'anonymous', e); }
  }
  initialized = true;
  refreshAll();
}

function refreshAll() {
  loadUsers();
  loadEndpoints();
  loadBuiltinTools();
  loadLogs(false);
  loadNotificationLogs();
}

export function _initData() {
  if (!initialized) initAll();
  else refreshAll();
}

export function open(tab) {
  _initData();
  settingsModule.open(tab || 'services');
}

export function close() {
  stopLogsPolling();
  settingsModule.close();
}

export { shouldDisplayEndpointBaseUrl, isFeatherlessEndpoint, endpointDetailHtml, renderFeatherlessPanel };

const adminModule = { open, close, _initData, get _initialized() { return initialized; } };
export default adminModule;
