<script setup lang="ts">
import { ref } from "vue";
import type { Upload, WorkflowStatus } from "../types";
import StatusMessages from "./StatusMessages.vue";

defineProps<{
  uploads: Upload[];
  imageCount: number;
  busy: boolean;
  status: WorkflowStatus;
}>();
const name = defineModel<string>("name", { required: true });
const description = defineModel<string>("description", { required: true });
const urls = defineModel<string>("urls", { required: true });
const emit = defineEmits<{
  submit: [];
  addFiles: [files: File[]];
  removeUpload: [key: number];
  dismiss: [];
}>();
const fileInput = ref<HTMLInputElement | null>(null);
const dragging = ref(false);

function chooseFiles(event: Event) {
  if (!(event.target instanceof HTMLInputElement)) return;
  emit("addFiles", Array.from(event.target.files ?? []));
  event.target.value = "";
}
function dropFiles(event: DragEvent) {
  dragging.value = false;
  emit("addFiles", Array.from(event.dataTransfer?.files ?? []));
}
</script>

<template>
  <section id="upload-form" class="panel upload-panel" tabindex="-1">
    <h2>Добавьте фото одного товара</h2>
    <p class="section-help">
      Одного фото достаточно. Можно добавить несколько ракурсов.
    </p>
    <form @submit.prevent="emit('submit')">
      <label class="field-label" for="name">Что это за товар?</label>
      <input
        id="name"
        v-model="name"
        required
        maxlength="200"
        :disabled="busy"
        placeholder="Например, чемодан"
        autocomplete="off"
      />

      <input
        ref="fileInput"
        type="file"
        class="visually-hidden"
        tabindex="-1"
        aria-label="Файлы фотографий"
        accept="image/jpeg,image/png,image/webp"
        multiple
        :disabled="busy"
        @change="chooseFiles"
      />
      <button
        class="dropzone"
        :class="{ dragging }"
        type="button"
        :disabled="busy"
        @click="fileInput?.click()"
        @dragover.prevent="dragging = !busy"
        @dragleave.prevent="dragging = false"
        @drop.prevent="dropFiles"
      >
        <svg
          width="32"
          height="32"
          viewBox="0 0 32 32"
          fill="none"
          aria-hidden="true"
        >
          <rect
            x="4"
            y="4"
            width="24"
            height="24"
            rx="5"
            stroke="currentColor"
            stroke-width="1.6"
          />
          <circle
            cx="11"
            cy="11"
            r="2.5"
            stroke="currentColor"
            stroke-width="1.6"
          />
          <path
            d="m5 24 7-7 5 5 5-9 6 10"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linejoin="round"
          />
        </svg>
        <strong>{{
          uploads.length ? "Добавить ещё фото" : "Выбрать фотографии"
        }}</strong>
        <span>или перетащите их сюда</span>
        <small>JPEG, PNG, WebP · до 8 МБ на фото</small>
      </button>

      <TransitionGroup
        name="list"
        tag="div"
        class="upload-previews"
        aria-label="Загруженные фотографии"
      >
        <div
          v-for="(upload, index) in uploads"
          :key="upload.key"
          class="upload-preview"
        >
          <img
            :src="upload.preview"
            :alt="`Добавленное фото ${index + 1}`"
          /><span>{{ index + 1 }}</span
          ><button
            type="button"
            :disabled="busy"
            :aria-label="`Убрать фото ${index + 1}`"
            @click="emit('removeUpload', upload.key)"
          >
            ×
          </button>
        </div>
      </TransitionGroup>

      <details class="optional-fields">
        <summary>Добавить фото по ссылке или описание</summary>
        <div class="optional-content">
          <label class="field-label" for="urls"
            >Прямые ссылки на фотографии</label
          ><textarea
            id="urls"
            v-model="urls"
            rows="2"
            :disabled="busy"
            placeholder="https://…&#10;Каждая ссылка с новой строки"
          ></textarea
          ><label class="field-label" for="description"
            >Описание товара, если нужно</label
          ><textarea
            id="description"
            v-model="description"
            maxlength="6000"
            rows="2"
            :disabled="busy"
            placeholder="Необязательно"
          ></textarea>
        </div>
      </details>
      <div class="form-bottom">
        <StatusMessages
          v-bind="status"
          :idle-text="
            imageCount
              ? `Добавлено фото: ${imageCount}`
              : 'Для начала добавьте хотя бы одно фото'
          "
          @dismiss="emit('dismiss')"
        />
        <button class="button primary" :disabled="busy || !imageCount">
          Продолжить <span aria-hidden="true">→</span>
        </button>
      </div>
    </form>
  </section>
</template>
