<script setup lang="ts">
import { computed, onMounted } from "vue";
import AnalysisResults from "./components/AnalysisResults.vue";
import ProductUploadForm from "./components/ProductUploadForm.vue";
import ProductExamples from "./components/ProductExamples.vue";
import PhotoSelection from "./components/PhotoSelection.vue";
import MotionSurface from "./components/MotionSurface.vue";
import { useProductWorkflow } from "./composables/useProductWorkflow";
import { useWorkflowNavigation } from "./composables/useWorkflowNavigation";

const workflow = useProductWorkflow();
const {
  draft,
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
  imageCount,
} = workflow;
useWorkflowNavigation(product, analysis, () => status.error);
onMounted(workflow.loadExamples);
const currentStep = computed(() =>
  analysis.value ? 3 : product.value ? 2 : 1,
);
const steps = ["Добавьте фото", "Выберите ракурсы", "Посмотрите детали"];
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <a href="/" class="brand" aria-label="Framewise: начать заново"
        ><span class="brand-mark" aria-hidden="true"
          ><svg viewBox="0 0 24 24" fill="none">
            <path
              d="M8 4H5a1 1 0 0 0-1 1v3m12-4h3a1 1 0 0 1 1 1v3M4 16v3a1 1 0 0 0 1 1h3m8 0h3a1 1 0 0 0 1-1v-3"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
            />
            <circle
              cx="12"
              cy="12"
              r="3.5"
              stroke="currentColor"
              stroke-width="1.8"
            /></svg></span
        >Framewise</a
      >
      <span class="top-caption header-tag">Студия деталей товара</span>
    </header>
    <main>
      <ol class="workflow-steps" aria-label="Этапы анализа">
        <li
          v-for="(step, index) in steps"
          :key="step"
          :class="{
            active: currentStep === index + 1,
            complete: currentStep > index + 1,
          }"
          :aria-current="currentStep === index + 1 ? 'step' : undefined"
        >
          <span aria-hidden="true">{{
            currentStep > index + 1 ? "✓" : index + 1
          }}</span
          >{{ step }}
        </li>
      </ol>
      <MotionSurface>
        <Transition name="stage">
          <div v-if="!product" key="upload" class="workspace-shell">
            <section class="intro">
              <h1>Покажите товар.<br /><span>Увидьте детали.</span></h1>
              <p>
                Загрузите
                <strong>одно фото или несколько фото одного товара</strong> с
                разных сторон. Получите описания деталей и увидьте их прямо на
                снимках.
              </p>
              <div class="purpose-example">
                <span aria-hidden="true">↳</span
                ><span
                  >Например, ручку, замок и внутренние ремни чемодана.</span
                >
              </div>
            </section>
            <ProductUploadForm
              v-model:name="draft.name"
              v-model:description="draft.description"
              v-model:urls="draft.urls"
              :uploads="draft.uploads"
              :image-count="imageCount"
              :busy="busy"
              :status="status"
              @submit="workflow.prepareProduct"
              @add-files="workflow.addFiles"
              @remove-upload="workflow.removeUpload"
              @dismiss="status.error = ''"
            />
            <ProductExamples
              v-model:catalog-id="catalogId"
              :examples="examples"
              :catalog="catalog"
              :busy="busy"
              :retry-available="examplesIncomplete"
              @open="workflow.openExample"
              @retry="workflow.loadExamples"
            />
          </div>
          <PhotoSelection
            v-else
            :key="product.id"
            :product="product"
            :product-title="productTitle"
            :selected="selected"
            :busy="busy"
            :status="status"
            @reset="workflow.startOver"
            @toggle="workflow.togglePhoto"
            @suggest="workflow.suggest"
            @analyze="workflow.analyze"
            @cancel="workflow.cancel"
            @dismiss="status.error = ''"
          />
        </Transition>
      </MotionSurface>
      <Transition name="stage">
        <AnalysisResults
          v-if="analysis && product"
          :analysis="analysis"
          :product="product"
        />
      </Transition>
    </main>
  </div>
</template>
