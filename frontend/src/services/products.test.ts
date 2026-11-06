import { afterEach, describe, expect, it, vi } from "vitest";
import { analysis, product } from "../test/fixtures";
import { request } from "./http";
import { productService } from "./products";
afterEach(() => vi.unstubAllGlobals());
const signal = () => new AbortController().signal;
function reply(data: unknown, status = 200) {
  const fetch = vi.fn(
    async () => new Response(JSON.stringify(data), { status }),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("API boundary", () => {
  it.each(["", "   ", { message: "" }, { message: "   " }])(
    "falls back to a visible error when server detail is empty: %j",
    async (detail) => {
      reply({ detail }, 422);
      await expect(
        request("/api/products/manual", { signal: signal() }),
      ).rejects.toThrow("422");
    },
  );

  it("rejects malformed products instead of casting them into UI state", async () => {
    reply({ id: "bad", images: [null] });
    await expect(productService.get("bad", signal())).rejects.toThrow(
      "некорректные данные",
    );
  });

  it("rejects foreign image IDs and invalid rectangles", async () => {
    const item = product();
    const result = analysis(item);
    const ids = item.images.map((photo) => photo.id);
    result.features[0].image_id = "foreign";
    reply(result);
    await expect(
      productService.analyze(item.id, ids, signal()),
    ).rejects.toThrow("некорректные данные");
    result.features[0].image_id = ids[0];
    result.features[0].bbox = [200, 10, 20, 40];
    reply(result);
    await expect(
      productService.analyze(item.id, ids, signal()),
    ).rejects.toThrow("некорректные данные");
  });

  it("preserves payloads and exposes structured validation messages", async () => {
    const item = product();
    const fetch = reply(analysis(item));
    const ids = item.images.slice(0, 3).map((photo) => photo.id);
    await productService.analyze(item.id, ids, signal());
    expect(fetch).toHaveBeenCalledWith(
      "/api/analyze",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ product_id: item.id, image_ids: ids }),
      }),
    );
    reply({ detail: [{ loc: ["body", "description"], msg: "Too long" }] }, 422);
    await expect(
      request("/api/products/manual", { signal: signal() }),
    ).rejects.toThrow("description: Too long");
  });

  it("handles malformed error details and preserves cancellation", async () => {
    reply({ detail: [null, 42, {}] }, 502);
    await expect(request("/api/analyze", { signal: signal() })).rejects.toThrow(
      "502",
    );
    const controller = new AbortController();
    const abort = new DOMException("Aborted", "AbortError");
    controller.abort();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abort));
    await expect(
      request("/api/analyze", { signal: controller.signal }),
    ).rejects.toBe(abort);
  });
});
