// static/js/markdown/tableRow.js
//
// Pure helper for splitting a markdown table row into cells. No DOM —
// safe to import anywhere and to unit-test under node.

// Split a "| a | b | c |" row into trimmed cell strings. Only the outer pipes
// go, so an empty interior cell keeps its column.
export function splitTableRow(row) {
  const text = typeof row === 'string' ? row : '';
  return text
    .replace(/^\s*\|/, '')
    .replace(/\|\s*$/, '')
    .split('|')
    .map((cell) => cell.trim());
}
