"""Exercise the running app with real model calls and save each API response.

Install backend/requirements.txt, then run this script against a running app.
The checks validate the API contract. Visual accuracy needs a human review.
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.schemas import AnalysisView, ModelAnalysis, ProductView, Suggestion  # noqa: E402


class Verification:
    def __init__(self, base_url: str, output: Path):
        self.output = output
        output.mkdir(parents=True, exist_ok=True)
        self.report = {
            "base_url": base_url,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "Real API/model calls; response contracts only. Review boxes and descriptions visually.",
            "checks": [],
        }
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=360, trust_env=False)

    def save(self):
        (self.output / "report.json").write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")

    def request(self, name, method, path, *, expected=(200,), schema=None, image_ids=None, binary=False, **kwargs):
        entry = {"name": name, "method": method, "path": path, "passed": False}
        if "json" in kwargs:
            entry["request_json"] = kwargs["json"]
        if "data" in kwargs:
            entry["request_fields"] = kwargs["data"]
        started = time.monotonic()
        result = None
        try:
            response = self.client.request(method, path, **kwargs)
            entry["status_code"] = response.status_code
            entry["content_type"] = response.headers.get("content-type", "")
            if binary:
                entry["response_bytes"] = len(response.content)
                entry["response_sha256"] = hashlib.sha256(response.content).hexdigest()
                result = response.content
            else:
                entry["raw_response"] = response.text
                result = response.json()
            if response.status_code not in expected:
                raise ValueError(f"Expected HTTP {expected}, received {response.status_code}")
            if binary and (not response.content or entry["content_type"].split(";")[0] != "image/jpeg"):
                raise ValueError("Canonical media must be a nonempty JPEG")
            if schema and response.status_code in (200, 201):
                value = schema.model_validate(result)
                if isinstance(value, AnalysisView):
                    ModelAnalysis(status="ok", features=[feature.model_dump(exclude={"id"}) for feature in value.features])
                    if any(feature.image_id not in image_ids for feature in value.features):
                        raise ValueError("Analysis refers to a photograph outside the requested set")
                if isinstance(value, Suggestion) and not set(value.selected_image_ids).issubset(image_ids):
                    raise ValueError("Suggestion refers to a photograph outside the requested set")
            entry["passed"] = True
        except (httpx.HTTPError, ValueError, ValidationError) as error:
            entry["error"] = str(error)
            result = None
        entry["seconds"] = round(time.monotonic() - started, 2)
        self.report["checks"].append(entry)
        self.save()
        print(f"{name}: HTTP {entry.get('status_code', 'unavailable')}, {entry['seconds']} s, {'PASS' if entry['passed'] else 'FAIL'}", flush=True)
        return result

    def analyze(self, name, product, image_ids):
        return self.request(
            name, "POST", "/api/analyze",
            json={"product_id": product["id"], "image_ids": image_ids},
            schema=AnalysisView, image_ids=set(image_ids),
        )

    def run(self):
        self.request("health", "GET", "/api/health")
        self.request("catalog", "GET", "/api/products")
        cap = self.request("catalog_cap", "GET", "/api/products/40016330299", schema=ProductView)
        suitcase = self.request("catalog_suitcase", "GET", "/api/products/43358020299", schema=ProductView)

        if cap:
            image_ids = [image["id"] for image in cap["images"]]
            self.request("suggest_five_photos", "POST", "/api/suggest", json={"product_id": cap["id"], "image_ids": image_ids}, schema=Suggestion, image_ids=set(image_ids))
            single_id = "catalog-40016330299-4"
            self.analyze("analyze_single_photo", cap, [single_id])
            four_ids = [image_ids[index] for index in (0, 1, 3, 4)]
            self.analyze("reanalyze_four_photos", cap, four_ids)
            self.request("reject_empty_selection", "POST", "/api/analyze", json={"product_id": cap["id"], "image_ids": []}, expected=(422,))

        if suitcase:
            photo = suitcase["images"][0]
            content = self.request("download_manual_source", "GET", photo["url"], binary=True)
            if content:
                manual = self.request(
                    "manual_upload", "POST", "/api/products/manual", expected=(201,), schema=ProductView,
                    data={"name": "Чемодан", "description": "Товар, добавленный вручную для проверки приложения.", "urls": "[]"},
                    files=[("files", ("suitcase.jpg", content, "image/jpeg"))],
                )
                if manual:
                    self.request("manual_canonical_media", "GET", manual["images"][0]["url"], binary=True)
                    self.analyze("analyze_manual_upload", manual, [image["id"] for image in manual["images"]])

        url_product = self.request(
            "public_url_import", "POST", "/api/products/manual", expected=(201,), schema=ProductView,
            data={"name": "Тушь для ресниц", "description": "Пример загрузки по прямой публичной ссылке.", "urls": '["https://cdn.dummyjson.com/product-images/beauty/essence-mascara-lash-princess/1.webp"]'},
        )
        if url_product:
            self.request("public_url_canonical_media", "GET", url_product["images"][0]["url"], binary=True)
            self.analyze("analyze_public_url", url_product, [image["id"] for image in url_product["images"]])
        self.request("reject_private_url", "POST", "/api/products/manual", data={"name": "Проверка адреса", "urls": '["http://127.0.0.1/private.jpg"]'}, expected=(422,))

        self.report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        self.report["passed"] = all(check["passed"] for check in self.report["checks"])
        self.save()
        self.client.close()
        return self.report["passed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="Running app URL, including the frontend API proxy")
    parser.add_argument("--output", type=Path, default=Path("verification/api"), help="Directory for raw response and timing report")
    args = parser.parse_args()
    verification = Verification(args.base_url, args.output)
    passed = verification.run()
    print(f"Saved report: {(args.output / 'report.json').resolve()}")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
