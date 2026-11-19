import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api, getOrganization, setAccessToken, setOrganization } from "@/lib/api";
import type { LoginResponse, MeResponse } from "@/types/api";

type Status = "loading" | "authenticated" | "anonymous";

interface AuthValue {
  status: Status;
  session: MeResponse | null;
  permissions: Set<string>;
  can: (permission: string) => boolean;
  isDemo: boolean;
  login: (email: string, password: string, organizationSlug?: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  switchOrganization: (organizationId: string) => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [session, setSession] = useState<MeResponse | null>(null);

  const loadSession = useCallback(async () => {
    const me = await api.get<MeResponse>("/auth/me");
    setSession(me);
    setStatus("authenticated");
    if (!getOrganization()) setOrganization(me.organization.id);
    return me;
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!localStorage.getItem("resolve-session")) {
      setStatus("anonymous");
      return;
    }
    (async () => {
      try {
        const refreshed = await api.refresh();
        if (!refreshed) {
          localStorage.removeItem("resolve-session");
          if (!cancelled) setStatus("anonymous");
          return;
        }
        if (!cancelled) await loadSession();
      } catch {
        localStorage.removeItem("resolve-session");
        if (!cancelled) setStatus("anonymous");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadSession]);

  const login = useCallback(
    async (email: string, password: string, organizationSlug?: string) => {
      const response = await api.post<LoginResponse>(
        "/auth/login",
        { email, password, organization_slug: organizationSlug || undefined },
        { skipAuth: true },
      );
      setAccessToken(response.access_token);
      setOrganization(response.organization.id);
      localStorage.setItem("resolve-session", "1");
      await loadSession();
    },
    [loadSession],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      // Local session is cleared regardless of the server response.
    }
    setAccessToken(null);
    setSession(null);
    localStorage.removeItem("resolve-session");
    setStatus("anonymous");
  }, []);

  const refresh = useCallback(async () => {
    await loadSession();
  }, [loadSession]);

  const switchOrganization = useCallback(
    async (organizationId: string) => {
      setOrganization(organizationId);
      const me = await api.get<MeResponse>("/auth/me");
      setSession(me);
    },
    [],
  );

  const permissions = useMemo(() => new Set(session?.permissions ?? []), [session]);
  const value = useMemo<AuthValue>(
    () => ({
      status,
      session,
      permissions,
      can: (permission: string) => permissions.has(permission),
      isDemo: Boolean(session?.demo_mode || session?.organization.is_demo),
      login,
      logout,
      refresh,
      switchOrganization,
    }),
    [status, session, permissions, login, logout, refresh, switchOrganization],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
