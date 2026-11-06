"""Revalidate saved exploratory runs and add input-recipe hashes for audit.

No model calls are made. Reconstructed hashes are explicitly marked because
earlier harness versions recorded the recipe and source IDs, not these hashes.
"""

import base64
import hashlib
import json

import run_eval


def main():
    project = run_eval.PROJECT
    fixtures = {name: (images, operation) for name, _, images, operation in run_eval.cases()}
    for fixture in run_eval.FIXTURES["cases"][:3]:
        fixtures[fixture["case_id"]] = (fixture["images"], "ground")
    for series in sorted((project / "evaluation/results").iterdir()):
        if not series.is_dir():
            continue
        if series.name == "8b-second-pass":
            continue
        summary = []
        for path in sorted(series.glob("*/result.json")):
            row = json.loads(path.read_text(encoding="utf-8"))
            if row.get("target_name_included"):
                row["catalog_included"] = False
            if "result" not in row:
                summary.append(row)
                continue
            entries, operation = fixtures[row["case"]]
            entries = [entry for entry in entries if entry["image_id"] in row["image_ids"]]
            photos = {entry["image_id"]: run_eval.canonical_image(entry["path"]) for entry in entries}
            row["valid"] = run_eval.validate(row["result"], row["image_ids"], operation)
            row["prompt_sha256"] = hashlib.sha256(row["prompt"].encode()).hexdigest()
            if "input_images" not in row:
                row["input_images"] = run_eval.input_metadata(entries)
                row["hashes_reconstructed_from_recorded_recipe"] = True
                sent = list(photos.values())
                if operation == "suggest":
                    letter_selection = "selected_labels" in row["result"]
                    sent = [run_eval.contact_sheet(photos, letter_selection)]
                row["sent_image_sha256"] = []
                for photo in sent:
                    part = run_eval.image_part(photo)
                    content = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
                    row["sent_image_sha256"].append(hashlib.sha256(content).hexdigest())
            run_eval.overlay(photos, row["result"], path.parent)
            path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
            summary.append(row)
        (series / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
