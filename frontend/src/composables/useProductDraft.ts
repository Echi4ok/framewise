import { computed, markRaw, onScopeDispose, reactive } from "vue";
import { MAX_IMAGE_BYTES, MAX_INPUT_PHOTOS } from "../constants";
import type { ProductDraft, Upload } from "../types";

export function useProductDraft() {
  const draft = reactive<ProductDraft>({
    name: "",
    description: "",
    urls: "",
    uploads: [],
  });
  let nextKey = 0;
  const imageUrls = computed(() =>
    draft.urls
      .split(/\r?\n/)
      .map((url) => url.trim())
      .filter(Boolean),
  );
  const imageCount = computed(
    () => draft.uploads.length + imageUrls.value.length,
  );

  function addFiles(files: File[]) {
    const existing = new Set(draft.uploads.map((upload) => upload.file));
    const additions = files.filter((file) => {
      if (existing.has(file)) return false;
      existing.add(file);
      return true;
    });
    if (imageCount.value + additions.length > MAX_INPUT_PHOTOS)
      throw new Error("Для одного товара можно добавить до 20 фотографий.");
    for (const file of additions) {
      if (file.size > MAX_IMAGE_BYTES)
        throw new Error(
          `Файл «${file.name}» больше 8 МБ. Выберите фотографию поменьше.`,
        );
      if (!/\.(jpe?g|png|webp)$/i.test(file.name))
        throw new Error("Выберите фотографии JPEG, PNG или WebP.");
    }
    const previews: Upload[] = [];
    try {
      for (const file of additions) {
        previews.push({
          key: nextKey++,
          file: markRaw(file),
          preview: URL.createObjectURL(file),
        });
      }
    } catch {
      previews.forEach((upload) => URL.revokeObjectURL(upload.preview));
      throw new Error(
        "Не удалось подготовить фотографии. Добавьте их ещё раз.",
      );
    }
    draft.uploads.push(...previews);
  }

  function removeFile(key: number) {
    const upload = draft.uploads.find((item) => item.key === key);
    if (upload) URL.revokeObjectURL(upload.preview);
    draft.uploads = draft.uploads.filter((item) => item.key !== key);
  }

  function reset() {
    draft.uploads.forEach((upload) => URL.revokeObjectURL(upload.preview));
    draft.uploads = [];
    draft.name = "";
    draft.description = "";
    draft.urls = "";
  }

  onScopeDispose(reset);
  return { draft, imageUrls, imageCount, addFiles, removeFile, reset };
}
