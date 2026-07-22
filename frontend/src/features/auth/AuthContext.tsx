import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { type Annotator, fetchMe, login as apiLogin, logout as apiLogout, type LoginResult } from "./authApi";

interface AuthState {
  annotator: Annotator | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<LoginResult>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthCtx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [annotator, setAnnotator] = useState<Annotator | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    fetchMe().then((a) => {
      if (!alive) return;
      setAnnotator(a);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const r = await apiLogin(email, password);
    if (r.ok) setAnnotator(r.annotator);
    return r;
  }, []);

  const signOut = useCallback(async () => {
    await apiLogout();
    setAnnotator(null);
  }, []);

  const refresh = useCallback(async () => {
    setAnnotator(await fetchMe());
  }, []);

  return <AuthCtx.Provider value={{ annotator, loading, signIn, signOut, refresh }}>{children}</AuthCtx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
