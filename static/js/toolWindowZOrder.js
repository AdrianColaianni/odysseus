export const TOOL_WINDOW_SELECTOR = 'body > .modal, body > .research-overlay, body > .notes-pane-backdrop';

export function topToolWindowZ(options = {}) {
  const {
    exclude = null,
    root = globalThis.document,
    getStyle = globalThis.getComputedStyle,
    floor = 250,
  } = options;
  let top = floor;
  if (!root || typeof root.querySelectorAll !== 'function' || typeof getStyle !== 'function') return top;
  root.querySelectorAll(TOOL_WINDOW_SELECTOR).forEach(el => {
    if (!el || el === exclude) return;
    if (el.classList?.contains('hidden') || el.classList?.contains('modal-minimized')) return;
    const cs = getStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const z = parseInt(cs.zIndex, 10);
    if (Number.isFinite(z)) top = Math.max(top, z);
  });
  return top;
}

export function nextToolWindowZ(options = {}) {
  const { current = null } = options;
  const top = topToolWindowZ(options);
  const currentZ = parseInt(current, 10);
  if (Number.isFinite(currentZ) && currentZ > top) return currentZ;
  return top + 1;
}

// One counter for every bring-to-front path. Its 1000 floor keeps a raised
// window above the static .modal z-indexes (250, 260).
let _raisedZ = 1000;

// Raise `win` above every other open tool window unless it already is.
export function raiseToolWindow(win) {
  const current = getComputedStyle(win).zIndex;
  if (nextToolWindowZ({ exclude: win, current }) === parseInt(current, 10)) return;
  _raisedZ = nextToolWindowZ({ exclude: win, floor: _raisedZ });
  win.style.setProperty('z-index', String(_raisedZ), 'important');
}

// Dock chips pinned by the minimized-dock drag interactions reach z 10030
// (free-drag) / 10020 (mobile rest) — see modalManager.js. A body-portaled
// dropdown has to clear those too, not just the open tool-window stack, so this
// floor keeps it above a chip even when no modal is currently raised.
const DOCK_OVERLAY_FLOOR = 10030;

// The z a body-portaled dropdown/menu needs to sit just above every open tool
// window and dock chip. The bring-to-front counter climbs without bound, so
// a fixed z falls behind its own modal over a long session (#4720).
export function topPortalZ(options = {}) {
  return Math.max(topToolWindowZ(options), DOCK_OVERLAY_FLOOR) + 1;
}
