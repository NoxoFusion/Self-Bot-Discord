import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { __resetLiveStateForTests, useLiveState } from "./ws";

class FakeWebSocket {
  static instances = [];

  static reset() {
    FakeWebSocket.instances = [];
  }

  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.readyState = 3;
  }

  emitOpen() {
    this.readyState = 1;
    this.onopen?.({});
  }

  emitMessage(payload) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  emitError() {
    this.onerror?.({});
  }

  emitClose() {
    this.readyState = 3;
    this.onclose?.({});
  }
}

const expectedHost =
  window.location.hostname === "localhost" ? "localhost" : "127.0.0.1";

describe("useLiveState", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.reset();
    __resetLiveStateForTests();
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    __resetLiveStateForTests();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("connects, receives a state message, and reconnects after close", () => {
    const { result, unmount } = renderHook(() => useLiveState());

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).toBe(
      `ws://${expectedHost}:8765/api/v1/ws`,
    );

    act(() => {
      FakeWebSocket.instances[0].emitOpen();
    });
    expect(result.current.connected).toBe(true);

    const state = {
      type: "state",
      bot: { state: "online", username: "alice" },
      voice: { updated_at: 123, tokens: [{ index: 0, channels: ["456"] }] },
      tokens: 1,
    };
    act(() => {
      FakeWebSocket.instances[0].emitMessage(state);
    });
    expect(result.current.liveState).toEqual(state);

    act(() => {
      FakeWebSocket.instances[0].emitClose();
    });
    expect(result.current.connected).toBe(false);
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(2999);
    });
    expect(FakeWebSocket.instances).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);

    unmount();
  });

  it("stops reconnecting after unmount", () => {
    const { unmount } = renderHook(() => useLiveState());

    act(() => {
      FakeWebSocket.instances[0].emitClose();
    });
    unmount();

    act(() => {
      vi.advanceTimersByTime(10000);
    });

    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("reconnects after a socket error", () => {
    const { unmount } = renderHook(() => useLiveState());

    act(() => {
      FakeWebSocket.instances[0].emitError();
    });

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(FakeWebSocket.instances).toHaveLength(2);

    unmount();
  });

  it("shares one socket between two components", () => {
    const first = renderHook(() => useLiveState());
    const second = renderHook(() => useLiveState());

    expect(FakeWebSocket.instances).toHaveLength(1);

    const payload = {
      type: "state",
      bot: { state: "online", username: "alice" },
      voice: { updated_at: 123, tokens: [] },
      tokens: 0,
    };
    act(() => {
      FakeWebSocket.instances[0].emitOpen();
      FakeWebSocket.instances[0].emitMessage(payload);
    });

    expect(first.result.current.connected).toBe(true);
    expect(second.result.current.connected).toBe(true);
    expect(first.result.current.liveState).toEqual(payload);
    expect(second.result.current.liveState).toEqual(payload);

    first.unmount();
    expect(FakeWebSocket.instances[0].readyState).not.toBe(3);

    second.unmount();
    expect(FakeWebSocket.instances[0].readyState).toBe(3);
  });
});
