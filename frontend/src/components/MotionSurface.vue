<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";

const surface = ref<HTMLElement | null>(null);
const content = ref<HTMLElement | null>(null);
let observer: ResizeObserver | undefined;
let animation: Animation | undefined;
let previousHeight = 0;
let preference: MediaQueryList | undefined;
function respectMotionPreference() {
  if (preference?.matches) animation?.cancel();
}

onMounted(() => {
  if (!surface.value || !content.value || typeof ResizeObserver === "undefined")
    return;
  const frame = surface.value;
  const body = content.value;
  preference = window.matchMedia("(prefers-reduced-motion: reduce)");
  preference.addEventListener("change", respectMotionPreference);
  observer = new ResizeObserver(() => {
    const nextHeight = Math.ceil(body.getBoundingClientRect().height);
    if (nextHeight === previousHeight) return;
    const from = frame.getBoundingClientRect().height;
    animation?.cancel();
    frame.style.height = `${nextHeight}px`;
    if (
      previousHeight &&
      !preference?.matches &&
      typeof frame.animate === "function"
    ) {
      animation = frame.animate(
        [{ height: `${from}px` }, { height: `${nextHeight}px` }],
        { duration: 320, easing: "cubic-bezier(.22, 1, .36, 1)" },
      );
    }
    previousHeight = nextHeight;
  });
  observer.observe(body);
});

onUnmounted(() => {
  observer?.disconnect();
  animation?.cancel();
  preference?.removeEventListener("change", respectMotionPreference);
});
</script>

<template>
  <div ref="surface" class="motion-surface">
    <div ref="content" class="motion-surface-content"><slot /></div>
  </div>
</template>
