/** Parse `dot.path = value` lines out of a gym correction into resume edits, so a
 *  human correction becomes a concrete world-state change the gym re-verifies.
 *  Values coerce to number / bool / null / JSON where possible, else stay strings. */
export function parseStateEdits(text: string): Record<string, unknown> {
  const edits: Record<string, unknown> = {};
  for (const line of text.split("\n")) {
    const m = line.match(/^\s*([A-Za-z0-9_.\-]+)\s*=\s*(.+?)\s*$/);
    if (!m) continue;
    const raw = m[2];
    let v: unknown = raw;
    if (raw === "true") v = true;
    else if (raw === "false") v = false;
    else if (raw === "null") v = null;
    else if (/^-?\d+(\.\d+)?$/.test(raw)) v = Number(raw);
    else if (/^[[{]/.test(raw)) {
      try {
        v = JSON.parse(raw);
      } catch {
        /* keep as string */
      }
    }
    edits[m[1]] = v;
  }
  return edits;
}
