/** Shared-window integration: docking and stacking. */
export function createWindowLayout({
  makeWindowDraggable,
  clearDockSide,
  applyEdgeDock,
  topToolWindowZ
}) {
  function _wireNotesWindow(pane) {
    if (!pane || pane.dataset.windowDragWired === '1') return;
    const header = pane.querySelector('.notes-pane-header');
    if (!header) return;
    pane.dataset.windowDragWired = '1';
    makeWindowDraggable(pane, {
      content: pane,
      header,
      fsClass: 'notes-window-fullscreen',
      skipSelector: 'button, input, select, textarea, label, .notes-mobile-grabber',
      enableDock: true,
      enableLeftDock: true,
      onExitFullscreen: () => {
        _restoreNotesSidebarDock(pane);
      },
    });
  }

  function _clearNotesSnapStyles(pane) {
    if (!pane) return;
    const hadLeft = pane.classList.contains('modal-left-docked');
    const hadRight = pane.classList.contains('modal-right-docked');
    pane.classList.remove('notes-window-fullscreen', 'modal-left-docked', 'modal-right-docked');
    if (hadLeft) clearDockSide('left', pane);
    if (hadRight) clearDockSide('right', pane);
    ['position', 'left', 'top', 'right', 'bottom', 'width', 'max-width', 'height',
      'max-height', 'margin', 'transform', 'border-radius']
      .forEach((prop) => pane.style.removeProperty(prop));
    delete pane.dataset._tilePreSnap;
    delete pane.dataset._tileZone;
    delete pane._preDockSnapshot;
    delete pane._dockSide;
    delete pane._dockSuspended;
  }

  function _restoreNotesSidebarDock(pane) {
    if (!pane || window.innerWidth <= 768) return;
    _clearNotesSnapStyles(pane);
    if (!pane.isConnected) return;
    applyEdgeDock(pane, 'right');
  }

  function _topToolWindowZ(exclude = null) {
    return topToolWindowZ({ exclude });
  }

  function _bringNotesToFront(pane = document.getElementById('notes-pane')) {
    if (!pane) return;
    const backdrop = document.getElementById('notes-pane-backdrop') || pane.parentElement;
    const z = _topToolWindowZ(backdrop) + 1;
    if (backdrop) backdrop.style.setProperty('z-index', String(z), 'important');
    try {
      window.dispatchEvent(new CustomEvent('odysseus:modal-opened', {
        detail: { id: 'notes-panel', modal: pane },
      }));
    } catch (_) {}
  }


  return { _wireNotesWindow, _restoreNotesSidebarDock, _bringNotesToFront };
}
