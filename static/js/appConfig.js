// static/js/appConfig.js
//
// One shared, invalidatable cache for /api/auth/settings and /api/tools, so
// every module (and every ?v= instance of a module) sees one snapshot.
//
// WRITERS MUST INVALIDATE. Anything that POSTs /api/auth/settings calls
// invalidateSettings(); anything that POSTs /api/tools calls invalidateTools()
// *and* invalidateSettings(), because that route persists `disabled_tools`
// into the same settings store (routes/model_routes.py).
//
// The resolved object is shared by reference, so treat it as read-only: copy
// before mutating (`{ ...await getSettings() }`).

// Written by login.html immediately before it redirects to '/', so the first
// load after a login can skip the request entirely. Consumed once per page
// load, by whichever module asks for settings first.
const PREFETCH_KEY = 'ody-prefetch-settings';

const _URLS = { settings: '/api/auth/settings', tools: '/api/tools' };
const _cache = { settings: null, tools: null };

function _readPrefetchedSettings() {
  try {
    const raw = sessionStorage.getItem(PREFETCH_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(PREFETCH_KEY);
    return JSON.parse(raw);
  } catch (_) {
    return null;
  }
}

// A rejected promise must not stay in the slot. Plain `??=` memoisation would
// keep it, so one transient blip during boot would leave keybinds, TTS and the
// search provider on their defaults for the whole session with no retry. Clear
// the slot on failure — unless a later invalidate/refetch already replaced it —
// and rethrow, so every caller's existing .catch() still runs exactly as before.
function _get(key) {
  if (_cache[key]) return _cache[key];
  const pending = fetch(_URLS[key], { credentials: 'same-origin' })
    .then(r => r.json())
    .catch(err => {
      if (_cache[key] === pending) _cache[key] = null;
      throw err;
    });
  _cache[key] = pending;
  return pending;
}

/** GET /api/auth/settings, once per page load (or once per invalidation). */
export function getSettings() {
  if (!_cache.settings) {
    const prefetched = _readPrefetchedSettings();
    if (prefetched) _cache.settings = Promise.resolve(prefetched);
  }
  return _get('settings');
}

/** GET /api/tools, once per page load (or once per invalidation). */
export function getTools() {
  return _get('tools');
}

/** Call after any write that can change settings. */
export function invalidateSettings() {
  _cache.settings = null;
}

/** Call after any write that can change the tool enable/disable state. */
export function invalidateTools() {
  _cache.tools = null;
}
