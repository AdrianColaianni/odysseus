// Image-model settings panel.

import { byId as el } from './dom.js';
import { postSettings as _postSettings, flashStatus, flashSaveError } from './api.js';
import { modelCaps } from '../editor/ai-models.js';
import { sortModelIds } from '../modelSort.js';

export async function initImageSettings(settingsLoad, endpointsLoad) {
  const modelSel = el('set-imgModelSelect');
  const qualSel = el('set-imgQualitySelect');
  const msg = el('set-imgSettingsMsg');
  const enabledToggle = el('set-imgEnabledToggle');
  const configWrap = modelSel ? modelSel.closest('div[style*="flex-direction"]') : null;
  try {
    const endpoints = await endpointsLoad;
    const imageModels = new Set();
    endpoints.forEach(endpoint => {
      if (!endpoint.is_enabled || !endpoint.online) return;
      (Array.isArray(endpoint.models) ? endpoint.models : []).forEach(modelId => {
        if (modelId && modelCaps(modelId, '', endpoint.model_type).gen) imageModels.add(String(modelId));
      });
    });
    sortModelIds(Array.from(imageModels)).forEach(mid => {
      const opt = document.createElement('option');
      opt.value = mid;
      opt.textContent = mid;
      modelSel.appendChild(opt);
    });
  } catch (e) { console.warn('Failed to load models for image settings', e); }
  try {
    const settings = await settingsLoad;
    if (settings.image_model) modelSel.value = settings.image_model;
    if (settings.image_quality) qualSel.value = settings.image_quality;
    if (enabledToggle) enabledToggle.checked = settings.image_gen_enabled === true;
  } catch (e) { console.warn('Failed to load settings', e); }

  function syncImgDisabled() {
    var off = enabledToggle && !enabledToggle.checked;
    var card = enabledToggle ? enabledToggle.closest('.admin-card') : null;
    if (card) card.style.opacity = off ? '0.45' : '';
    if (configWrap) configWrap.style.pointerEvents = off ? 'none' : '';
  }
  syncImgDisabled();

  async function saveSettings() {
    try {
      const res = await _postSettings({ image_gen_enabled: enabledToggle ? enabledToggle.checked : false, image_model: modelSel.value, image_quality: qualSel.value });
      if (!res.ok) throw new Error(await res.text().catch(() => `HTTP ${res.status}`));
      flashStatus(msg, 'Saved', false);
    } catch (e) { flashSaveError(msg, e); }
  }
  modelSel.addEventListener('change', saveSettings);
  qualSel.addEventListener('change', saveSettings);
  if (enabledToggle) enabledToggle.addEventListener('change', function() { syncImgDisabled(); saveSettings(); });
}
