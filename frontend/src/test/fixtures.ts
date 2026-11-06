import type { Component } from "vue";
import { createApp, h, nextTick, reactive } from "vue";
import type { Analysis, Product } from "../types";

export function product(id = "test-product", photos = 5): Product {
  return {
    id,
    name: "Тестовый товар",
    description: "Описание товара",
    images: Array.from({ length: photos }, (_, index) => ({
      id: `${id}-${index + 1}`,
      url: `/api/media/${id}-${index + 1}`,
      width: 1200,
      height: 1600,
    })),
  };
}

export function analysis(item: Product): Analysis {
  return {
    features: [0, 1, 2].map((index) => ({
      id: `feature-${index + 1}`,
      image_id: item.images[index % item.images.length].id,
      description: `Видимая деталь ${index + 1}`,
      bbox: [index * 100, 10, index * 100 + 50, 150],
    })),
  };
}

export function deferred<T>() {
  let resolve: (value: T) => void = () => {
    throw new Error("Promise is not initialized");
  };
  let reject: (reason?: unknown) => void = () => {
    throw new Error("Promise is not initialized");
  };
  const promise = new Promise<T>((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, resolve, reject };
}

export function mountComponent(
  component: Component,
  props: Record<string, unknown>,
) {
  const state = reactive(props);
  const element = document.createElement("div");
  document.body.append(element);
  const app = createApp({ setup: () => () => h(component, state) });
  app.mount(element);
  return {
    element,
    async setProps(value: Record<string, unknown>) {
      Object.assign(state, value);
      await nextTick();
    },
    unmount() {
      app.unmount();
      element.remove();
    },
  };
}

export function get(element: Element, selector: string) {
  const node = element.querySelector(selector);
  if (!node) throw new Error(`Missing element: ${selector}`);
  return node;
}
