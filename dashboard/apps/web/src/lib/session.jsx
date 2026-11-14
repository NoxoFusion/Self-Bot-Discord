"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { api, ApiError } from "./api";

const SessionContext = createContext(null);

const INITIAL_STATE = {
  loading: true,
  authenticated: false,
  csrf: null,
  error: null,
};

// Vite's dev proxy reports an unreachable backend as 500/502/503/504 with a
// non-JSON body. Treat that as "offline" (status 0) so the UI can distinguish
// it from a real backend error response.
function isOfflineError(err) {
  if (!(err instanceof ApiError)) return true;
  if (err.status === 0) return true;
  if (err.status === 502 || err.status === 503 || err.status === 504)
    return true;
  return (
    err.status === 500 &&
    (err.data == null || err.data?.error === "invalid_response")
  );
}

export function SessionProvider({ children }) {
  const [state, setState] = useState(INITIAL_STATE);

  const refresh = useCallback(async () => {
    setState((prev) => ({ ...prev, loading: true }));
    try {
      const data = await api.getSession();
      setState({
        loading: false,
        authenticated: data?.authenticated !== false,
        csrf: data?.csrf ?? data?.csrf_token ?? null,
        error: null,
      });
      return data;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setState({
          loading: false,
          authenticated: false,
          csrf: null,
          error: null,
        });
      } else {
        const offline = isOfflineError(err);
        const status = offline ? 0 : err.status;
        setState({
          loading: false,
          authenticated: false,
          csrf: null,
          error: {
            status,
            message: offline
              ? "Local API offline"
              : err?.data?.error || "Could not reach the local API",
          },
        });
      }
      return null;
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const pair = useCallback(async (code) => {
    const data = await api.pair(code);
    setState({
      loading: false,
      authenticated: true,
      csrf: data?.csrf ?? data?.csrf_token ?? null,
      error: null,
    });
    return data;
  }, []);

  const logout = useCallback(async () => {
    const csrf = state.csrf;
    try {
      await api.logout(csrf);
    } finally {
      setState({
        loading: false,
        authenticated: false,
        csrf: null,
        error: null,
      });
    }
  }, [state.csrf]);

  const value = useMemo(
    () => ({ ...state, pair, logout, refresh }),
    [state, pair, logout, refresh],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

export function useSessionContext() {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    throw new Error("useSessionContext must be used inside SessionProvider");
  }
  return ctx;
}
