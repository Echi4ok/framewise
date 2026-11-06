import type {
  Analysis,
  Feature,
  Photo,
  Product,
  ProductSummary,
  Suggestion,
} from "../types";
import { post, request } from "./http";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isSummary(value: unknown): value is ProductSummary {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.name === "string"
  );
}

function isPhoto(value: unknown): value is Photo {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.url === "string" &&
    typeof value.width === "number" &&
    value.width > 0 &&
    typeof value.height === "number" &&
    value.height > 0
  );
}

function isProduct(value: unknown): value is Product {
  return (
    isSummary(value) &&
    "description" in value &&
    typeof value.description === "string" &&
    "images" in value &&
    Array.isArray(value.images) &&
    value.images.every(isPhoto)
  );
}

function isBox(value: unknown): value is Feature["bbox"] {
  if (!Array.isArray(value) || value.length !== 4) return false;
  if (
    !value.every(
      (coordinate) =>
        Number.isInteger(coordinate) && coordinate >= 0 && coordinate <= 1000,
    )
  )
    return false;
  return value[0] < value[2] && value[1] < value[3];
}

function isFeature(value: unknown): value is Feature {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.image_id === "string" &&
    typeof value.description === "string" &&
    isBox(value.bbox)
  );
}

function invalidResponse(): never {
  throw new Error("Сервер вернул некорректные данные. Повторите попытку.");
}

function productResponse(value: unknown): Product {
  if (!isProduct(value)) return invalidResponse();
  if (!value.images.length)
    throw new Error("У этого товара нет фотографий. Выберите другой товар.");
  return value;
}

export interface ManualProductInput {
  name: string;
  description: string;
  urls: string[];
  files: File[];
}

export const productService = {
  async list(signal: AbortSignal): Promise<ProductSummary[]> {
    const value = await request("/api/products", { signal });
    if (!Array.isArray(value) || !value.every(isSummary))
      return invalidResponse();
    return value;
  },

  async get(id: string, signal: AbortSignal): Promise<Product> {
    return productResponse(
      await request(`/api/products/${encodeURIComponent(id)}`, { signal }),
    );
  },

  async create(
    input: ManualProductInput,
    signal: AbortSignal,
  ): Promise<Product> {
    const form = new FormData();
    form.set("name", input.name);
    form.set("description", input.description);
    form.set("urls", JSON.stringify(input.urls));
    input.files.forEach((file) => form.append("files", file));
    return productResponse(
      await request(
        "/api/products/manual",
        {
          method: "POST",
          body: form,
          signal,
        },
        70_000,
      ),
    );
  },

  async suggest(product: Product, signal: AbortSignal): Promise<Suggestion> {
    const imageIds = product.images.map((photo) => photo.id);
    const value = await post(
      "/api/suggest",
      { product_id: product.id, image_ids: imageIds },
      signal,
    );
    if (
      !isRecord(value) ||
      !Array.isArray(value.selected_image_ids) ||
      !value.selected_image_ids.length ||
      typeof value.reason !== "string" ||
      !value.selected_image_ids.every(
        (id) => typeof id === "string" && imageIds.includes(id),
      )
    )
      return invalidResponse();
    return {
      selected_image_ids: value.selected_image_ids,
      reason: value.reason,
    };
  },

  async analyze(
    productId: string,
    imageIds: string[],
    signal: AbortSignal,
  ): Promise<Analysis> {
    const value = await post(
      "/api/analyze",
      { product_id: productId, image_ids: imageIds },
      signal,
    );
    if (
      !isRecord(value) ||
      !Array.isArray(value.features) ||
      !value.features.length ||
      !value.features.every(isFeature) ||
      !value.features.every((feature) => imageIds.includes(feature.image_id))
    )
      return invalidResponse();
    return { features: value.features };
  },
};

export type ProductService = typeof productService;
