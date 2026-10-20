// Platform detection + AltGr-keystroke helper, shared by the keybind code.

// macOS and iOS Option also sets AltGraph, so Apple platforms are never AltGr.
export const IS_MAC =
  /Mac|iPhone|iPad/.test((typeof navigator !== 'undefined' && navigator.platform) || '') ||
  /Mac/.test((typeof navigator !== 'undefined' && navigator.userAgent) || '');

// True for an AltGr keystroke, which browsers report as Ctrl+Alt plus the
// AltGraph modifier state; a genuine left Ctrl+Alt lacks AltGraph.
export function isAltGrEvent(e, isMac = IS_MAC) {
  return (
    !isMac &&
    !!e.ctrlKey &&
    !!e.altKey &&
    !!(e.getModifierState && e.getModifierState('AltGraph'))
  );
}
