// Pure helper, no DOM: safe to import anywhere and to unit-test under node.

// Return the longest key that is a substring of `name`, or null. Longest key
// wins, so "gpt-4o-mini" matches its own key rather than "gpt-4o".
export function matchModelKey(name, keys) {
  const n = (name || '').toLowerCase();
  let best = null;
  for (const key of keys) {
    if (n.includes(key) && (best === null || key.length > best.length)) {
      best = key;
    }
  }
  return best;
}
