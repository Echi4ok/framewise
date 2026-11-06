"""Small, reproducible development evaluation against an OpenAI-compatible VLM.

Run serially with no other traffic to the endpoint. This is a development set,
not a held-out benchmark. Raw model output is retained before any validation.
"""

import argparse
import base64
import csv
import hashlib
import io
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((PROJECT / "evaluation/fixtures/cases.json").read_text(encoding="utf-8-sig"))
COLORS = ["#00a6b5", "#e555c9", "#e3a600", "#36a23a", "#e45431"]


def canonical_image(relative_path, max_side=1600):
    with Image.open(PROJECT / relative_path) as source:
        photo = ImageOps.exif_transpose(source).convert("RGB")
    photo.thumbnail((max_side, max_side))
    return photo


def image_part(image):
    encoded = io.BytesIO()
    image.save(encoded, format="JPEG", quality=90)
    url = "data:image/jpeg;base64," + base64.b64encode(encoded.getvalue()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": url}}


def input_metadata(images):
    metadata = []
    for entry in images:
        photo = canonical_image(entry["path"])
        encoded = io.BytesIO()
        photo.save(encoded, format="JPEG", quality=90)
        metadata.append({"image_id": entry["image_id"], "path": entry["path"], "source_sha256": hashlib.sha256((PROJECT / entry["path"]).read_bytes()).hexdigest(), "canonical_jpeg_sha256": hashlib.sha256(encoded.getvalue()).hexdigest(), "canonical_size": [photo.width, photo.height], "jpeg_quality": 90})
    return metadata


def sent_image_hashes(body):
    hashes = []
    for message in body["messages"]:
        if not isinstance(message["content"], list):
            continue
        for part in message["content"]:
            if part["type"] == "image_url":
                image_bytes = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
                hashes.append(hashlib.sha256(image_bytes).hexdigest())
    return hashes


def schema(operation, image_ids, letter_selection=False):
    image_id = {"type": "string", "enum": image_ids}
    box = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 1000}, "minItems": 4, "maxItems": 4}
    if operation == "ground":
        item = {"type": "object", "properties": {"target_id": {"type": "string"}, "image_id": image_id, "bbox": box}, "required": ["target_id", "image_id", "bbox"], "additionalProperties": False}
        properties = {"detections": {"type": "array", "items": item}}
    elif operation == "suggest":
        key = "selected_labels" if letter_selection else "selected_image_ids"
        selected_item = {"type": "string", "enum": [chr(65 + index) for index in range(len(image_ids))]} if letter_selection else image_id
        properties = {key: {"type": "array", "items": selected_item, "minItems": 1, "maxItems": 4}, "reason": {"type": "string"}}
    else:
        item = {"type": "object", "properties": {"image_id": image_id, "description": {"type": "string"}, "bbox": box}, "required": ["image_id", "description", "bbox"], "additionalProperties": False}
        properties = {"status": {"type": "string", "enum": ["ok", "insufficient_evidence"]}, "features": {"type": "array", "items": item, "maxItems": 5}}
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def load_catalog():
    with (PROJECT / "data/products.csv").open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file, delimiter=";")
        rows = list(reader)
    if rows and len(rows[0]) == 1:
        with (PROJECT / "data/products.csv").open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
    return rows


def catalog_text(product_id):
    for row in load_catalog():
        if product_id in row.values():
            return json.dumps(row, ensure_ascii=False)
    return "Product ID " + product_id


def target_name(product_id):
    for row in load_catalog():
        if product_id == row.get("product_id"):
            return row["name"]
    return ""


def contact_sheet(photos, letter_selection=True):
    columns = min(4, len(photos))
    cell_width, cell_height = 224, 250
    sheet = Image.new("RGB", (columns * cell_width, math.ceil(len(photos) / columns) * cell_height), "#f1f1ed")
    draw = ImageDraw.Draw(sheet)
    for index, photo in enumerate(photos.values()):
        x, y = index % columns * cell_width, index // columns * cell_height
        thumbnail = ImageOps.contain(photo, (cell_width - 12, cell_height - 38))
        sheet.paste(thumbnail, (x + (cell_width - thumbnail.width) // 2, y + 30 + (cell_height - 38 - thumbnail.height) // 2))
        label = chr(65 + index) if letter_selection else str(index + 1)
        draw.text((x + 10, y + 8), f"PHOTO {label}", fill="black")
    return sheet


def cases():
    cap, suitcase, nike, demix = FIXTURES["cases"]
    gallery = [{"image_id": path.stem, "path": path.relative_to(PROJECT).as_posix()} for path in sorted((PROJECT / "data/images").glob(demix["product_id"] + "_*.jpg"), key=lambda path: int(path.stem.rsplit("_", 1)[1]))]
    largest_gallery = [{"image_id": path.stem, "path": path.relative_to(PROJECT).as_posix()} for path in sorted((PROJECT / "data/images").glob("33578610299_*.jpg"), key=lambda path: int(path.stem.rsplit("_", 1)[1]))]
    jacket = [{"image_id": f"42153320299_{number}", "path": f"data/images/42153320299_{number}.jpg"} for number in [1, 3]]
    controls = PROJECT / "evaluation/controls"
    controls.mkdir(exist_ok=True)
    Image.new("RGB", (512, 512), "white").save(controls / "blank.jpg")
    return [
        ("cap-single", cap, [cap["images"][2]], "analyze"),
        ("cap-multi", cap, cap["images"], "analyze"),
        ("suitcase-multi", suitcase, suitcase["images"], "analyze"),
        ("nike-conflict", nike, nike["images"][:2], "analyze"),
        ("demix-annotations", demix, demix["images"], "analyze"),
        ("nike-select", nike, nike["images"], "suggest"),
        ("demix-gallery-select", demix, gallery, "suggest"),
        ("largest-gallery-select", {"product_id": "33578610299"}, largest_gallery, "suggest"),
        ("negative-blank", {"product_id": "blank"}, [{"image_id": "blank", "path": "evaluation/controls/blank.jpg"}], "analyze"),
        ("negative-chart", nike, [nike["images"][2]], "analyze"),
        ("target-jacket", {"product_id": "42153320299"}, jacket, "analyze"),
    ]


def build_request(name, fixture, images, operation, variant, model, include_catalog=True, name_only=False, omit_ocr=False):
    photos = {entry["image_id"]: canonical_image(entry["path"]) for entry in images}
    if variant == "plain":
        prompt = "Analyze the product photos. Find 3-5 product features. Write short Russian descriptions with bounding boxes normalized 0..1000 [x1,y1,x2,y2] and exact image_id. Return status and features as JSON."
        if operation == "suggest":
            prompt = "Select 1-4 informative complementary product photos. Return selected_image_ids and a short Russian reason as JSON."
    else:
        prompt = (PROJECT / f"backend/app/prompts/{operation}.txt").read_text(encoding="utf-8")
    if omit_ocr and operation == "analyze":
        prompt += "\nDo not transcribe any letters, words, names or numbers from the photographs. Describe only the placement, color, shape and visible construction of text/logos/illustrations. Never quote or guess the content of text. Prefer physical construction details such as mesh, seams, edging and closures."
    parts = [{"type": "text", "text": "Inspect the supplied images."}]
    if include_catalog:
        parts.append({"type": "text", "text": "Catalog reference data:\n" + catalog_text(fixture["product_id"])})
    if name_only:
        parts.append({"type": "text", "text": "Intended target product name (only identifies which object to inspect, never evidence of a visible attribute): " + target_name(fixture["product_id"]) + ". Describe only features of that target object, excluding other outfit items. Photos remain the sole evidence even if this name conflicts with their appearance."})
    if operation == "suggest":
        letter_selection = variant == "improved"
        sheet = contact_sheet(photos, letter_selection)
        mapping = {"available_labels": [chr(65 + index) for index in range(len(photos))]} if letter_selection else {f"PHOTO {index + 1}": image_id for index, image_id in enumerate(photos)}
        parts.extend([{"type": "text", "text": json.dumps(mapping)}, image_part(sheet)])
    else:
        for image_id, photo in photos.items():
            parts.extend([{"type": "text", "text": f"image_id={image_id}"}, image_part(photo)])
    body = {"model": model, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": parts}], "temperature": 0.1, "seed": 42, "max_tokens": 1800, "response_format": {"type": "json_schema", "json_schema": {"name": operation, "strict": True, "schema": schema(operation, list(photos), operation == "suggest" and variant == "improved")}}}
    return body, photos, prompt


def validate(result, image_ids, operation):
    if operation == "suggest":
        chosen = result["selected_image_ids"]
        return 1 <= len(chosen) <= 4 and len(chosen) == len(set(chosen)) and set(chosen) <= set(image_ids)
    if operation == "ground":
        features = result["detections"]
    else:
        features = result["features"]
        if result["status"] == "insufficient_evidence":
            return features == []
        if not 3 <= len(features) <= 5:
            return False
        descriptions = [" ".join(feature["description"].casefold().split()) for feature in features]
        if len(descriptions) != len(set(descriptions)):
            return False
        regions = [(feature["image_id"], tuple(feature["bbox"])) for feature in features]
        if len(regions) != len(set(regions)):
            return False
    for feature in features:
        x1, y1, x2, y2 = feature["bbox"]
        if feature["image_id"] not in image_ids:
            return False
        if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
            return False
    return True


def overlay(photos, result, directory):
    for index, feature in enumerate(result.get("features", result.get("detections", []))):
        photo = photos[feature["image_id"]]
        x1, y1, x2, y2 = feature["bbox"]
        coordinates = [x1 * photo.width / 1000, y1 * photo.height / 1000, x2 * photo.width / 1000, y2 * photo.height / 1000]
        draw = ImageDraw.Draw(photo)
        color = COLORS[index % len(COLORS)]
        draw.rectangle(coordinates, outline=color, width=max(2, photo.width // 300))
        draw.rectangle([coordinates[0], coordinates[1], coordinates[0] + 24, coordinates[1] + 22], fill=color)
        draw.text((coordinates[0] + 5, coordinates[1] + 4), str(index + 1), fill="black")
    for image_id, photo in photos.items():
        photo.thumbnail((850, 850))
        photo.save(directory / f"{image_id}.jpg", quality=90)


def call(endpoint, body):
    request = urllib.request.Request(endpoint.rstrip("/") + "/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=240) as response:
        payload = json.load(response)
    return payload, round(time.monotonic() - started, 3)


def iou(first, second):
    intersection = max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(0, min(first[3], second[3]) - max(first[1], second[1]))
    area_first = (first[2] - first[0]) * (first[3] - first[1])
    area_second = (second[2] - second[0]) * (second[3] - second[1])
    return intersection / (area_first + area_second - intersection)


def ground_request(fixture, model):
    photos = {}
    targets = []
    for entry in fixture["images"]:
        if not entry["bbox_references"]:
            continue
        photos[entry["image_id"]] = canonical_image(entry["path"])
        for reference in entry["bbox_references"]:
            targets.append({"target_id": f"target-{len(targets) + 1}", "image_id": entry["image_id"], "label": reference["label"], "reference_bbox": reference["xyxy"]})
    public_targets = [{key: value for key, value in target.items() if key != "reference_bbox"} for target in targets]
    prompt = "Locate precisely each requested visible detail in its specified image. Return JSON with detections containing target_id, exact image_id and bbox [x1,y1,x2,y2] integers normalized to 0..1000 for that entire image. Use tight boxes. The targets are " + json.dumps(public_targets)
    parts = [{"type": "text", "text": prompt}]
    for image_id, photo in photos.items():
        parts.extend([{"type": "text", "text": f"image_id={image_id}"}, image_part(photo)])
    body = {"model": model, "messages": [{"role": "user", "content": parts}], "temperature": 0.1, "seed": 42, "max_tokens": 1200, "response_format": {"type": "json_schema", "json_schema": {"name": "ground", "strict": True, "schema": schema("ground", list(photos))}}}
    return body, photos, prompt, targets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3-vl:4b-instruct")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11436/v1")
    parser.add_argument("--variant", choices=["plain", "improved"], default="improved")
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--label")
    parser.add_argument("--task", choices=["features", "ground"], default="features")
    parser.add_argument("--no-catalog", action="store_true")
    parser.add_argument("--name-only", action="store_true")
    parser.add_argument("--omit-ocr", action="store_true")
    args = parser.parse_args()
    label = args.label or args.model.replace(":", "-") + "-" + (args.variant if args.task == "features" else "ground")
    root = PROJECT / "evaluation/results" / label
    root.mkdir(parents=True, exist_ok=True)
    summary = []
    eval_cases = cases() if args.task == "features" else [(fixture["case_id"], fixture, fixture["images"], "ground") for fixture in FIXTURES["cases"][:3]]
    for name, fixture, images, operation in eval_cases:
        if args.cases and name not in args.cases:
            continue
        directory = root / name
        directory.mkdir(exist_ok=True)
        targets = []
        if operation == "ground":
            body, photos, prompt, targets = ground_request(fixture, args.model)
        else:
            body, photos, prompt = build_request(name, fixture, images, operation, args.variant, args.model, not args.no_catalog and not args.name_only, args.name_only, args.omit_ocr)
        row = {"case": name, "model": args.model, "variant": args.variant, "catalog_included": not args.no_catalog and not args.name_only if operation != "ground" else False, "prompt": prompt, "image_ids": list(photos), "endpoint": args.endpoint}
        row["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
        row["target_name_included"] = args.name_only
        row["input_images"] = input_metadata([entry for entry in images if entry["image_id"] in photos])
        row["sent_image_sha256"] = sent_image_hashes(body)
        row["user_texts"] = [part["text"] for part in body["messages"][-1]["content"] if part["type"] == "text"]
        try:
            payload, seconds = call(args.endpoint, body)
            (directory / "raw-response.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            raw = payload["choices"][0]["message"]["content"]
            row.update(seconds=seconds, usage=payload.get("usage"), finish_reason=payload["choices"][0]["finish_reason"], result=json.loads(raw))
            if operation == "suggest" and "selected_labels" in row["result"]:
                mapping = {chr(65 + index): image_id for index, image_id in enumerate(photos)}
                row["selection_mapping"] = mapping
                row["result"]["selected_image_ids"] = [mapping[label] for label in row["result"]["selected_labels"]]
            row["valid"] = validate(row["result"], photos, operation)
            if targets:
                predictions = {entry["target_id"]: entry for entry in row["result"]["detections"]}
                row["grounding"] = []
                for target in targets:
                    prediction = predictions.get(target["target_id"])
                    score = iou(target["reference_bbox"], prediction["bbox"]) if prediction and prediction["image_id"] == target["image_id"] else 0
                    row["grounding"].append({**target, "prediction": prediction, "iou": round(score, 4), "pass_iou_50": score >= 0.5})
            overlay(photos, row["result"], directory)
            if operation == "suggest":
                contact_sheet(photos, args.variant == "improved").save(directory / "contact-sheet.jpg", quality=90)
        except Exception as error:
            row["error"] = repr(error)
            row["valid"] = False
        (directory / "result.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append(row)
        printable_keys = ["case", "model", "seconds", "valid", "finish_reason", "error", "grounding"]
        print(json.dumps({key: row[key] for key in printable_keys if key in row}, ensure_ascii=False), flush=True)
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
