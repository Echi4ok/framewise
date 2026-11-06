export interface Photo {
  id: string;
  url: string;
  width: number;
  height: number;
}

export interface ProductSummary {
  id: string;
  name: string;
}

export interface Product extends ProductSummary {
  description: string;
  images: Photo[];
}

export interface Feature {
  id: string;
  image_id: string;
  description: string;
  bbox: [number, number, number, number];
}

export interface Analysis {
  features: Feature[];
}

export interface Suggestion {
  selected_image_ids: string[];
  reason: string;
}

export interface Upload {
  key: number;
  file: File;
  preview: string;
}

export interface ProductDraft {
  name: string;
  description: string;
  urls: string;
  uploads: Upload[];
}

export interface WorkflowStatus {
  error: string;
  notice: string;
  loading: string;
  seconds: number;
}
