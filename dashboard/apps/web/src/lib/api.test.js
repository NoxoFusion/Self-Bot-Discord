import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, apiFetch, normalizeStatus } from "./api";

const API_BASE = `http://${
  typeof window !== "undefined" && window.location.hostname === "localhost"
    ? "localhost"
    : "127.0.0.1"
}:8765/api/v1`;

function okResponse(data = { ok: true }) {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(data),
  };
}

function errorResponse(status, data) {
  return {
    ok: false,
    status,
    text: async () => JSON.stringify(data),
  };
}

describe("normalizeStatus", () => {
  it("extracts the Discord avatar URL from bot status", () => {
    const status = normalizeStatus({
      bot: {
        username: "alice",
        avatar_url: "https://cdn.example/avatar.png",
      },
    });

    expect(status.bot.avatarUrl).toBe("https://cdn.example/avatar.png");
  });

  it("extracts the Discord display name from bot status", () => {
    const status = normalizeStatus({
      bot: {
        username: "alice",
        display_name: "Alice",
      },
    });

    expect(status.bot.displayName).toBe("Alice");
  });

  it("normalizes the last reload timestamp", () => {
    expect(normalizeStatus({ last_reload: 1234567890 }).lastReload).toBe(
      1234567890,
    );
    expect(normalizeStatus({}).lastReload).toBeNull();
  });
});

describe("settings endpoints", () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(okResponse());
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads settings with GET /settings", async () => {
    await api.getSettings();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE}/settings`);
    expect(options.method).toBe("GET");
    expect(options.credentials).toBe("include");
  });

  it("saves the prefix with PUT /settings/prefix and csrf", async () => {
    await api.savePrefix("!", "csrf-token");

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE}/settings/prefix`);
    expect(options.method).toBe("PUT");
    expect(options.headers["X-CSRF-Token"]).toBe("csrf-token");
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(options.body)).toEqual({ prefix: "!" });
  });

  it("requests a reload with POST /settings/reload and csrf", async () => {
    await api.requestReload("csrf-token");

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_BASE}/settings/reload`);
    expect(options.method).toBe("POST");
    expect(options.headers["X-CSRF-Token"]).toBe("csrf-token");
    expect(options.body).toBeUndefined();
  });
});

describe("ApiError message", () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the first validation detail as the error message", async () => {
    fetchMock.mockResolvedValue(
      errorResponse(400, {
        error: "validation_error",
        details: ["songs[0].id must be a 22-character Spotify track ID"],
      }),
    );

    await expect(api.getSongs()).rejects.toThrow(
      "songs[0].id must be a 22-character Spotify track ID",
    );
  });

  it("falls back to data.error when there are no details", async () => {
    fetchMock.mockResolvedValue(errorResponse(400, { error: "bot_offline" }));

    await expect(api.getSongs()).rejects.toThrow("bot_offline");
  });
});

describe("apiFetch timeout", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("aborts the request after the timeout", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn(
      (_url, options) =>
        new Promise((_resolve, reject) => {
          options.signal.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const promise = apiFetch("/status");
    // Attach a handler immediately so the rejection is never "unhandled"
    // between the timer firing and the assertions below.
    promise.catch(() => {});

    await vi.advanceTimersByTimeAsync(10000);

    await expect(promise).rejects.toMatchObject({ status: 0 });
    await expect(promise).rejects.toMatchObject({
      data: { error: "network_error" },
    });
  });
});
