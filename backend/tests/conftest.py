import pytest

from app.config import Settings
from app.store import Store
from tests.helpers import image_bytes


@pytest.fixture
def settings(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "products.csv").write_text(
        "product_id,name,description\n100,Test coat,Reference description\n200,Other product,Other description\n",
        encoding="utf-8",
    )
    (tmp_path / "images.csv").write_text(
        "product_id,image_order,image_url\n100,1,https://example.com/a.jpg\n100,2,https://example.com/b.jpg\n200,1,https://example.com/c.jpg\n",
        encoding="utf-8",
    )
    for name, color in [("100_1.jpg", "red"), ("100_2.jpg", "blue"), ("200_1.jpg", "green")]:
        (tmp_path / "images" / name).write_bytes(image_bytes(color))
    return Settings(data_dir=tmp_path, _env_file=None)


@pytest.fixture
def store(settings):
    value = Store(settings)
    value.load_catalog()
    return value
