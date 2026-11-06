import { describe, expect, it, vi } from "vitest";
import { get, mountComponent, product } from "../test/fixtures";
import PhotoSelection from "./PhotoSelection.vue";

const idle = { error: "", notice: "", loading: "", seconds: 0 };

describe("photo selection presentation", () => {
  it("makes AI selection explicit before the gallery while retaining manual selection", async () => {
    const item = product();
    const suggest = vi.fn();
    const toggle = vi.fn();
    const mounted = mountComponent(PhotoSelection, {
      product: item,
      productTitle: item.name,
      selected: [item.images[0].id],
      busy: false,
      status: idle,
      onSuggest: suggest,
      onToggle: toggle,
    });
    try {
      const button = get(mounted.element, ".ai-select-button");
      const gallery = get(mounted.element, ".photo-grid");
      expect(button.textContent?.trim()).toBe("Подобрать фото с ИИ");
      expect(button.getAttribute("type")).toBe("button");
      expect(
        button.compareDocumentPosition(gallery) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).not.toBe(0);
      expect(button.getAttribute("aria-describedby")).toBe("ai-selection-help");
      expect(get(mounted.element, "#ai-selection-help").textContent).toContain(
        "изменить",
      );
      button.dispatchEvent(new MouseEvent("click"));
      expect(suggest).toHaveBeenCalledTimes(1);
      get(mounted.element, ".photo-card").dispatchEvent(
        new MouseEvent("click"),
      );
      expect(toggle).toHaveBeenCalledWith(item.images[0].id);
      await mounted.setProps({ busy: true });
      expect(button.hasAttribute("disabled")).toBe(true);
    } finally {
      mounted.unmount();
    }
  });

  it("explains why AI selection is unavailable for a single photo", async () => {
    const item = product("single", 1);
    const mounted = mountComponent(PhotoSelection, {
      product: item,
      productTitle: item.name,
      selected: [item.images[0].id],
      busy: false,
      status: idle,
    });
    try {
      expect(
        get(mounted.element, ".ai-select-button").hasAttribute("disabled"),
      ).toBe(true);
      expect(get(mounted.element, "#ai-selection-help").textContent).toContain(
        "одно фото",
      );
      await mounted.setProps({ selected: [] });
      expect(get(mounted.element, "#ai-selection-help").textContent).toContain(
        "Отметьте его",
      );
    } finally {
      mounted.unmount();
    }
  });

  it("displays readable description text while leaving the source DTO unchanged", () => {
    const item = product();
    item.name = "Товар — пример";
    item.description =
      "<p>Описание&nbsp;&amp; детали</p><ul><li>Ручка</li></ul><script>alert(1)</script>";
    const original = item.description;
    const mounted = mountComponent(PhotoSelection, {
      product: item,
      productTitle: item.name,
      selected: [],
      busy: false,
      status: idle,
    });
    try {
      expect(get(mounted.element, ".product-description").textContent).toBe(
        "Описание & детали\n\n• Ручка",
      );
      expect(mounted.element.querySelector("script")).toBeNull();
      expect(get(mounted.element, ".product-heading h2").textContent).toBe(
        "Товар - пример",
      );
      expect(item.description).toBe(original);
      expect(item.name).toBe("Товар — пример");
    } finally {
      mounted.unmount();
    }
  });
});
