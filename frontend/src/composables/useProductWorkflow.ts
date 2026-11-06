import { computed, onScopeDispose, reactive, ref } from "vue";
import { EXAMPLES, MAX_ANALYSIS_PHOTOS, MAX_INPUT_PHOTOS } from "../constants";
import { productService, type ProductService } from "../services/products";
import type {
  Analysis,
  Product,
  ProductSummary,
  WorkflowStatus,
} from "../types";
import { useProductDraft } from "./useProductDraft";

function message(cause: unknown) {
  return cause instanceof Error
    ? cause.message
    : "Не получилось выполнить действие. Попробуйте ещё раз.";
}

export function useProductWorkflow(api: ProductService = productService) {
  const draftState = useProductDraft();
  const product = ref<Product | null>(null);
  const analysis = ref<Analysis | null>(null);
  const selected = ref<string[]>([]);
  const examples = ref<Product[]>([]);
  const catalog = ref<ProductSummary[]>([]);
  const catalogId = ref("");
  const status = reactive<WorkflowStatus>({
    error: "",
    notice: "",
    loading: "",
    seconds: 0,
  });
  const busy = computed(() => Boolean(status.loading));
  const productTitle = computed(
    () =>
      EXAMPLES.find((example) => example.id === product.value?.id)?.title ||
      product.value?.name ||
      "",
  );
  const examplesIncomplete = computed(
    () => examples.value.length < EXAMPLES.length || !catalog.value.length,
  );
  let activeRequest: AbortController | null = null;
  let elapsedTimer: ReturnType<typeof setInterval> | undefined;
  let disposed = false;

  function clearMessages() {
    status.error = "";
    status.notice = "";
  }

  async function perform<T>(
    label: string,
    request: (signal: AbortSignal) => Promise<T>,
    apply: (value: T) => void,
  ) {
    if (busy.value || disposed) return;
    const controller = new AbortController();
    activeRequest = controller;
    status.loading = label;
    status.seconds = 0;
    clearMessages();
    const startedAt = Date.now();
    elapsedTimer = setInterval(() => {
      status.seconds = Math.floor((Date.now() - startedAt) / 1000);
    }, 1000);
    try {
      const value = await request(controller.signal);
      if (!disposed && activeRequest === controller) apply(value);
    } catch (cause) {
      if (
        !disposed &&
        activeRequest === controller &&
        !controller.signal.aborted
      )
        status.error = message(cause);
    } finally {
      if (activeRequest === controller) {
        clearInterval(elapsedTimer);
        activeRequest = null;
        if (!disposed) status.loading = "";
      }
    }
  }

  function setProduct(value: Product) {
    product.value = value;
    selected.value = value.images
      .slice(0, MAX_ANALYSIS_PHOTOS)
      .map((photo) => photo.id);
    analysis.value = null;
  }

  async function loadExamples() {
    await perform(
      "Загружаем примеры",
      async (signal) => {
        const productsRequest = Promise.allSettled(
          EXAMPLES.map((example) => api.get(example.id, signal)),
        );
        const [list] = await Promise.allSettled([api.list(signal)]);
        return { list, products: await productsRequest };
      },
      (result) => {
        catalog.value =
          result.list.status === "fulfilled" ? result.list.value : [];
        examples.value = result.products.flatMap((item) =>
          item.status === "fulfilled" ? [item.value] : [],
        );
        if (!examples.value.length && result.list.status === "rejected")
          status.error = message(result.list.reason);
        else if (examplesIncomplete.value)
          status.notice =
            "Часть примеров не загрузилась. Можно повторить загрузку или добавить свои фото.";
      },
    );
  }

  async function openExample(id: string) {
    if (busy.value) return;
    const normalized = id.trim();
    if (!normalized) {
      status.error = "Укажите ID товара из тестового набора.";
      return;
    }
    await perform(
      "Открываем фотографии товара",
      (signal) => {
        const cached = examples.value.find(
          (example) => example.id === normalized,
        );
        return cached ? Promise.resolve(cached) : api.get(normalized, signal);
      },
      setProduct,
    );
  }

  function addFiles(files: File[]) {
    if (busy.value) return;
    clearMessages();
    try {
      draftState.addFiles(files);
    } catch (cause) {
      status.error = message(cause);
    }
  }

  function removeUpload(key: number) {
    if (busy.value) return;
    draftState.removeFile(key);
    clearMessages();
  }

  async function prepareProduct() {
    if (busy.value) return;
    const { draft, imageCount, imageUrls } = draftState;
    if (!draft.name.trim()) {
      status.error = "Напишите, что это за товар. Например, чемодан.";
      return;
    }
    if (!imageCount.value) {
      status.error = "Добавьте хотя бы одно фото одного товара.";
      return;
    }
    if (imageCount.value > MAX_INPUT_PHOTOS) {
      status.error = "Для одного товара можно добавить до 20 фотографий.";
      return;
    }
    const input = {
      name: draft.name.trim(),
      description: draft.description.trim(),
      urls: [...imageUrls.value],
      files: draft.uploads.map((upload) => upload.file),
    };
    await perform(
      "Загружаем ваши фотографии",
      (signal) => api.create(input, signal),
      setProduct,
    );
  }

  function togglePhoto(id: string) {
    if (busy.value || !product.value?.images.some((photo) => photo.id === id))
      return;
    clearMessages();
    if (selected.value.includes(id))
      selected.value = selected.value.filter((value) => value !== id);
    else if (selected.value.length < MAX_ANALYSIS_PHOTOS)
      selected.value = [...selected.value, id];
    else {
      status.notice =
        "За один раз можно посмотреть до четырёх фото. Снимите отметку с одного из выбранных.";
      return;
    }
    analysis.value = null;
  }

  async function suggest() {
    if (!product.value || busy.value) return;
    const target = product.value;
    await perform(
      "Выбираем полезные ракурсы",
      (signal) => api.suggest(target, signal),
      (result) => {
        selected.value = result.selected_image_ids;
        analysis.value = null;
        status.notice =
          "Полезные ракурсы отмечены. Вы можете изменить выбор, затем нажать «Найти детали».";
      },
    );
  }

  async function analyze() {
    if (!product.value || !selected.value.length || busy.value) return;
    const id = product.value.id;
    const imageIds = [...selected.value];
    analysis.value = null;
    await perform(
      "Ищем детали на выбранных фото",
      (signal) => api.analyze(id, imageIds, signal),
      (result) => {
        analysis.value = result;
      },
    );
  }

  function startOver() {
    if (busy.value) return;
    draftState.reset();
    catalogId.value = "";
    product.value = null;
    analysis.value = null;
    selected.value = [];
    clearMessages();
  }

  function cancel() {
    if (!activeRequest || disposed) return;
    const request = activeRequest;
    activeRequest = null;
    request.abort();
    clearInterval(elapsedTimer);
    status.loading = "";
    status.seconds = 0;
    status.error = "";
    status.notice = "Ожидание отменено. Товар и выбранные фото сохранены.";
  }

  onScopeDispose(() => {
    disposed = true;
    activeRequest?.abort();
    clearInterval(elapsedTimer);
  });

  return {
    product,
    analysis,
    selected,
    examples,
    catalog,
    catalogId,
    productTitle,
    examplesIncomplete,
    status,
    busy,
    draft: draftState.draft,
    imageCount: draftState.imageCount,
    loadExamples,
    openExample,
    addFiles,
    removeUpload,
    prepareProduct,
    togglePhoto,
    suggest,
    analyze,
    startOver,
    cancel,
  };
}
