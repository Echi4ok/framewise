import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";
import { mountComponent } from "../test/fixtures";
import MotionSurface from "./MotionSurface.vue";

let contentHeight = 200;
let displayedHeight = 200;
let resize = () => {};
let preferenceChanged = () => {};
let reduced = false;
const cancel = vi.fn();
const disconnect = vi.fn();
const removeListener = vi.fn();
const animate = vi.fn(() => ({ cancel }));
const originalAnimate = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "animate",
);
const mounted: ReturnType<typeof mountComponent>[] = [];

function setup() {
  const wrapper = defineComponent({
    setup: () => () =>
      h(MotionSurface, null, { default: () => h("div", "Content") }),
  });
  const result = mountComponent(wrapper, {});
  mounted.push(result);
  return result;
}

beforeEach(() => {
  contentHeight = 200;
  displayedHeight = 200;
  reduced = false;
  cancel.mockClear();
  disconnect.mockClear();
  removeListener.mockClear();
  animate.mockClear();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(callback: () => void) {
        resize = callback;
      }
      observe() {}
      disconnect = disconnect;
    },
  );
  vi.stubGlobal("matchMedia", () => ({
    get matches() {
      return reduced;
    },
    addEventListener: (_event: string, listener: () => void) => {
      preferenceChanged = listener;
    },
    removeEventListener: removeListener,
  }));
  Object.defineProperty(HTMLElement.prototype, "animate", {
    configurable: true,
    value: animate,
  });
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      const height = this.classList.contains("motion-surface-content")
        ? contentHeight
        : displayedHeight;
      return new DOMRect(0, 0, 600, height);
    },
  );
});

afterEach(() => {
  mounted.splice(0).forEach((item) => item.unmount());
  vi.unstubAllGlobals();
  if (originalAnimate)
    Object.defineProperty(HTMLElement.prototype, "animate", originalAnimate);
  else Reflect.deleteProperty(HTMLElement.prototype, "animate");
});

describe("motion surface", () => {
  it("resizes from the visible height and can collapse an empty slot", () => {
    const { element } = setup();
    resize();
    expect(animate).not.toHaveBeenCalled();
    contentHeight = 360;
    resize();
    expect(animate).toHaveBeenLastCalledWith(
      [{ height: "200px" }, { height: "360px" }],
      expect.objectContaining({ duration: 320 }),
    );
    displayedHeight = 280;
    contentHeight = 400;
    resize();
    expect(animate).toHaveBeenLastCalledWith(
      [{ height: "280px" }, { height: "400px" }],
      expect.any(Object),
    );
    contentHeight = 0;
    resize();
    expect(
      element.querySelector<HTMLElement>(".motion-surface")?.style.height,
    ).toBe("0px");
  });

  it("cancels animation immediately when reduced motion is enabled", () => {
    setup();
    resize();
    contentHeight = 360;
    resize();
    expect(animate).toHaveBeenCalledTimes(1);
    reduced = true;
    preferenceChanged();
    expect(cancel).toHaveBeenCalled();
    contentHeight = 500;
    resize();
    expect(animate).toHaveBeenCalledTimes(1);
  });

  it("does not replay unchanged measurements and removes observers on unmount", () => {
    const result = setup();
    resize();
    resize();
    expect(animate).not.toHaveBeenCalled();
    result.unmount();
    mounted.pop();
    expect(disconnect).toHaveBeenCalledOnce();
    expect(removeListener).toHaveBeenCalledWith("change", expect.any(Function));
  });
});
