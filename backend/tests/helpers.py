import io

from PIL import Image

from app.schemas import AnalysisView, FeatureView, Suggestion


def image_bytes(color="red", size=(80, 120), mode="RGB", exif=None):
    output = io.BytesIO()
    image = Image.new(mode, size, color)
    options = {"exif": exif} if exif is not None else {}
    image.save(output, format="PNG" if mode == "RGBA" else "JPEG", **options)
    return output.getvalue()


class TestVision:
    async def suggest(self, product, photos):
        return Suggestion(selected_image_ids=[photos[0].id], reason="Clear overall view")

    async def analyze(self, product, photos):
        return AnalysisView(
            features=[
                FeatureView(
                    id=f"feature-{index}",
                    image_id=photos[0].id,
                    description=f"Visible detail {index}",
                    bbox=[index * 50, 10, index * 50 + 40, 100],
                )
                for index in range(1, 4)
            ]
        )


def completion_payload(content):
    return {
        "id": "test",
        "object": "chat.completion",
        "created": 0,
        "model": "test",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
    }
