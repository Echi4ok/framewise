"""Bounded second-pass experiment. This does not change the app pipeline."""

import hashlib
import json

import run_eval


def refine(case_name):
    source_path = run_eval.PROJECT / "evaluation/results/8b-production-final" / case_name / "result.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    original = source["result"]["features"]
    fixture = next(case for case in run_eval.FIXTURES["cases"] if case["product_id"] == source["image_ids"][0].split("_")[0])
    images = [entry for entry in fixture["images"] if entry["image_id"] in source["image_ids"]]
    photos = {entry["image_id"]: run_eval.canonical_image(entry["path"]) for entry in images}
    prompt = (
        "Verify each proposed feature against the supplied product photographs. "
        "The product name only identifies the intended object. Pixels are the sole evidence. "
        "For each feature_index, keep the exact image_id. Preserve the existing description by referring to its index. "
        "Set supported=false if the entire description is not directly supported, if it describes a marketing banner instead of a physical product detail, "
        "or if it repeats the same feature from another view. For repeats retain only the clearest one. "
        "Uncertain OCR transcription, invented names, materials and functional qualities are unsupported. "
        "For supported features, return a fresh tight bbox around the physical detail, [x1,y1,x2,y2] integers 0..1000 for that single photo. "
        "Do not enclose unrelated parts merely to make a large rectangle. Return an entry for every supplied feature index and a brief reason."
    )
    targets = [{"feature_index": index, "image_id": item["image_id"], "description": item["description"]} for index, item in enumerate(original, 1)]
    content = [{"type": "text", "text": json.dumps({"target_product_name": run_eval.target_name(fixture["product_id"]), "proposed_features": targets}, ensure_ascii=False)}]
    for image_id, photo in photos.items():
        content.extend([{"type": "text", "text": f"image_id={image_id}"}, run_eval.image_part(photo)])
    box = {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 1000}, "minItems": 4, "maxItems": 4}
    item = {"type": "object", "properties": {"feature_index": {"type": "integer", "minimum": 1, "maximum": len(original)}, "image_id": {"type": "string", "enum": list(photos)}, "supported": {"type": "boolean"}, "bbox": box, "reason": {"type": "string"}}, "required": ["feature_index", "image_id", "supported", "bbox", "reason"], "additionalProperties": False}
    schema = {"type": "object", "properties": {"verified_features": {"type": "array", "items": item, "minItems": len(original), "maxItems": len(original)}}, "required": ["verified_features"], "additionalProperties": False}
    body = {"model": "qwen3-vl:8b-instruct", "temperature": 0.1, "seed": 42, "max_tokens": 1800, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": content}], "response_format": {"type": "json_schema", "json_schema": {"name": "verify", "strict": True, "schema": schema}}}
    payload, seconds = run_eval.call("http://127.0.0.1:11436/v1", body)
    result = json.loads(payload["choices"][0]["message"]["content"])
    directory = run_eval.PROJECT / "evaluation/results/8b-second-pass" / case_name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "raw-response.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    row = {"case": case_name, "model": body["model"], "prompt": prompt, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "source_run": str(source_path.relative_to(run_eval.PROJECT)), "seconds": seconds, "original_features": original, "target_name": run_eval.target_name(fixture["product_id"]), "result": result, "usage": payload.get("usage")}
    refined = []
    for prediction in result["verified_features"]:
        index = prediction["feature_index"] - 1
        if prediction["image_id"] != original[index]["image_id"]:
            raise ValueError("Refinement changed an image ID")
        if prediction["supported"]:
            refined.append({**original[index], "bbox": prediction["bbox"]})
    row["retained_features"] = refined
    row["enough_for_three_feature_contract"] = len(refined) >= 3
    run_eval.overlay(photos, {"features": refined}, directory)
    (directory / "result.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"case": case_name, "seconds": seconds, "retained": len(refined), "result": result}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    for case_name in ["cap-multi", "demix-annotations"]:
        refine(case_name)
