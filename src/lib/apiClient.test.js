import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiGet, apiRequest, apiUpload, setAuthToken } from "./apiClient";

/**
 * These tests pin the error contract the screens already rely on:
 *   * an HTTP error carries `.status` and the backend's `detail` message;
 *   * a transport failure is translated rather than leaking
 *     `TypeError: Failed to fetch` to a toast;
 *   * a hung request is aborted instead of spinning forever;
 *   * concurrent identical GETs share one network call.
 */
const fetchMock = vi.fn();

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

beforeEach(() => {
  fetchMock.mockReset();
  global.fetch = fetchMock;
  setAuthToken(null);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("apiRequest", () => {
  it("resolves the parsed body on success", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    await expect(apiRequest("/api/health")).resolves.toEqual({ ok: true });
  });

  it("rejects with the backend detail and status on an HTTP error", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Not allowed" }, 403));
    const err = await apiRequest("/api/farms").catch((e) => e);
    expect(err.status).toBe(403);
    expect(err.message).toBe("Not allowed");
  });

  it("falls back to a readable message when the error body is not JSON", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error("not json");
      },
    });
    const err = await apiRequest("/api/farms").catch((e) => e);
    expect(err.status).toBe(502);
    expect(err.message).toMatch(/502/);
  });

  it("translates a transport failure into an actionable message", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const err = await apiRequest("/api/farms").catch((e) => e);
    expect(err.isNetworkError).toBe(true);
    expect(err.status).toBe(0);
    // The browser's opaque message must not reach the user.
    expect(err.message).not.toMatch(/Failed to fetch/);
    expect(err.message).toMatch(/Cannot reach the FarmIQ server/i);
  });

  it("aborts a request that outlives its deadline and reports a timeout", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          init.signal.addEventListener("abort", () => {
            const e = new Error("aborted");
            e.name = "AbortError";
            reject(e);
          });
        }),
    );

    const pending = apiRequest("/api/chat", { timeoutMs: 1000 });
    const assertion = expect(pending).rejects.toMatchObject({
      isTimeout: true,
      status: 0,
    });
    await vi.advanceTimersByTimeAsync(1001);
    await assertion;
  });

  it("passes an abort signal to fetch so the deadline is real", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    await apiRequest("/api/health");
    expect(fetchMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
  });

  it("attaches the bearer token when one is set", async () => {
    setAuthToken("tok-123");
    fetchMock.mockResolvedValue(jsonResponse({}));
    await apiRequest("/api/farms");
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer tok-123");
  });

  it("serialises a JSON body and sets the content type", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    await apiRequest("/api/farms", { method: "POST", body: { name: "North field" } });
    const init = fetchMock.mock.calls[0][1];
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual({ name: "North field" });
  });
});

describe("apiUpload", () => {
  it("does not set Content-Type so the browser can add the multipart boundary", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    await apiUpload("/api/voice/transcribe", new FormData());
    expect(fetchMock.mock.calls[0][1].headers["Content-Type"]).toBeUndefined();
  });
});

describe("apiGet de-duplication", () => {
  it("shares one network call between concurrent identical GETs", async () => {
    let resolveFetch;
    fetchMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = () => resolve(jsonResponse({ items: [] }));
      }),
    );

    const a = apiGet("/api/farms");
    const b = apiGet("/api/farms");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    resolveFetch();
    await expect(a).resolves.toEqual({ items: [] });
    await expect(b).resolves.toEqual({ items: [] });
  });

  it("does not cache — a later call hits the network again", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [] }));
    await apiGet("/api/farms");
    await apiGet("/api/farms");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("frees the in-flight entry when the shared request fails", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("offline"));
    await apiGet("/api/farms").catch(() => {});
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [] }));
    await expect(apiGet("/api/farms")).resolves.toEqual({ items: [] });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("never shares a call that passes explicit options", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    const a = apiGet("/api/x", { headers: { "X-Trace": "1" } });
    const b = apiGet("/api/x", { headers: { "X-Trace": "2" } });
    await Promise.all([a, b]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
