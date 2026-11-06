<script setup lang="ts">
import { computed } from "vue";
import { productDescriptionText } from "../presentation/productDescription";
import { formatUiText } from "../presentation/text";
import type { Product, WorkflowStatus } from "../types";
import StatusMessages from "./StatusMessages.vue";
const props = defineProps<{
  product: Product;
  productTitle: string;
  selected: string[];
  busy: boolean;
  status: WorkflowStatus;
}>();
const descriptionText = computed(() =>
  productDescriptionText(props.product.description),
);
const emit = defineEmits<{
  reset: [];
  toggle: [id: string];
  suggest: [];
  analyze: [];
  dismiss: [];
  cancel: [];
}>();
</script>

<template>
  <section id="photo-selection" class="panel selection-panel" tabindex="-1">
    <div class="product-heading">
      <div>
        <p class="overline">ОДИН ТОВАР</p>
        <h2>{{ formatUiText(productTitle) }}</h2>
      </div>
      <button class="text-button" :disabled="busy" @click="emit('reset')">
        ← Другой товар
      </button>
    </div>
    <h3>Какие фото посмотреть?</h3>
    <p class="section-help">
      {{
        product.images.length === 1
          ? "На этом фото модель найдёт видимые детали товара."
          : "Отметьте от 1 до 4 фото этого же товара. Разные ракурсы помогут увидеть больше деталей."
      }}
    </p>
    <div class="selection-tools">
      <button
        class="button secondary ai-select-button"
        type="button"
        :disabled="busy || product.images.length < 2"
        :aria-busy="status.loading.includes('ракурсы')"
        aria-describedby="ai-selection-help"
        @click="emit('suggest')"
      >
        Подобрать фото с ИИ
      </button>
      <p id="ai-selection-help" class="ai-selection-help">
        {{
          product.images.length > 1
            ? "ИИ предложит до четырёх полезных ракурсов. Выбор можно изменить перед анализом."
            : selected.length
              ? "Здесь одно фото. Оно уже выбрано для анализа."
              : "Здесь одно фото. Отметьте его для анализа."
        }}
      </p>
    </div>
    <div class="photo-grid">
      <button
        v-for="(photo, index) in product.images"
        :key="photo.id"
        class="photo-card"
        :class="{ selected: selected.includes(photo.id) }"
        :disabled="busy"
        :aria-pressed="selected.includes(photo.id)"
        :aria-label="`Фото ${index + 1}${selected.includes(photo.id) ? ', выбрано' : ''}`"
        @click="emit('toggle', photo.id)"
      >
        <img
          :src="photo.url"
          :width="photo.width"
          :height="photo.height"
          :alt="`Фото ${index + 1}. ${formatUiText(productTitle)}`"
        /><span class="photo-caption">Фото {{ index + 1 }}</span
        ><span class="selection-mark" aria-hidden="true">{{
          selected.includes(photo.id) ? "✓" : ""
        }}</span>
      </button>
    </div>
    <div class="actions">
      <div>
        <p class="selection-count">
          Выбрано <strong>{{ selected.length }}</strong> из
          {{ product.images.length }}
        </p>
      </div>
      <button
        class="button primary"
        :disabled="busy || !selected.length"
        @click="emit('analyze')"
      >
        Найти детали на {{ selected.length }} фото
        <span aria-hidden="true">→</span>
      </button>
    </div>
    <p class="output-explanation">
      Вы получите 3-5 описаний деталей и рамки на выбранных фотографиях.
    </p>
    <StatusMessages
      v-bind="status"
      @dismiss="emit('dismiss')"
      @cancel="emit('cancel')"
    />
    <details class="product-details">
      <summary>Информация о товаре</summary>
      <p>{{ formatUiText(product.name) }}</p>
      <p v-if="descriptionText" class="product-description">
        {{ descriptionText }}
      </p>
      <small>ID: {{ product.id }}</small>
    </details>
  </section>
</template>
