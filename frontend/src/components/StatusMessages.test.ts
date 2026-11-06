import { nextTick } from "vue";
import { describe, expect, it, vi } from "vitest";
import { get, mountComponent } from "../test/fixtures";
import StatusMessages from "./StatusMessages.vue";

describe("feedback slot", () => {
  it("offers cancellation only while inspecting details or selecting views", async () => {
    const cancel = vi.fn();
    const mounted = mountComponent(StatusMessages, {
      error: "",
      notice: "",
      loading: "Загружаем фотографии",
      seconds: 0,
      onCancel: cancel,
    });
    expect(mounted.element.querySelector(".status-cancel")).toBeNull();
    await mounted.setProps({ loading: "Выбираем полезные ракурсы" });
    get(mounted.element, ".status-cancel").dispatchEvent(
      new MouseEvent("click"),
    );
    expect(cancel).toHaveBeenCalledTimes(1);
    await mounted.setProps({ loading: "Ищем детали на выбранных фото" });
    expect(get(mounted.element, ".status-cancel").textContent?.trim()).toBe(
      "Отменить",
    );
    await mounted.setProps({ loading: "" });
    expect(mounted.element.querySelector(".status-cancel")).toBeNull();
    mounted.unmount();
  });

  it("keeps one slot mounted and announces only the current state", async () => {
    const dismiss = vi.fn();
    const mounted = mountComponent(StatusMessages, {
      error: "",
      notice: "",
      loading: "",
      seconds: 0,
      onDismiss: dismiss,
    });
    const slot = get(mounted.element, ".feedback-slot");
    await mounted.setProps({
      loading: "Ищем детали",
      notice: "Old notice",
      error: "Old error",
    });
    expect(mounted.element.querySelectorAll('[role="status"]')).toHaveLength(1);
    expect(mounted.element.querySelector('[role="alert"]')).toBeNull();
    await mounted.setProps({ loading: "" });
    expect(get(mounted.element, '[role="alert"]').textContent).toContain(
      "Old error",
    );
    expect(get(mounted.element, ".feedback-slot")).toBe(slot);
    get(mounted.element, 'button[aria-label="Закрыть ошибку"]').dispatchEvent(
      new MouseEvent("click"),
    );
    await nextTick();
    expect(dismiss).toHaveBeenCalledTimes(1);
    mounted.unmount();
  });
});
