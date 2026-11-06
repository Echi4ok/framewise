import { afterEach, describe, expect, it, vi } from "vitest";
import { effectScope, nextTick, ref } from "vue";
import { product } from "../test/fixtures";
import type { Analysis, Product } from "../types";
import { useWorkflowNavigation } from "./useWorkflowNavigation";

afterEach(() => document.body.replaceChildren());

describe("workflow navigation", () => {
  it("respects reduced motion and focuses the new step", async () => {
    const target = document.createElement("section");
    target.id = "photo-selection";
    target.tabIndex = -1;
    document.body.append(target);
    const scroll = vi
      .spyOn(target, "scrollIntoView")
      .mockImplementation(() => undefined);
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    vi.spyOn(query, "matches", "get").mockReturnValue(true);
    vi.spyOn(window, "matchMedia").mockReturnValue(query);
    const current = ref<Product | null>(null);
    const result = ref<Analysis | null>(null);
    const scope = effectScope();
    scope.run(() => useWorkflowNavigation(current, result, () => ""));
    current.value = product();
    await nextTick();
    await nextTick();
    expect(scroll).toHaveBeenCalledWith({
      behavior: "instant",
      block: "start",
    });
    expect(document.activeElement).toBe(target);
    scope.stop();
  });

  it("does not scroll a later screen after its scope is disposed", async () => {
    const target = document.createElement("section");
    target.id = "photo-selection";
    document.body.append(target);
    const scroll = vi
      .spyOn(target, "scrollIntoView")
      .mockImplementation(() => undefined);
    const current = ref<Product | null>(null);
    const scope = effectScope();
    scope.run(() => useWorkflowNavigation(current, ref(null), () => ""));
    current.value = product();
    await nextTick();
    scope.stop();
    await nextTick();
    expect(scroll).not.toHaveBeenCalled();
  });
});
