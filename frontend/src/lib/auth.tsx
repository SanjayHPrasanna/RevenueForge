import { useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken, TOKEN_KEY } from "./api";

export type User = {
  id: string;
  name: string;
  email: string;
  role: string;
  tenant: { id: string; name: string; slug: string; onboarding: Record<string, boolean> };
};

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (data: Record<string, string>) => Promise<User>;
  google: (credential: string, company?: Record<string, string>) => Promise<{ user?: User; needs_company?: boolean; email?: string; name?: string }>;
  microsoft: (credential: string, nonce: string, company?: Record<string, string>) => Promise<{ user?: User; needs_company?: boolean; email?: string; name?: string }>;
  logout: () => void;
  refresh: () => Promise<void>;
};

const Ctx = createContext<AuthState>(null as any);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await api.get<User>("/auth/me"));
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  };

  const qc = useQueryClient();
  useEffect(() => {
    refresh();
    // Signing in or out in another tab changes the shared token: reload so this tab never acts as the wrong company.
    const onStorage = (e: StorageEvent) => {
      if (e.key === null || e.key === TOKEN_KEY) window.location.assign(getToken() ? "/app" : "/login");
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const login = async (email: string, password: string) => {
    const r = await api.post<{ token: string; user: User }>("/auth/login", { email, password });
    qc.clear();
    setToken(r.token);
    setUser(r.user);
    return r.user;
  };
  const register = async (data: Record<string, string>) => {
    const r = await api.post<{ token: string; user: User }>("/auth/register", data);
    qc.clear();
    setToken(r.token);
    setUser(r.user);
    return r.user;
  };
  const google = async (credential: string, company: Record<string, string> = {}) => {
    const r = await api.post<any>("/auth/google", { credential, ...company });
    if (r.needs_company) return r;
    qc.clear();
    setToken(r.token);
    setUser(r.user);
    return { user: r.user };
  };
  const microsoft = async (credential: string, nonce: string, company: Record<string, string> = {}) => {
    const r = await api.post<any>("/auth/microsoft", { credential, nonce, ...company });
    if (r.needs_company) return r;
    qc.clear();
    setToken(r.token);
    setUser(r.user);
    return { user: r.user };
  };
  const logout = () => {
    qc.clear();
    setToken(null);
    setUser(null);
    location.href = "/";
  };
  return <Ctx.Provider value={{ user, loading, login, register, google, microsoft, logout, refresh }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
