// Shared window drag. Options: content (the moved element), header (the
// handle), fsClass + onExitFullscreen (drag a fullscreen window down to
// unsnap), skipSelector, onDragStart, onDragEnd({ rect }), enableTouch,
// mobileSkip (viewport width below which drag is off), enableDock.

import { makeEdgeDockController } from './modalSnap.js';
import { makeWindowResizable } from './windowResize.js';

const UNSNAP_PX = 24;     // cursor distance from top before fullscreen exits

export function makeWindowDraggable(modal, options = {}) {
  const content = options.content;
  const header = options.header;
  if (!content || !header) return;
  const fsClass = options.fsClass || null;
  const onExitFullscreen = options.onExitFullscreen || null;
  const onDragEnd = options.onDragEnd || null;
  const onDragStart = options.onDragStart || null;
  const skipSelector = options.skipSelector || 'button, input, select';
  const mobileSkip = (typeof options.mobileSkip === 'number') ? options.mobileSkip : 768;
  const enableTouch = options.enableTouch !== false;
  // tileManager owns new edge snaps; these controllers only let a docked
  // window be pulled loose.
  const enableDock = options.enableDock !== false && !!modal;

  header.style.cursor = 'move';
  header.style.userSelect = 'none';

  // Edge/corner resize. Every draggable window also becomes resizable — the
  // same gesture a native desktop window uses (grab an edge or corner, drag).
  // Skipped on mobile (windows are full-screen sheets there) and while the
  // window is fullscreen-snapped or docked. Wired here so all ~12 callsites
  // get it without per-file changes.
  if (options.enableResize !== false) {
    const _dockClasses = ['modal-right-docked', 'modal-left-docked'];
    makeWindowResizable(content, {
      modal,
      mobileSkip,
      minWidth: options.minWidth,
      minHeight: options.minHeight,
      isLocked: () => (fsClass && modal && modal.classList.contains(fsClass))
        || (modal && _dockClasses.some((c) => modal.classList.contains(c))),
      storageKey: options.resizeStorageKey
        || (modal && modal.id ? 'winsize-' + modal.id
          : (content.id ? 'winsize-' + content.id : null)),
    });
  }

  // A native-window-style reset gesture: double-clicking unused header/title
  // space restores the authored size and lets the modal overlay center it.
  // Controls keep their own double-click behaviour, and mobile sheets retain
  // their fixed drawer geometry.
  header.addEventListener('dblclick', (event) => {
    if (mobileSkip > 0 && window.innerWidth <= mobileSkip) return;
    if (skipSelector && event.target.closest(skipSelector)) return;
    if (event.target.closest('button, input, select, textarea, a, [contenteditable="true"]')) return;
    if (typeof content._resetWindowGeometry !== 'function') return;
    if (!content._resetWindowGeometry()) return;
    event.preventDefault();
    event.stopPropagation();
  });

  const rightDock = enableDock ? makeEdgeDockController(modal, 'right') : null;
  // Left dock is enabled by default too. modalSnap collapses the wide sidebar
  // and anchors the panel beside the icon rail, so it no longer collides with
  // the navigation. Callers can still pass enableLeftDock:false for a special
  // modal that should only dock right.
  const leftDock = (enableDock && options.enableLeftDock !== false) ? makeEdgeDockController(modal, 'left') : null;

  // Per-drag state, reset on mousedown.
  let dragging = false;
  let startX = 0, startY = 0;
  let startLeft = 0, startTop = 0;
  // Whether the pointer actually moved beyond a small threshold this drag.
  // Used to suppress the synthetic click the browser fires on mouseup —
  // header click handlers (e.g. "collapse expanded card / back to list")
  // would otherwise fire after a drag and collapse the modal contents.
  let movedDuringDrag = false;
  const MOVE_THRESHOLD = 4;

  const _exitFs = (cx, cy) => {
    if (!onExitFullscreen) return;
    if (fsClass && modal && !modal.classList.contains(fsClass)) return;
    onExitFullscreen(cx, cy);
    // After exit, re-anchor the drag offsets to the new windowed rect so
    // the drag continues smoothly from the cursor's position.
    const r = content.getBoundingClientRect();
    startX = cx; startY = cy;
    startLeft = r.left; startTop = r.top;
  };

  const _isFullscreen = () => fsClass && modal && modal.classList.contains(fsClass);

  const _startDrag = (cx, cy) => {
    dragging = true;
    if (modal) modal.classList.add('modal-dragging');
    // Cancel any in-flight open animation so we don't pin a mid-animation
    // rect and then jump once the animation settles.
    content.getAnimations()
      .filter(a => a.playState !== 'finished')
      .forEach(a => a.cancel());
    const rect = content.getBoundingClientRect();
    if (onDragStart) onDragStart({ rect, cx, cy });
    startX = cx; startY = cy;
    startLeft = rect.left; startTop = rect.top;
    // Pin position so the drag follows the cursor instead of fighting a
    // centering transform / margin. Inline styles win unless CSS uses
    // !important (the fullscreen rules do, by design).
    content.style.position = 'fixed';
    content.style.left = startLeft + 'px';
    content.style.top = startTop + 'px';
    content.style.transform = 'none';
    content.style.margin = '0';
  };

  const _onMove = (cx, cy) => {
    if (!dragging) return;
    if (_isFullscreen()) {
      if (cy > UNSNAP_PX) {
        _exitFs(cx, cy);
      } else {
        if (rightDock) rightDock.release();
        if (leftDock) leftDock.release();
      }
      return;
    }
    // Right-docked: pulling away from the right edge un-docks. Same for left.
    if (rightDock && modal && modal.classList.contains('modal-right-docked')) {
      if (rightDock.onMove(cx, cy)) {
        const r = content.getBoundingClientRect();
        startX = cx; startY = cy;
        startLeft = r.left; startTop = r.top;
      }
      return;
    }
    if (leftDock && modal && modal.classList.contains('modal-left-docked')) {
      if (leftDock.onMove(cx, cy)) {
        const r = content.getBoundingClientRect();
        startX = cx; startY = cy;
        startLeft = r.left; startTop = r.top;
      }
      return;
    }
    // Windowed: just follow the cursor.
    if (Math.abs(cx - startX) > MOVE_THRESHOLD || Math.abs(cy - startY) > MOVE_THRESHOLD) {
      movedDuringDrag = true;
    }
    content.style.left = (startLeft + cx - startX) + 'px';
    content.style.top = (startTop + cy - startY) + 'px';
    if (rightDock) rightDock.release();
    if (leftDock) leftDock.release();
  };

  const _onEnd = () => {
    if (!dragging) return;
    dragging = false;
    if (modal) modal.classList.remove('modal-dragging');
    if (rightDock) rightDock.release();
    if (leftDock) leftDock.release();
    if (onDragEnd) onDragEnd({ rect: content.getBoundingClientRect() });
  };

  header.addEventListener('mousedown', (e) => {
    if (mobileSkip > 0 && window.innerWidth <= mobileSkip) return;
    if (skipSelector && e.target.closest(skipSelector)) return;
    e.preventDefault();
    movedDuringDrag = false;
    _startDrag(e.clientX, e.clientY);
    const onMove = (ev) => _onMove(ev.clientX, ev.clientY);
    const onUp = (ev) => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      _onEnd();
      // If the pointer actually moved, swallow the synthetic click the
      // browser fires next — otherwise a header click handler (collapse
      // expanded card / "back to list") runs and undoes the drag intent.
      if (movedDuringDrag) {
        const swallow = (clickEv) => {
          clickEv.stopPropagation();
          clickEv.preventDefault();
        };
        header.addEventListener('click', swallow, { capture: true, once: true });
        // Safety: if no click fires (some browsers), drop the listener.
        setTimeout(() => header.removeEventListener('click', swallow, { capture: true }), 50);
      }
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });

  if (enableTouch) {
    header.addEventListener('touchstart', (e) => {
      if (mobileSkip > 0 && window.innerWidth <= mobileSkip) return;
      if (skipSelector && e.target.closest(skipSelector)) return;
      const t = e.touches[0];
      if (!t) return;
      movedDuringDrag = false;
      _startDrag(t.clientX, t.clientY);
      const onMove = (ev) => {
        const tt = ev.touches[0];
        if (tt) _onMove(tt.clientX, tt.clientY);
      };
      const onEnd = () => {
        document.removeEventListener('touchmove', onMove);
        document.removeEventListener('touchend', onEnd);
        document.removeEventListener('touchcancel', onEnd);
        _onEnd();
      };
      document.addEventListener('touchmove', onMove, { passive: true });
      document.addEventListener('touchend', onEnd);
      document.addEventListener('touchcancel', onEnd);
    }, { passive: true });
  }
}
