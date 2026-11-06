import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, type EffectScope } from "vue";
import { MAX_IMAGE_BYTES } from "../constants";
import { useProductDraft } from "./useProductDraft";

const scopes: EffectScope[] = [];
function setup() {
  const scope = effectScope();
  scopes.push(scope);
  const draft = scope.run(useProductDraft);
  if (!draft) throw new Error("Missing active scope");
  return draft;
}
beforeEach(() => {
  vi.spyOn(URL, "createObjectURL").mockImplementation(
    () => `blob:${Math.random()}`,
  );
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
});
afterEach(() => {
  scopes.splice(0).forEach((scope) => scope.stop());
});

describe("upload draft", () => {
  it("does not drop distinct files with identical names, sizes and timestamps", () => {
    const state = setup();
    const options = { lastModified: 10 };
    state.addFiles([
      new File(["one"], "photo.jpg", options),
      new File(["two"], "photo.jpg", options),
    ]);
    expect(state.draft.uploads).toHaveLength(2);
  });

  it("releases allocated previews if preparation fails partway", () => {
    const state = setup();
    vi.mocked(URL.createObjectURL)
      .mockReturnValueOnce("blob:first")
      .mockImplementationOnce(() => {
        throw new Error("Preview failed");
      });
    expect(() =>
      state.addFiles([
        new File(["one"], "one.jpg"),
        new File(["two"], "two.jpg"),
      ]),
    ).toThrow("подготовить фотографии");
    expect(state.draft.uploads).toEqual([]);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:first");
  });

  it("validates the whole batch before creating previews", () => {
    const state = setup();
    expect(() =>
      state.addFiles([
        new File(["jpeg"], "good.jpg"),
        new File(["text"], "bad.txt"),
      ]),
    ).toThrow("JPEG");
    expect(state.draft.uploads).toEqual([]);
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("rejects oversized files and counts URLs toward the input limit", () => {
    const state = setup();
    expect(() =>
      state.addFiles([
        new File([new Uint8Array(MAX_IMAGE_BYTES + 1)], "large.png"),
      ]),
    ).toThrow("8 МБ");
    state.draft.urls = Array.from(
      { length: 20 },
      (_, index) => `https://images.test/${index}.jpg`,
    ).join("\n");
    expect(() => state.addFiles([new File(["a"], "small.jpg")])).toThrow(
      "20 фотографий",
    );
  });

  it("deduplicates selections and releases each preview once on remove/reset/dispose", () => {
    const state = setup();
    const first = new File(["a"], "one.jpg", { lastModified: 10 });
    state.addFiles([first, first, new File(["b"], "two.jpg")]);
    state.addFiles([first]);
    expect(state.draft.uploads).toHaveLength(2);
    const preview = state.draft.uploads[0];
    state.removeFile(preview.key);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith(preview.preview);
    state.draft.name = "Сумка";
    state.draft.description = "Описание";
    state.draft.urls = "https://images.test/photo.jpg";
    state.reset();
    expect(state.draft).toEqual({
      name: "",
      description: "",
      urls: "",
      uploads: [],
    });
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
    scopes.splice(0).forEach((scope) => scope.stop());
    expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });
});
