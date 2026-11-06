<script setup lang="ts">
import { formatUiText } from "../presentation/text";

defineProps<{
  error: string;
  notice: string;
  loading: string;
  seconds: number;
  idleText?: string;
}>();
defineEmits<{ dismiss: []; cancel: [] }>();
</script>

<template>
  <div class="feedback-slot" :aria-busy="Boolean(loading)">
    <div
      v-if="loading"
      role="status"
      aria-live="polite"
      class="progress-message"
    >
      <span class="spinner"></span>
      <div>
        <strong>{{ formatUiText(loading) }}…</strong>
        <p>
          {{
            loading.includes("детали") || loading.includes("ракурсы")
              ? "Первый запуск модели может занять около минуты."
              : "Подождите немного."
          }}
        </p>
      </div>
      <span class="elapsed">{{ seconds }} с</span>
      <button
        v-if="loading.includes('детали') || loading.includes('ракурсы')"
        class="status-cancel"
        type="button"
        @click="$emit('cancel')"
      >
        Отменить
      </button>
    </div>
    <div
      v-else-if="error"
      id="error-message"
      role="alert"
      class="message error"
      tabindex="-1"
    >
      <p>{{ formatUiText(error) }}</p>
      <button
        type="button"
        aria-label="Закрыть ошибку"
        @click="$emit('dismiss')"
      >
        ×
      </button>
    </div>
    <div v-else-if="notice" role="status" class="message notice">
      <p>{{ formatUiText(notice) }}</p>
    </div>
    <p v-else-if="idleText" class="feedback-idle">
      {{ formatUiText(idleText) }}
    </p>
    <span v-else aria-hidden="true" class="feedback-empty"></span>
  </div>
</template>
