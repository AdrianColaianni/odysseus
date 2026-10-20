// static/js/search.js

/**
 * Search settings management — reads active provider from admin settings.
 */

import { getSettings, invalidateSettings } from './appConfig.js';

let _provider = 'searxng';

export async function init() {
  try {
    const s = await getSettings();
    _provider = s.search_provider || 'searxng';
  } catch (e) {
    console.warn('Search provider settings failed to load; keeping the default:', e);
  }
}

const _labels = {
  searxng: 'SearXNG', brave: 'Brave', duckduckgo: 'DuckDuckGo',
  google_pse: 'Google', tavily: 'Tavily', serper: 'Serper',
  disabled: 'search (disabled)',
};

export function getProviderLabel() {
  return _labels[_provider] || _provider;
}

/** Re-fetch after admin saves new settings */
export function refresh() {
  // The point of this call is to observe settings just written, so drop the
  // shared snapshot first.
  invalidateSettings();
  init();
}

const searchModule = {
  init,
  getProviderLabel,
  refresh
};

export default searchModule;
