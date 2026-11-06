<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { formatUiText } from "../presentation/text";
import type { Analysis, Feature, Product } from "../types";

const props = defineProps<{
  analysis: Analysis;
  product: Product;
}>();

const activeImageId = ref("");
const activeFeatureId = ref("");
const hoveredFeatureId = ref("");
const imageReady = ref(false);
const imageError = ref(false);
const colors = ["#6346df", "#008c87", "#c55b15", "#b23e7a", "#3f6eba"];

const resultPhotos = computed(() =>
  props.product.images.filter((photo) =>
    props.analysis.features.some((feature) => feature.image_id === photo.id),
  ),
);
const activePhoto = computed(() =>
  resultPhotos.value.find((photo) => photo.id === activeImageId.value),
);
const activeFeatures = computed(() =>
  props.analysis.features.filter(
    (feature) => feature.image_id === activeImageId.value,
  ),
);
const featureWord = computed(() =>
  props.analysis.features.length === 5 ? "деталей" : "детали",
);

watch(
  () => props.analysis,
  (analysis) => {
    const firstFeature = analysis.features[0];
    activeImageId.value = firstFeature?.image_id ?? "";
    activeFeatureId.value = firstFeature?.id ?? "";
    hoveredFeatureId.value = "";
  },
  { immediate: true },
);

function focusFeature(feature: Feature) {
  activeFeatureId.value = feature.id;
  activeImageId.value = feature.image_id;
  hoveredFeatureId.value = "";
}

watch(
  activeImageId,
  () => {
    imageReady.value = false;
    imageError.value = false;
  },
  { flush: "sync" },
);

function isCurrentImage(event: Event) {
  const image = event.currentTarget;
  const photo = activePhoto.value;
  if (!(image instanceof HTMLImageElement) || !photo) return false;
  const source = new URL(photo.url, window.location.href).href;
  return (
    image.src === source && (!image.currentSrc || image.currentSrc === source)
  );
}

function showImage(event: Event) {
  if (!isCurrentImage(event)) return;
  imageError.value = false;
  imageReady.value = true;
}

function showImageError(event: Event) {
  if (!isCurrentImage(event)) return;
  imageError.value = true;
  imageReady.value = false;
}

function chooseResultPhoto(id: string) {
  activeImageId.value = id;
  activeFeatureId.value =
    props.analysis.features.find((feature) => feature.image_id === id)?.id ??
    "";
  hoveredFeatureId.value = "";
}

function featureIndex(feature: Feature) {
  return props.analysis.features.findIndex((value) => value.id === feature.id);
}

function photoNumber(id: string) {
  return props.product.images.findIndex((photo) => photo.id === id) + 1;
}

function color(feature: Feature) {
  return colors[featureIndex(feature) % colors.length];
}

function highlighted(feature: Feature) {
  return feature.id === (hoveredFeatureId.value || activeFeatureId.value);
}
</script>

<template>
  <section id="results" class="results panel" tabindex="-1">
    <div class="results-heading">
      <div>
        <h2>Что видно на товаре</h2>
        <p class="result-product-name">{{ formatUiText(product.name) }}</p>
        <p>Нажмите на деталь в списке, чтобы увидеть её на фото.</p>
      </div>
      <span class="count-chip"
        >{{ analysis.features.length }} {{ featureWord }}</span
      >
    </div>

    <div class="result-layout">
      <div class="result-visual">
        <div class="result-media-frame" :aria-busy="!imageReady && !imageError">
          <div v-if="activePhoto" class="image-stage">
            <img
              :key="activePhoto.id"
              :src="activePhoto.url"
              :width="activePhoto.width"
              :height="activePhoto.height"
              :class="{ 'image-pending': !imageReady }"
              :alt="`Фото ${photoNumber(activePhoto.id)}. ${formatUiText(product.name)}`"
              @load="showImage"
              @error="showImageError"
            />
            <svg
              v-if="imageReady"
              viewBox="0 0 1000 1000"
              preserveAspectRatio="none"
              aria-label="Области найденных деталей"
            >
              <g
                v-for="feature in activeFeatures"
                :key="feature.id"
                class="bbox"
                :class="{ highlighted: highlighted(feature) }"
                tabindex="0"
                role="button"
                :aria-label="formatUiText(feature.description)"
                @mouseenter="hoveredFeatureId = feature.id"
                @mouseleave="hoveredFeatureId = ''"
                @focus="hoveredFeatureId = feature.id"
                @blur="hoveredFeatureId = ''"
                @click="focusFeature(feature)"
                @keydown.enter.prevent="focusFeature(feature)"
                @keydown.space.prevent="focusFeature(feature)"
              >
                <rect
                  :x="feature.bbox[0]"
                  :y="feature.bbox[1]"
                  :width="feature.bbox[2] - feature.bbox[0]"
                  :height="feature.bbox[3] - feature.bbox[1]"
                  :stroke="color(feature)"
                  :fill="color(feature)"
                  vector-effect="non-scaling-stroke"
                />
                <svg
                  :x="feature.bbox[0]"
                  :y="Math.max(0, feature.bbox[1] - 70)"
                  width="80"
                  height="70"
                  viewBox="0 0 70 70"
                  preserveAspectRatio="xMinYMin meet"
                >
                  <rect
                    width="62"
                    height="62"
                    rx="10"
                    :fill="color(feature)"
                    class="bbox-label"
                  />
                  <text x="31" y="45" text-anchor="middle">
                    {{ featureIndex(feature) + 1 }}
                  </text>
                </svg>
              </g>
            </svg>
          </div>
          <p v-if="imageError" role="alert" class="result-media-error">
            Не удалось открыть фото. Попробуйте другой кадр.
          </p>
          <span v-else-if="!imageReady" aria-hidden="true" class="image-loading"
            ><span class="spinner"></span
          ></span>
        </div>

        <div class="result-thumbs">
          <button
            v-for="photo in resultPhotos"
            :key="photo.id"
            :class="{ active: photo.id === activeImageId }"
            :aria-pressed="photo.id === activeImageId"
            :aria-label="`Показать детали на фото ${photoNumber(photo.id)}. ${formatUiText(product.name)}`"
            @click="chooseResultPhoto(photo.id)"
          >
            <img :src="photo.url" alt="" />
            <span class="result-photo-label"
              >Фото {{ photoNumber(photo.id) }}</span
            >
          </button>
        </div>
      </div>

      <div class="feature-list">
        <button
          v-for="feature in analysis.features"
          :key="feature.id"
          class="feature"
          :class="{ active: highlighted(feature) }"
          :style="{ '--feature-color': color(feature) }"
          @click="focusFeature(feature)"
          @mouseenter="hoveredFeatureId = feature.id"
          @mouseleave="hoveredFeatureId = ''"
          @focus="hoveredFeatureId = feature.id"
          @blur="hoveredFeatureId = ''"
        >
          <span class="feature-number">{{ featureIndex(feature) + 1 }}</span>
          <span>{{ formatUiText(feature.description) }}</span>
          <span class="feature-arrow" aria-hidden="true">↗</span>
        </button>
        <p class="result-note">
          AI может ошибаться. Проверьте найденные детали на фотографиях.
        </p>
      </div>
    </div>
  </section>
</template>
