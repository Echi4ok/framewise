from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import Photo, Product


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PhotoView(StrictModel):
    id: str
    url: str
    width: int
    height: int


class ProductView(StrictModel):
    id: str
    name: str
    description: str
    images: list[PhotoView]


class ProductSummary(StrictModel):
    id: str
    name: str


class PhotoRequest(StrictModel):
    product_id: str = Field(min_length=1, max_length=100)
    image_ids: list[str] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.image_ids)) != len(self.image_ids):
            raise ValueError("image_ids must be unique")
        return self


class Suggestion(StrictModel):
    selected_image_ids: list[str] = Field(min_length=1, max_length=4)
    reason: str = Field(min_length=1, max_length=700)

    @model_validator(mode="after")
    def unique_ids(self):
        if len(set(self.selected_image_ids)) != len(self.selected_image_ids):
            raise ValueError("selected_image_ids must be unique")
        return self


class SelectedLabels(StrictModel):
    selected_labels: list[Annotated[str, Field(pattern="^[A-Z]$")]] = Field(min_length=1, max_length=4)
    reason: str = Field(min_length=1, max_length=700)

    @model_validator(mode="after")
    def unique_labels(self):
        if len(set(self.selected_labels)) != len(self.selected_labels):
            raise ValueError("selected_labels must be unique")
        return self


Coordinate = Annotated[int, Field(strict=True, ge=0, le=1000)]


class GroundedFeature(StrictModel):
    image_id: str = Field(min_length=1)
    description: str = Field(min_length=3, max_length=350)
    bbox: list[Coordinate] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def positive_box(self):
        x1, y1, x2, y2 = self.bbox
        if x1 >= x2 or y1 >= y2:
            raise ValueError("bbox must have positive width and height")
        return self


class ModelAnalysis(StrictModel):
    status: Literal["ok", "insufficient_evidence"]
    features: list[GroundedFeature] = Field(max_length=5)

    @model_validator(mode="after")
    def check_result(self):
        if self.status == "ok" and not 3 <= len(self.features) <= 5:
            raise ValueError("successful analysis must contain 3 to 5 features")
        if self.status == "insufficient_evidence" and self.features:
            raise ValueError("insufficient_evidence requires an empty features array")
        descriptions = [" ".join(item.description.casefold().split()) for item in self.features]
        if len(descriptions) != len(set(descriptions)):
            raise ValueError("feature descriptions must be unique")
        regions = [(feature.image_id, tuple(feature.bbox)) for feature in self.features]
        if len(regions) != len(set(regions)):
            raise ValueError("features in the same image must not reuse the exact same bbox")
        return self


class FeatureView(GroundedFeature):
    id: str


class AnalysisView(StrictModel):
    features: list[FeatureView] = Field(min_length=3, max_length=5)


def photo_view(photo: Photo) -> PhotoView:
    return PhotoView(
        id=photo.id,
        url=f"/api/media/{photo.id}",
        width=photo.image.width,
        height=photo.image.height,
    )


def product_view(product: Product) -> ProductView:
    return ProductView(
        id=product.id,
        name=product.name,
        description=product.description,
        images=[photo_view(photo) for photo in product.images],
    )
