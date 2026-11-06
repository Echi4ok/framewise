<script setup lang="ts">
import { computed } from "vue";
import { formatUiText } from "../presentation/text";
import { EXAMPLES } from "../constants";
import type { Product, ProductSummary } from "../types";
const props = defineProps<{
  examples: Product[];
  catalog: ProductSummary[];
  busy: boolean;
  retryAvailable: boolean;
}>();
const catalogId = defineModel<string>("catalogId", { required: true });
const emit = defineEmits<{ open: [id: string]; retry: [] }>();
const cards = computed(() =>
  EXAMPLES.map((definition) => ({
    ...definition,
    product: props.examples.find((product) => product.id === definition.id),
  })),
);
</script>

<template>
  <section class="examples" aria-label="Готовые примеры">
    <h2>Хотите сначала попробовать?</h2>
    <p>Откройте готовые фото одного товара.</p>
    <div class="example-grid">
      <button
        v-for="card in cards"
        :key="card.id"
        class="example-card"
        :disabled="busy || !card.product"
        @click="emit('open', card.id)"
      >
        <img
          v-if="card.product?.images[0]"
          :src="card.product.images[0].url"
          width="45"
          height="54"
          :alt="card.title"
        /><span
          ><strong>{{ card.action }}</strong
          ><small
            >{{ card.product?.images.length ?? "…" }} фото одного товара</small
          ></span
        ><span class="example-arrow" aria-hidden="true">→</span>
      </button>
    </div>
    <button
      v-if="retryAvailable && !busy"
      class="text-button"
      @click="emit('retry')"
    >
      Загрузить примеры ещё раз
    </button>
    <details class="catalog-details">
      <summary>Открыть другой товар из тестового набора</summary>
      <form class="catalog-form" @submit.prevent="emit('open', catalogId)">
        <label for="product-id">ID товара</label>
        <div>
          <input
            id="product-id"
            v-model="catalogId"
            list="products"
            required
            :disabled="busy"
            placeholder="ID из products.csv"
          /><datalist id="products">
            <option v-for="entry in catalog" :key="entry.id" :value="entry.id">
              {{ formatUiText(entry.name) }}
            </option></datalist
          ><button class="button secondary" :disabled="busy">Открыть</button>
        </div>
      </form>
    </details>
  </section>
</template>
