import { nextTick } from "vue";
import { describe, expect, it } from "vitest";
import { analysis, get, mountComponent, product } from "../test/fixtures";
import AnalysisResults from "./AnalysisResults.vue";

async function loadImage(element: Element, source?: string) {
  const image = get(element, ".image-stage > img");
  const src = source ?? image.getAttribute("src");
  if (!src) throw new Error("Missing image source");
  Object.defineProperty(image, "currentSrc", {
    value: new URL(src, window.location.href).href,
    configurable: true,
  });
  image.dispatchEvent(new Event("load"));
  await nextTick();
}

describe("linked result controls", () => {
  it("normalizes names and generated descriptions only in their presentation", async () => {
    const item = product();
    item.name = "Товар — пример";
    const result = analysis(item);
    result.features[0].description = "Верх — серый";
    const mounted = mountComponent(AnalysisResults, {
      product: item,
      analysis: result,
    });
    try {
      expect(get(mounted.element, ".result-product-name").textContent).toBe(
        "Товар - пример",
      );
      expect(get(mounted.element, ".feature").textContent).toContain(
        "Верх - серый",
      );
      await loadImage(mounted.element);
      expect(get(mounted.element, ".bbox").getAttribute("aria-label")).toBe(
        "Верх - серый",
      );
      expect(result.features[0].description).toBe("Верх — серый");
    } finally {
      mounted.unmount();
    }
  });

  it("switches image and matching feature from descriptions, thumbnails and keyboard", async () => {
    const item = product();
    const mounted = mountComponent(AnalysisResults, {
      product: item,
      analysis: analysis(item),
    });
    get(mounted.element, ".feature:nth-child(3)").dispatchEvent(
      new MouseEvent("click"),
    );
    await nextTick();
    expect(get(mounted.element, ".image-stage > img").getAttribute("src")).toBe(
      item.images[2].url,
    );
    get(mounted.element, ".result-thumbs button:nth-child(2)").dispatchEvent(
      new MouseEvent("click"),
    );
    await nextTick();
    expect(
      get(mounted.element, ".feature:nth-child(2)").classList.contains(
        "active",
      ),
    ).toBe(true);
    expect(
      get(mounted.element, ".feature:nth-child(3)").classList.contains(
        "active",
      ),
    ).toBe(false);
    await loadImage(mounted.element);
    get(mounted.element, ".bbox").dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter" }),
    );
    await nextTick();
    expect(
      get(mounted.element, ".feature:nth-child(2)").classList.contains(
        "active",
      ),
    ).toBe(true);
    expect(
      get(mounted.element, ".image-stage > svg").getAttribute("viewBox"),
    ).toBe("0 0 1000 1000");
    mounted.unmount();
  });

  it("waits for the current image and ignores load events from the old source", async () => {
    const item = product();
    const mounted = mountComponent(AnalysisResults, {
      product: item,
      analysis: analysis(item),
    });
    await loadImage(mounted.element);
    expect(mounted.element.querySelector(".image-stage > svg")).not.toBeNull();
    get(mounted.element, ".result-thumbs button:nth-child(2)").dispatchEvent(
      new MouseEvent("click"),
    );
    await nextTick();
    expect(mounted.element.querySelector(".image-stage > svg")).toBeNull();
    await loadImage(mounted.element, item.images[0].url);
    expect(mounted.element.querySelector(".image-stage > svg")).toBeNull();
    await loadImage(mounted.element);
    expect(mounted.element.querySelector(".image-stage > svg")).not.toBeNull();
    mounted.unmount();
  });

  it("shows original photo numbers and resets for a new result", async () => {
    const item = product();
    const result = analysis(item);
    result.features[0].image_id = item.images[4].id;
    const mounted = mountComponent(AnalysisResults, {
      product: item,
      analysis: result,
    });
    expect(mounted.element.textContent).toContain("Фото 5");
    await mounted.setProps({ analysis: analysis(item) });
    expect(get(mounted.element, ".image-stage > img").getAttribute("src")).toBe(
      item.images[0].url,
    );
    expect(
      get(mounted.element, ".feature:nth-child(1)").classList.contains(
        "active",
      ),
    ).toBe(true);
    mounted.unmount();
  });

  it("ignores stale image errors and clears an active error after successful load", async () => {
    const item = product();
    const mounted = mountComponent(AnalysisResults, {
      product: item,
      analysis: analysis(item),
    });
    await loadImage(mounted.element);
    const oldImage = get(mounted.element, ".image-stage > img");
    get(mounted.element, ".result-thumbs button:nth-child(2)").dispatchEvent(
      new MouseEvent("click"),
    );
    await nextTick();
    const currentImage = get(mounted.element, ".image-stage > img");
    expect(currentImage).not.toBe(oldImage);
    oldImage.dispatchEvent(new Event("error"));
    await nextTick();
    expect(mounted.element.querySelector(".result-media-error")).toBeNull();
    await loadImage(mounted.element, item.images[0].url);
    currentImage.dispatchEvent(new Event("error"));
    await nextTick();
    expect(mounted.element.querySelector(".result-media-error")).toBeNull();
    Object.defineProperty(currentImage, "currentSrc", {
      value: "",
      configurable: true,
    });
    currentImage.dispatchEvent(new Event("error"));
    await nextTick();
    expect(mounted.element.querySelector(".result-media-error")).not.toBeNull();
    expect(mounted.element.querySelector(".image-stage > svg")).toBeNull();
    await loadImage(mounted.element);
    expect(mounted.element.querySelector(".result-media-error")).toBeNull();
    expect(mounted.element.querySelector(".image-stage > svg")).not.toBeNull();
    mounted.unmount();
  });
});
