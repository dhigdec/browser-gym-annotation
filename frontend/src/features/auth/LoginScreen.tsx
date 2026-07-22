import { useState } from "react";
import { useAuth } from "./AuthContext";

// The seeded dummy accounts (dev/testing only). Click one to fill the email; the
// shared dev password is shown below. These are throwaway test fixtures.
const TEST_ACCOUNTS = [
  { email: "ana@deccan.ai", name: "Ana Rivera", role: "reviewer" },
  { email: "ben@deccan.ai", name: "Ben Okafor", role: "annotator" },
  { email: "chloe@deccan.ai", name: "Chloe Tan", role: "annotator" },
  { email: "diego@deccan.ai", name: "Diego Santos", role: "annotator" },
  { email: "ela@deccan.ai", name: "Ela Novak", role: "annotator" },
];
const DEV_PASSWORD = "annotate1";

const C = {
  bg: "#f4f6fa", card: "#ffffff", ink: "#1a2233", muted: "#5c6676", faint: "#8b94a3",
  border: "#e2e7ee", primary: "#4f46e5", primaryInk: "#ffffff", danger: "#c02b1d", chip: "#f2f4f8",
};

export function LoginScreen() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    const r = await signIn(email.trim(), password);
    setBusy(false);
    if (!r.ok) setError(r.error);
  };

  return (
    <div style={{ minHeight: "100vh", background: C.bg, display: "flex", alignItems: "center", justifyContent: "center", padding: 24, fontFamily: "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif" }}>
      <div style={{ width: "100%", maxWidth: 400 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18, justifyContent: "center" }}>
          <span style={{ width: 34, height: 34, borderRadius: 9, background: C.primary, color: "#fff", display: "inline-flex", alignItems: "center", justifyContent: "center", fontWeight: 800, fontSize: 18 }}>◆</span>
          <span style={{ fontWeight: 700, fontSize: 17, color: C.ink }}>Browser-Use Gym · Annotator</span>
        </div>
        <form onSubmit={submit} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 14, padding: "26px 24px", boxShadow: "0 1px 3px rgba(20,30,50,.05)" }}>
          <h1 style={{ fontSize: 19, margin: "0 0 4px", color: C.ink }}>Sign in</h1>
          <p style={{ margin: "0 0 18px", color: C.muted, fontSize: 13.5 }}>Log in to your annotator account.</p>

          <label style={{ display: "block", fontSize: 12.5, fontWeight: 600, color: C.muted, marginBottom: 6 }}>Email</label>
          <input
            type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus autoComplete="username"
            placeholder="you@deccan.ai"
            style={{ width: "100%", padding: "10px 12px", borderRadius: 9, border: `1px solid ${C.border}`, fontSize: 14, color: C.ink, outline: "none", marginBottom: 14, boxSizing: "border-box" }}
          />
          <label style={{ display: "block", fontSize: 12.5, fontWeight: 600, color: C.muted, marginBottom: 6 }}>Password</label>
          <input
            type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
            placeholder="••••••••"
            style={{ width: "100%", padding: "10px 12px", borderRadius: 9, border: `1px solid ${C.border}`, fontSize: 14, color: C.ink, outline: "none", marginBottom: 16, boxSizing: "border-box" }}
          />
          {error && <div role="alert" style={{ background: "#fdece9", color: C.danger, borderRadius: 8, padding: "8px 11px", fontSize: 13, marginBottom: 14 }}>{error}</div>}
          <button
            type="submit" disabled={busy || !email || !password}
            style={{ width: "100%", padding: "11px", borderRadius: 9, border: "none", background: busy || !email || !password ? "#a9a6ec" : C.primary, color: C.primaryInk, fontWeight: 700, fontSize: 14.5, cursor: busy || !email || !password ? "default" : "pointer" }}
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 14, padding: "16px 18px", marginTop: 14 }}>
          <div style={{ fontSize: 11.5, fontWeight: 700, letterSpacing: ".05em", textTransform: "uppercase", color: C.faint, marginBottom: 10 }}>Test accounts · click to fill email</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 7 }}>
            {TEST_ACCOUNTS.map((a) => (
              <button
                key={a.email} type="button" onClick={() => { setEmail(a.email); setError(null); }}
                title={`${a.name} · ${a.role}`}
                style={{ border: `1px solid ${C.border}`, background: email === a.email ? "#eceafc" : C.chip, color: C.ink, borderRadius: 20, padding: "5px 11px", fontSize: 12.5, cursor: "pointer", fontWeight: 500 }}
              >
                {a.name}{a.role === "reviewer" ? " ★" : ""}
              </button>
            ))}
          </div>
          <div style={{ fontSize: 12.5, color: C.muted, marginTop: 12 }}>
            Password for all test accounts: <code style={{ background: C.chip, padding: "2px 7px", borderRadius: 6, fontSize: 12.5 }}>{DEV_PASSWORD}</code>
          </div>
        </div>
      </div>
    </div>
  );
}
