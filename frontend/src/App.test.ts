import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import App from "./App.vue";
import { EXAMPLES } from "./constants";
import { analysis, get, mountComponent, product } from "./test/fixtures";

beforeEach(() => {
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:upload");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.unstubAllGlobals();
  document.body.replaceChildren();
});

describe("complete UI workflow with a fake API", () => {
  it("uploads files, renders linked results and returns to an empty draft without Vue warnings", async () => {
    const warn = vi.spyOn(console, "warn");
    const item = product("manual", 2);
    const create = vi.fn();
    const fetch = vi.fn(async (path: string, init?: RequestInit) => {
      let value: unknown;
      if (path === "/api/products")
        value = EXAMPLES.map((entry) => ({ id: entry.id, name: entry.title }));
      else if (path === "/api/products/manual") {
        create(init?.body);
        value = item;
      } else if (path === "/api/analyze") value = analysis(item);
      else value = product(path.slice("/api/products/".length));
      return new Response(JSON.stringify(value), { status: 200 });
    });
    vi.stubGlobal("fetch", fetch);
    const mounted = mountComponent(App, {});
    try {
      await nextTick();
      await vi.waitFor(() =>
        expect(get(mounted.element, ".dropzone").hasAttribute("disabled")).toBe(
          false,
        ),
      );
      const name = get(mounted.element, "#name");
      if (!(name instanceof HTMLInputElement))
        throw new Error("Missing name input");
      name.value = "Мой чемодан";
      name.dispatchEvent(new Event("input", { bubbles: true }));
      const file = new File(["photo"], "photo.jpg", { type: "image/jpeg" });
      const input = get(mounted.element, 'input[type="file"]');
      Object.defineProperty(input, "files", {
        value: [file],
        configurable: true,
      });
      input.dispatchEvent(new Event("change", { bubbles: true }));
      await nextTick();
      expect(mounted.element.querySelectorAll(".upload-preview")).toHaveLength(
        1,
      );
      get(mounted.element, "#upload-form form").dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
      );
      await vi.waitFor(() =>
        expect(mounted.element.querySelectorAll(".photo-card")).toHaveLength(2),
      );
      expect(create).toHaveBeenCalledWith(expect.any(FormData));
      get(mounted.element, ".actions .primary").dispatchEvent(
        new MouseEvent("click"),
      );
      await vi.waitFor(() =>
        expect(mounted.element.querySelectorAll(".feature")).toHaveLength(3),
      );
      get(mounted.element, ".product-heading .text-button").dispatchEvent(
        new MouseEvent("click"),
      );
      await vi.waitFor(() =>
        expect(mounted.element.querySelector("#upload-form")).not.toBeNull(),
      );
      const resetName = get(mounted.element, "#name");
      if (!(resetName instanceof HTMLInputElement))
        throw new Error("Missing reset input");
      expect(resetName.value).toBe("");
      expect(mounted.element.querySelectorAll(".upload-preview")).toHaveLength(
        0,
      );
      expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:upload");
      expect(warn).not.toHaveBeenCalled();
    } finally {
      mounted.unmount();
    }
  });
});
