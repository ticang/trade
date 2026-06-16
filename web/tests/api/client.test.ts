import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiGet } from "@/lib/api/client";

describe("apiGet", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("fetches JSON from the configured API base URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_TRADE_API_BASE_URL", "http://localhost:8000");
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{ symbol: "600519" }],
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await apiGet<{ symbol: string }[]>("/api/markets");

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/markets", {
      signal: expect.any(AbortSignal),
    });
    expect(result).toEqual([{ symbol: "600519" }]);
  });

  it("raises ApiError for non-2xx responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        json: async () => ({ detail: "symbol outside current main-board scope" }),
      }),
    );

    await expect(apiGet("/api/kline/688981")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      message: "symbol outside current main-board scope",
    });
  });

  it("normalizes network failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("failed")));

    await expect(apiGet("/api/markets")).rejects.toBeInstanceOf(ApiError);
    await expect(apiGet("/api/markets")).rejects.toMatchObject({
      status: 0,
      message: "Network request failed",
    });
  });

  it("aborts requests after the timeout", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const request = expect(apiGet("/api/markets", 50)).rejects.toMatchObject({
      status: 0,
      message: "Network request failed",
    });
    await vi.advanceTimersByTimeAsync(50);

    await request;
  });
});
