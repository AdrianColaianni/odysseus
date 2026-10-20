import uiModule from '../ui.js?v=20260916largetoolscroll1';
import { invalidateSettings } from '../appConfig.js';

export async function postSettings(body) {
  try {
    const response = await fetch('/api/auth/settings', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const error = new Error(response.status === 403
        ? 'Admin access is required to change these settings.'
        : 'Failed to save');
      error.status = response.status;
      if (response.status === 403) uiModule.showError(error.message);
      throw error;
    }
    return response;
  } finally {
    invalidateSettings();
  }
}

export async function fetchSettings() {
  const response = await fetch('/api/auth/settings', { credentials: 'same-origin' });
  return response.json();
}

export async function fetchModelEndpoints() {
  const response = await fetch('/api/model-endpoints', { credentials: 'same-origin' });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const endpoints = await response.json();
  return Array.isArray(endpoints) ? endpoints : [];
}

// Show a save result beside a control. Successes clear after clearMs.
export function flashStatus(msgEl, text, isError, clearMs = 2000) {
  msgEl.textContent = text;
  msgEl.style.color = isError ? 'var(--red)' : 'var(--fg)';
  if (!isError) setTimeout(() => { msgEl.textContent = ''; }, clearMs);
}

export function flashSaveError(msgEl, error) {
  flashStatus(msgEl, error.status === 403 ? error.message : 'Failed to save', true);
}
