import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { product } from "../test/fixtures";
import { request } from "./http";
import { productService } from "./products";

function pendingFetch() {
  const fetch = vi.fn(
    (_path: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal;
        if (!signal) throw new Error("Missing abort signal");
        if (signal.aborted) reject(signal.reason);
        else
          signal.addEventListener("abort", () => reject(signal.reason), {
            once: true,
          });
      }),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("HTTP deadlines", () => {
  it("explains an HTML gateway timeout without exposing an opaque status code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("Gateway timeout", { status: 504 })),
    );
    await expect(
      request("/api/analyze", { signal: new AbortController().signal }),
    ).rejects.toThrow("Сервер отвечает слишком долго");
    expect(vi.getTimerCount()).toBe(0);
  });

  const item = product();
  const cases = [
    {
      name: "catalog GET",
      timeout: 10_000,
      run: (signal: AbortSignal) => productService.get(item.id, signal),
    },
    {
      name: "manual upload",
      timeout: 70_000,
      run: (signal: AbortSignal) =>
        productService.create(
          {
            name: "Товар",
            description: "",
            urls: [],
            files: [new File(["photo"], "photo.jpg")],
          },
          signal,
        ),
    },
    {
      name: "selection",
      timeout: 370_000,
      run: (signal: AbortSignal) => productService.suggest(item, signal),
    },
    {
      name: "analysis",
      timeout: 370_000,
      run: (signal: AbortSignal) =>
        productService.analyze(item.id, [item.images[0].id], signal),
    },
  ];

  it.each(cases)(
    "aborts $name at its deadline with an understandable error",
    async ({ timeout, run }) => {
      const fetch = pendingFetch();
      const operation = run(new AbortController().signal);
      const failed = expect(operation).rejects.toThrow(
        "Сервер отвечает слишком долго",
      );
      await vi.advanceTimersByTimeAsync(timeout - 1);
      expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(false);
      await vi.advanceTimersByTimeAsync(1);
      await failed;
      expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it("preserves caller cancellation and clears the deadline immediately", async () => {
    pendingFetch();
    const caller = new AbortController();
    const operation = request("/api/products", { signal: caller.signal });
    const cancelled = expect(operation).rejects.toMatchObject({
      name: "AbortError",
    });
    caller.abort();
    expect(vi.getTimerCount()).toBe(0);
    await cancelled;
  });

  it("cleans up the deadline and caller subscription after success", async () => {
    let combined: AbortSignal | null | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_path: string, init?: RequestInit) => {
        combined = init?.signal;
        return new Response(JSON.stringify({ status: "ok" }));
      }),
    );
    const caller = new AbortController();
    await expect(
      request("/api/health", { signal: caller.signal }),
    ).resolves.toEqual({ status: "ok" });
    expect(vi.getTimerCount()).toBe(0);
    caller.abort();
    expect(combined?.aborted).toBe(false);
  });
});
