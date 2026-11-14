"use client";
import { useEffect, useReducer } from "react";

// Same host resolution as api.js: the backend binds loopback only.
const WS_HOST =
  typeof window !== "undefined" && window.location.hostname === "localhost"
    ? "localhost"
    : "127.0.0.1";
const WS_URL = `ws://${WS_HOST}:8765/api/v1/ws`;

const RECONNECT_DELAY_MS = 3000;

// One shared connection for every `useLiveState()` caller.  The manager is
// created lazily in the browser and torn down when the last subscriber leaves.
let manager = null;

function createManager() {
  let socket = null;
  let reconnectTimer = null;
  let disposed = false;
  const subscribers = new Set();
  const state = { connected: false, liveState: null };

  function notify() {
    for (const callback of subscribers) callback();
  }

  function scheduleReconnect() {
    if (disposed || reconnectTimer !== null) return;
    if (subscribers.size === 0) return;

    // Drop the old socket without letting its late close handler schedule a
    // second reconnect (or close the replacement).
    const stale = socket;
    socket = null;
    if (stale) {
      try {
        stale.close();
      } catch {
        /* already closed */
      }
    }

    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, RECONNECT_DELAY_MS);
  }

  function connect() {
    if (disposed) return;

    let next;
    try {
      next = new window.WebSocket(WS_URL);
    } catch {
      scheduleReconnect();
      return;
    }
    socket = next;

    next.onopen = () => {
      if (disposed || socket !== next) return;
      state.connected = true;
      notify();
    };

    next.onmessage = (event) => {
      if (disposed || socket !== next) return;
      try {
        const parsed = JSON.parse(event.data);
        if (parsed && typeof parsed === "object") {
          state.liveState = parsed;
          notify();
        }
      } catch {
        /* ignore malformed frames */
      }
    };

    next.onerror = () => {
      if (disposed || socket !== next) return;
      state.connected = false;
      notify();
      scheduleReconnect();
    };

    next.onclose = () => {
      if (disposed || socket !== next) return;
      state.connected = false;
      socket = null;
      notify();
      scheduleReconnect();
    };
  }

  function dispose() {
    if (disposed) return;
    disposed = true;

    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      try {
        socket.close();
      } catch {
        /* already closed */
      }
      socket = null;
    }

    state.connected = false;
    notify();
  }

  const instance = {
    subscribe(callback) {
      subscribers.add(callback);
      if (socket === null && reconnectTimer === null && !disposed) connect();
      return () => {
        subscribers.delete(callback);
        if (subscribers.size === 0) {
          dispose();
          // Ref-count hit zero: the next subscriber gets a fresh manager.
          if (manager === instance) manager = null;
        }
      };
    },
    getState() {
      return state;
    },
    dispose,
  };

  return instance;
}

function getManager() {
  if (!manager) manager = createManager();
  return manager;
}

/**
 * Subscribe to the dashboard's live state WebSocket.
 *
 * Returns `{ connected, liveState }`.  The hook is SSR-safe: it does nothing
 * until it runs in the browser.  All callers share one connection; it is
 * closed when the last subscriber unmounts.  On error or close it retries
 * every 3s while subscribers remain.  REST polling remains the fallback
 * whenever `connected` is false.
 */
export function useLiveState() {
  const activeManager = typeof window !== "undefined" ? getManager() : null;
  const [, forceUpdate] = useReducer((count) => count + 1, 0);

  useEffect(() => {
    if (!activeManager) return undefined;
    return activeManager.subscribe(forceUpdate);
  }, [activeManager, forceUpdate]);

  if (!activeManager) return { connected: false, liveState: null };
  return activeManager.getState();
}

/** Test-only: dispose the shared manager so the next subscribe starts clean. */
export function __resetLiveStateForTests() {
  if (manager) {
    manager.dispose();
    manager = null;
  }
}
