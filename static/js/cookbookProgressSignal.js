// Watchdog liveness signal: the downloaded-byte counter when there is one, else
// the output tail, since pip resolves and native builds print lines but no bytes.
export function computeProgressSignal(bytes, dlAgg, lastPct, snapshot) {
  if (bytes) return bytes;
  const base = dlAgg != null ? String(dlAgg) : (lastPct || '0');
  return base + '|' + String(snapshot || '').slice(-300);
}
