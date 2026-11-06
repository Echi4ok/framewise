import { nextTick, onScopeDispose, watch, type Ref } from "vue";
import type { Analysis, Product } from "../types";

export function useWorkflowNavigation(
  product: Ref<Product | null>,
  analysis: Ref<Analysis | null>,
  error: () => string,
) {
  let revision = 0;
  watch(
    [product, analysis, error],
    async (
      [item, result, problem],
      [previousItem, previousResult, previousProblem],
    ) => {
      let target: string;
      if (problem && problem !== previousProblem) target = "error-message";
      else if (result && result !== previousResult) target = "results";
      else if (item !== previousItem)
        target = item ? "photo-selection" : "upload-form";
      else return;
      const current = ++revision;
      await nextTick();
      if (current !== revision) return;
      const element = document.getElementById(target);
      const reducedMotion = window.matchMedia?.(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      element?.scrollIntoView?.({
        behavior: reducedMotion ? "instant" : "smooth",
        block: "start",
      });
      element?.focus({ preventScroll: true });
    },
    { flush: "post" },
  );
  onScopeDispose(() => {
    revision += 1;
  });
}
