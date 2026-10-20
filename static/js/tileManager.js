// Desktop window tiling for tool modals: watches header drags, shows a ghost
// preview near the top (maximize), left or right (half) edge, and snaps on
// release. Each content remembers its pre-snap geometry for unsnap.

import { clearDockSide } from './modalSnap.js';

const EDGE_THRESHOLD_PX = 24;     // how close to an edge counts as "near"

let _ghost = null;
let _activeZone = null;
let _tracking = null; // { content, startRect }

function _isDesktop() { return window.innerWidth > 768; }

function _ensureGhost() {
  if (_ghost) return _ghost;
  _ghost = document.createElement('div');
  _ghost.id = 'tile-ghost';
  document.body.appendChild(_ghost);
  return _ghost;
}

function _hideGhost() {
  if (_ghost) _ghost.classList.remove('visible');
}

function _showGhost(rect) {
  const g = _ensureGhost();
  g.style.left = rect.left + 'px';
  g.style.top  = rect.top  + 'px';
  g.style.width  = rect.width  + 'px';
  g.style.height = rect.height + 'px';
  g.classList.add('visible');
}

function _viewportSafeRect() {
  // Reserve navigation on whichever edge it actually occupies. Treating a
  // right-side sidebar as left navigation makes leftEdge nearly viewport-wide,
  // yielding negative tile widths and sending dragged windows off-screen.
  const sidebar = document.getElementById('sidebar');
  const rail = document.querySelector('.icon-rail') || document.querySelector('#icon-rail');
  let leftEdge = 4;
  let rightEdge = window.innerWidth - 4;
  const reserve = (element, isRight) => {
    if (!element || window.getComputedStyle(element).display === 'none') return;
    const rect = element.getBoundingClientRect();
    if (!rect.width || rect.bottom <= 0 || rect.top >= window.innerHeight) return;
    if (isRight) rightEdge = Math.min(rightEdge, rect.left - 4);
    else leftEdge = Math.max(leftEdge, rect.right + 4);
  };
  if (sidebar && !sidebar.classList.contains('hidden')) {
    reserve(sidebar, sidebar.classList.contains('right-side'));
  }
  reserve(rail, rail?.classList.contains('right-side'));
  // Keep a valid workspace even during a transient resize frame.
  if (rightEdge <= leftEdge) {
    leftEdge = 4;
    rightEdge = window.innerWidth - 4;
  }
  return {
    left: leftEdge,
    top: 4,
    right: rightEdge,
    bottom: window.innerHeight - 4,
  };
}

export function _zoneForPointer(x, y) {
  const safe = _viewportSafeRect();
  const W = safe.right - safe.left;
  const H = safe.bottom - safe.top;

  if (y <= safe.top + EDGE_THRESHOLD_PX)
    return { name: 'maximize', rect: { left: safe.left, top: safe.top, width: W, height: H } };

  // Symmetric side half-snaps. The safe rect starts to the right of
  // the sidebar/rail so left-half does not cover navigation.
  if (x <= safe.left + EDGE_THRESHOLD_PX)
    return { name: 'left-half', rect: { left: safe.left, top: safe.top, width: W / 2, height: H } };
  if (x >= safe.right - EDGE_THRESHOLD_PX)
    return { name: 'right-half', rect: { left: safe.left + W / 2, top: safe.top, width: W / 2, height: H } };
  return null;
}

export function _zoneForContent(content, x, y) {
  const modal = content && content.closest && content.closest('.modal, .research-overlay');
  const zone = _zoneForPointer(x, y);
  if (!zone) return null;
  // Settings has a dense two-column layout; the full-height sidebar-style dock
  // crushes it. Let it tile only into the normal right half, where the nav can
  // flip to top tabs via CSS when the window gets narrow.
  if (modal && modal.id === 'settings-modal' && zone.name !== 'right-half') return null;
  if (modal && (modal.id === 'cookbook-modal'
      || modal.id === 'theme-modal')
      && zone.name !== 'maximize') return null;
  return zone;
}

function _clearEdgeDockResidue(modal, content) {
  const hadDockState = !!(
    (modal && (modal.classList.contains('modal-left-docked') || modal.classList.contains('modal-right-docked')))
    || (content && (content._preDockSnapshot || content._dockSide || content._dockSuspended))
  );
  if (modal) {
    const hadLeft = modal.classList.contains('modal-left-docked');
    const hadRight = modal.classList.contains('modal-right-docked');
    modal.classList.remove('modal-left-docked', 'modal-right-docked');
    if (hadLeft) clearDockSide('left', modal);
    if (hadRight) clearDockSide('right', modal);
    if (modal._dockCloseWatcher) {
      modal._dockCloseWatcher.obs?.disconnect();
      modal._dockCloseWatcher.parentObs?.disconnect();
      delete modal._dockCloseWatcher;
    }
  }
  if (!content) return;
  if (content._leftDockNavObs) {
    content._leftDockNavObs.navObs.disconnect();
    window.removeEventListener('resize', content._leftDockNavObs.reanchor);
    delete content._leftDockNavObs;
  }
  delete content._preDockSnapshot;
  delete content._dockSide;
  delete content._dockSuspended;
  if (hadDockState) {
    ['right', 'bottom', 'max-width', 'border-radius']
      .forEach(p => content.style.removeProperty(p));
  }
}

function _applySnap(content, rect, zoneName) {
  // Leftover edge-dock body padding would double-count with the safe rect,
  // so a tile snap clears it first.
  const _modal = content.closest && content.closest('.modal, .research-overlay');
  const _fromRect = content.getBoundingClientRect();
  _clearEdgeDockResidue(_modal, content);

  // Stash pre-snap geometry once, as a concrete fixed position: empty
  // left/top would let the .modal flex parent re-center the window.
  if (!content.dataset._tilePreSnap) {
    content.dataset._tilePreSnap = JSON.stringify({
      position: 'fixed',
      left:   content.style.left || (Math.round(_fromRect.left) + 'px'),
      top:    content.style.top  || (Math.round(_fromRect.top)  + 'px'),
      width:  content.style.width,
      height: content.style.height,
      maxHeight: content.style.maxHeight,
      transform: content.style.transform,
    });
  }
  content.style.transition = 'left 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), top 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), width 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), height 0.22s cubic-bezier(0.34, 1.56, 0.64, 1)';
  // Use !important — some modals (e.g. cookbook) carry inline width/height
  // and CSS that otherwise re-center the .modal-content, which made the snap
  // "jump back to the middle" on release.
  content.style.setProperty('position', 'fixed', 'important');
  content.style.setProperty('left',   rect.left   + 'px', 'important');
  content.style.setProperty('top',    rect.top    + 'px', 'important');
  content.style.setProperty('width',  rect.width  + 'px', 'important');
  content.style.setProperty('height', rect.height + 'px', 'important');
  content.style.setProperty('max-height', rect.height + 'px', 'important');
  content.style.setProperty('margin', '0', 'important');
  content.style.setProperty('transform', 'none', 'important');
  content.dataset._tileZone = zoneName;
  setTimeout(() => { content.style.transition = ''; }, 250);
}

function _unsnap(content) {
  const pre = content.dataset._tilePreSnap;
  if (!pre) return;
  // Clear the !important snap props first — Object.assign can't override them.
  ['position', 'left', 'top', 'width', 'height', 'max-height', 'margin', 'transform']
    .forEach(p => content.style.removeProperty(p));
  try {
    const r = JSON.parse(pre);
    Object.assign(content.style, r);
  } catch {}
  // Keep it a fixed floating window so the restored left/top actually take
  // effect — without position:fixed the .modal flex parent re-centers it.
  if (!content.style.position) content.style.position = 'fixed';
  delete content.dataset._tilePreSnap;
  delete content.dataset._tileZone;
}

function _findDragTarget(e) {
  const header = e.target.closest('.modal-header');
  if (!header) return null;
  // Skip clicks on header buttons (close, minimize, etc.)
  if (e.target.closest('button')) return null;
  const modal = header.closest('.modal, .research-overlay');
  if (!modal) return null;
  const content = modal.querySelector('.modal-content, .research-pane');
  return content || null;
}

document.addEventListener('pointerdown', (e) => {
  if (!_isDesktop()) return;
  const content = _findDragTarget(e);
  if (!content) return;

  // If we're already snapped, dragging away should unsnap immediately so the
  // user can move freely.
  if (content.dataset._tileZone) {
    // Defer slightly so pointermove threshold is met before unsnap kicks in
    _tracking = { content, startX: e.clientX, startY: e.clientY, willUnsnap: true };
  } else {
    _tracking = { content, startX: e.clientX, startY: e.clientY, willUnsnap: false };
  }
});

document.addEventListener('pointermove', (e) => {
  if (!_tracking) return;
  if (!_isDesktop()) return;
  const dx = e.clientX - _tracking.startX;
  const dy = e.clientY - _tracking.startY;
  if (Math.hypot(dx, dy) < 6) return;

  // Unsnap on first significant move
  if (_tracking.willUnsnap) {
    _unsnap(_tracking.content);
    _tracking.willUnsnap = false;
  }

  // Detect snap zone under cursor
  const zone = _zoneForContent(_tracking.content, e.clientX, e.clientY);
  if (zone) {
    _showGhost(zone.rect);
    _activeZone = zone;
  } else {
    _hideGhost();
    _activeZone = null;
  }
});

document.addEventListener('pointerup', () => {
  if (!_tracking) return;
  const t = _tracking;
  _tracking = null;
  _hideGhost();
  if (_activeZone && _isDesktop()) {
    _applySnap(t.content, _activeZone.rect, _activeZone.name);
  }
  _activeZone = null;
});

// Re-clamp every currently-snapped window so it keeps filling its zone after
// the safe-rect changes (viewport resize, sidebar toggle, etc.).
function _reclampAll(animate = false) {
  document.querySelectorAll('.modal-content[data-_tile-zone], .research-pane[data-_tile-zone]').forEach(c => {
    const name = c.dataset._tileZone;
    if (!name) return;
    const safe = _viewportSafeRect();
    const W = safe.right - safe.left, H = safe.bottom - safe.top;
    let r;
    switch (name) {
      // Migrate every retired top-edge state to the single sidebar-aware one.
      case 'fullscreen':
      case 'maximize':
      case 'top-half':
        c.dataset._tileZone = 'maximize';
        r = { left: safe.left, top: safe.top, width: W, height: H };
        break;
      case 'left-half':      r = { left: safe.left, top: safe.top, width: W/2, height: H }; break;
      case 'right-half':     r = { left: safe.left + W/2, top: safe.top, width: W/2, height: H }; break;
      case 'bottom-half':
        _unsnap(c);
        return;
      case 'top-left':       r = { left: safe.left, top: safe.top, width: W/2, height: H/2 }; break;
      case 'top-right':      r = { left: safe.left + W/2, top: safe.top, width: W/2, height: H/2 }; break;
      case 'bottom-left':    r = { left: safe.left, top: safe.top + H/2, width: W/2, height: H/2 }; break;
      case 'bottom-right':   r = { left: safe.left + W/2, top: safe.top + H/2, width: W/2, height: H/2 }; break;
      default: return;
    }
    if (animate) {
      c.style.transition = 'left 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), top 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), width 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), height 0.22s cubic-bezier(0.34, 1.56, 0.64, 1)';
      setTimeout(() => { c.style.transition = ''; }, 250);
    }
    c.style.setProperty('left', r.left + 'px', 'important');
    c.style.setProperty('top',  r.top  + 'px', 'important');
    c.style.setProperty('width', r.width + 'px', 'important');
    c.style.setProperty('height', r.height + 'px', 'important');
    c.style.setProperty('max-height', r.height + 'px', 'important');
  });
}

let _reclampPending = false;
function _reclampAllThrottled(animate) {
  if (_reclampPending) return;
  _reclampPending = true;
  requestAnimationFrame(() => {
    try { _reclampAll(animate); } finally { _reclampPending = false; }
  });
}

window.addEventListener('resize', () => _reclampAllThrottled(false));

// Watch the sidebar's class attribute so toggling hidden/right-side re-tiles
// any snapped modal that was anchored to the old safe-rect.
function _watchSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) {
    // Sidebar may not be in the DOM yet during early init.
    requestAnimationFrame(_watchSidebar);
    return;
  }
  const mo = new MutationObserver(() => _reclampAllThrottled(true));
  mo.observe(sidebar, { attributes: true, attributeFilter: ['class'] });
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _watchSidebar);
} else {
  _watchSidebar();
}

// Show the snap-zone ghost for a point and return the zone (or null).
export function previewZoneAt(x, y, target = null) {
  if (!_isDesktop()) { _hideGhost(); _activeZone = null; return null; }
  const content = target && target.querySelector
    ? (target.querySelector('.modal-content, .research-pane') || target)
    : null;
  const zone = content ? _zoneForContent(content, x, y) : _zoneForPointer(x, y);
  if (zone) { _showGhost(zone.rect); _activeZone = zone; }
  else { _hideGhost(); _activeZone = null; }
  return zone;
}

export function clearPreview() {
  _hideGhost();
  _activeZone = null;
}

// Snap a modal (its .modal-content) into a previously-detected zone.
export function snapModalToZone(modal, zone) {
  if (!modal || !zone) return;
  const content = modal.querySelector ? (modal.querySelector('.modal-content, .research-pane') || modal) : modal;
  if (!content) return;
  // Map the retired top states onto the sidebar-aware maximize.
  if (zone.name === 'fullscreen' || zone.name === 'top-half') {
    const safe = _viewportSafeRect();
    zone = {
      name: 'maximize',
      rect: {
        left: safe.left,
        top: safe.top,
        width: safe.right - safe.left,
        height: safe.bottom - safe.top,
      },
    };
  }
  if (modal.id === 'settings-modal' && zone.name !== 'right-half') return;
  _applySnap(content, zone.rect, zone.name);
}
