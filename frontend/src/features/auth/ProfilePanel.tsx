import { useAuth } from "./AuthContext";

const C = { ink: "#1a2233", muted: "#5c6676", faint: "#8b94a3", border: "#e2e7ee", card: "#fff", chip: "#f5f7fa", danger: "#c02b1d" };

function initials(name: string): string {
  const p = name.trim().split(/\s+/);
  return ((p[0]?.[0] ?? "") + (p[1]?.[0] ?? "")).toUpperCase() || name.slice(0, 2).toUpperCase();
}

export function ProfilePanel({ onClose }: { onClose: () => void }) {
  const { annotator, signOut } = useAuth();
  if (!annotator) return null;
  const a = annotator;
  const s = a.stats ?? { sessions: 0, submitted: 0, golden: 0, breaker: 0, flagged: 0 };
  const stat = (label: string, value: number, hue?: string) => (
    <div style={{ background: C.chip, borderRadius: 10, padding: "12px 14px", minWidth: 84 }}>
      <div style={{ fontSize: 22, fontWeight: 800, color: hue ?? C.ink, fontVariantNumeric: "tabular-nums" }}>{value}</div>
      <div style={{ fontSize: 11.5, color: C.muted, marginTop: 2 }}>{label}</div>
    </div>
  );

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(20,28,44,.38)", display: "flex", alignItems: "flex-start", justifyContent: "center", zIndex: 1000, padding: "70px 20px", fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif" }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: C.card, borderRadius: 16, width: "100%", maxWidth: 420, boxShadow: "0 12px 40px rgba(20,30,50,.22)", overflow: "hidden" }}>
        <div style={{ padding: "22px 22px 18px", display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ width: 52, height: 52, borderRadius: "50%", background: `hsl(${a.avatarHue} 62% 52%)`, color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 19, flexShrink: 0 }}>{initials(a.displayName)}</span>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 17, fontWeight: 700, color: C.ink }}>{a.displayName}</div>
            <div style={{ fontSize: 13, color: C.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.email}</div>
            <span style={{ display: "inline-block", marginTop: 5, fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: ".05em", color: "#4f46e5", background: "#eceafc", borderRadius: 20, padding: "2px 9px" }}>{a.role}</span>
          </div>
        </div>
        <div style={{ padding: "0 22px 8px", display: "flex", gap: 8, flexWrap: "wrap" }}>
          {stat("Sessions", s.sessions)}
          {stat("Submitted", s.submitted)}
          {stat("Golden", s.golden, "#0f7a44")}
          {stat("Breakers", s.breaker, "#b26a00")}
          {stat("Flagged", s.flagged, C.danger)}
        </div>
        <div style={{ padding: "14px 22px", fontSize: 12, color: C.faint }}>
          {a.lastLoginAt ? `Last login ${new Date(a.lastLoginAt).toLocaleString()}` : "First session"}
        </div>
        <div style={{ borderTop: `1px solid ${C.border}`, padding: "14px 22px", display: "flex", justifyContent: "space-between", gap: 10 }}>
          <button onClick={onClose} style={{ border: `1px solid ${C.border}`, background: "#fff", color: C.ink, borderRadius: 9, padding: "9px 16px", fontSize: 13.5, fontWeight: 600, cursor: "pointer" }}>Close</button>
          <button onClick={() => void signOut()} style={{ border: "none", background: "#fbecea", color: C.danger, borderRadius: 9, padding: "9px 16px", fontSize: 13.5, fontWeight: 700, cursor: "pointer" }}>Log out</button>
        </div>
      </div>
    </div>
  );
}
