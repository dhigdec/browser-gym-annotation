/** Auth API — cookie-based sessions. Every call sends the HttpOnly session cookie
 *  via credentials:"include"; the server derives identity from it. */

export interface AnnotatorStats {
  sessions: number;
  submitted: number;
  golden: number;
  breaker: number;
  flagged: number;
}

export interface Annotator {
  id: string;
  email: string;
  role: string;
  displayName: string;
  avatarHue: number;
  lastLoginAt: string | null;
  stats?: AnnotatorStats;
}

export type LoginResult = { ok: true; annotator: Annotator } | { ok: false; error: string };

export async function fetchMe(): Promise<Annotator | null> {
  try {
    const r = await fetch("/api/auth/me", { credentials: "include" });
    if (!r.ok) return null;
    return (await r.json()) as Annotator;
  } catch {
    return null;
  }
}

export async function login(email: string, password: string): Promise<LoginResult> {
  try {
    const r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email, password }),
    });
    if (r.ok) return { ok: true, annotator: (await r.json()) as Annotator };
    const d = (await r.json().catch(() => ({}))) as { detail?: string };
    return { ok: false, error: d.detail || `Login failed (${r.status})` };
  } catch {
    return { ok: false, error: "Cannot reach the server." };
  }
}

export async function logout(): Promise<void> {
  try {
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
  } catch {
    /* ignore */
  }
}
