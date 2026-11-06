import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, type EffectScope } from "vue";
import { EXAMPLES } from "../constants";
import type { ProductService } from "../services/products";
import { analysis, deferred, product } from "../test/fixtures";
import type { Analysis, Product, Suggestion } from "../types";
import { useProductWorkflow } from "./useProductWorkflow";

const scopes: EffectScope[] = [];
function setup(overrides: Partial<ProductService> = {}) {
  const api: ProductService = {
    list: vi.fn(async () => [{ id: "test", name: "Товар" }]),
    get: vi.fn(async (id: string) => product(id)),
    create: vi.fn(async () => product("manual")),
    suggest: vi.fn(async (item: Product) => ({
      selected_image_ids: [item.images[0].id],
      reason: "Ракурс",
    })),
    analyze: vi.fn(async () => analysis(product())),
    ...overrides,
  };
  const scope = effectScope();
  scopes.push(scope);
  const workflow = scope.run(() => useProductWorkflow(api));
  if (!workflow) throw new Error("Missing active scope");
  return { api, workflow, dispose: () => scope.stop() };
}
beforeEach(() => {
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
});
afterEach(() => {
  scopes.splice(0).forEach((scope) => scope.stop());
  vi.useRealTimers();
});

describe("product workflow", () => {
  it("cancels analysis immediately and ignores its late response during a retry", async () => {
    vi.useFakeTimers();
    const first = deferred<Analysis>();
    const second = deferred<Analysis>();
    let signal: AbortSignal | undefined;
    const run = vi.fn(
      (_id: string, _photos: string[], requestSignal: AbortSignal) => {
        signal = requestSignal;
        return first.promise;
      },
    );
    run.mockImplementationOnce((_id, _photos, requestSignal) => {
      signal = requestSignal;
      return first.promise;
    });
    run.mockImplementationOnce(() => second.promise);
    const { workflow } = setup({ analyze: run });
    await workflow.openExample("test-product");
    const selected = [...workflow.selected.value];
    const cancelled = workflow.analyze();
    vi.advanceTimersByTime(2500);
    workflow.cancel();
    expect(signal?.aborted).toBe(true);
    expect(workflow.busy.value).toBe(false);
    expect(workflow.status.notice).toContain("Ожидание отменено");
    expect(workflow.selected.value).toEqual(selected);
    expect(workflow.product.value?.id).toBe("test-product");
    expect(vi.getTimerCount()).toBe(0);
    const retry = workflow.analyze();
    first.resolve(analysis(product()));
    await cancelled;
    expect(workflow.analysis.value).toBeNull();
    expect(workflow.busy.value).toBe(true);
    second.resolve(analysis(product()));
    await retry;
    expect(workflow.analysis.value?.features).toHaveLength(3);
    expect(workflow.busy.value).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not replace an edited selection with a cancelled suggestion", async () => {
    const pending = deferred<Suggestion>();
    const { workflow } = setup({ suggest: vi.fn(() => pending.promise) });
    await workflow.openExample("test-product");
    const request = workflow.suggest();
    workflow.cancel();
    workflow.togglePhoto("test-product-1");
    const edited = [...workflow.selected.value];
    pending.resolve({
      selected_image_ids: ["test-product-5"],
      reason: "Late suggestion",
    });
    await request;
    expect(workflow.selected.value).toEqual(edited);
    expect(workflow.busy.value).toBe(false);
  });

  it("retains available examples when one card fails", async () => {
    const { workflow } = setup({
      get: vi.fn(async (id) => {
        if (id === EXAMPLES[1].id) throw new Error("404");
        return product(id);
      }),
    });
    await workflow.loadExamples();
    expect(workflow.examples.value.map((item) => item.id)).toEqual([
      EXAMPLES[0].id,
      EXAMPLES[2].id,
    ]);
    expect(workflow.status.notice).toContain("Часть примеров");
    expect(workflow.examplesIncomplete.value).toBe(true);
  });

  it("does not overlap requests or apply responses after disposal", async () => {
    const pending = deferred<Product>();
    let signal: AbortSignal | undefined;
    const { workflow, api, dispose } = setup({
      get: vi.fn((_id, requestSignal) => {
        signal = requestSignal;
        return pending.promise;
      }),
    });
    const loading = workflow.openExample("  selected  ");
    await workflow.openExample("other");
    expect(api.get).toHaveBeenCalledTimes(1);
    expect(api.get).toHaveBeenCalledWith("selected", expect.any(AbortSignal));
    dispose();
    expect(signal?.aborted).toBe(true);
    pending.resolve(product("selected"));
    await loading;
    expect(workflow.product.value).toBeNull();
  });

  it("clears stale results before a failed rerun and permits retry", async () => {
    const run = vi.fn(async () => analysis(product()));
    const { workflow } = setup({ analyze: run });
    await workflow.openExample("test-product");
    await workflow.analyze();
    expect(workflow.analysis.value?.features).toHaveLength(3);
    run.mockRejectedValueOnce(new Error("Ошибка модели"));
    const failed = workflow.analyze();
    expect(workflow.analysis.value).toBeNull();
    await failed;
    expect(workflow.status.error).toBe("Ошибка модели");
    expect(workflow.busy.value).toBe(false);
    await workflow.analyze();
    expect(workflow.analysis.value?.features).toHaveLength(3);
    expect(workflow.status.error).toBe("");
  });

  it("sends the edited selection after model suggestion", async () => {
    const { workflow, api } = setup();
    await workflow.openExample("test-product");
    workflow.togglePhoto("test-product-5");
    expect(workflow.selected.value).toHaveLength(4);
    expect(workflow.status.notice).toContain("четырёх");
    await workflow.suggest();
    workflow.togglePhoto("test-product-2");
    await workflow.analyze();
    expect(api.analyze).toHaveBeenCalledWith(
      "test-product",
      ["test-product-1", "test-product-2"],
      expect.any(AbortSignal),
    );
  });

  it("resets the full draft and current product", async () => {
    const { workflow, api } = setup();
    workflow.draft.name = "  Чемодан  ";
    workflow.draft.description = " Описание ";
    workflow.draft.urls = "https://images.test/photo.jpg";
    workflow.addFiles([new File(["photo"], "photo.jpg")]);
    await workflow.prepareProduct();
    expect(api.create).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Чемодан",
        description: "Описание",
        urls: ["https://images.test/photo.jpg"],
      }),
      expect.any(AbortSignal),
    );
    workflow.catalogId.value = "old";
    workflow.startOver();
    expect(workflow.product.value).toBeNull();
    expect(workflow.analysis.value).toBeNull();
    expect(workflow.selected.value).toEqual([]);
    expect(workflow.catalogId.value).toBe("");
    expect(workflow.draft).toEqual({
      name: "",
      description: "",
      urls: "",
      uploads: [],
    });
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
  });

  it("stops the elapsed timer after a failed request", async () => {
    vi.useFakeTimers();
    const pending = deferred<Product>();
    const { workflow } = setup({ get: vi.fn(() => pending.promise) });
    const request = workflow.openExample("slow");
    vi.advanceTimersByTime(2500);
    expect(workflow.status.seconds).toBe(2);
    pending.reject(new Error("Сервер недоступен"));
    await request;
    expect(workflow.status.loading).toBe("");
    expect(vi.getTimerCount()).toBe(0);
  });
});
