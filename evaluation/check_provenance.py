"""Verify common-case inputs for the frozen-prompt model comparison."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    four = json.loads((ROOT / "results/4b-production-final/summary.json").read_text(encoding="utf-8"))
    eight = json.loads((ROOT / "results/8b-production-final/summary.json").read_text(encoding="utf-8"))
    by_case = {row["case"]: row for row in eight}
    checks = []
    for row in four:
        other = by_case[row["case"]]
        checks.append({
            "case": row["case"],
            "same_system_prompt": row["prompt_sha256"] == other["prompt_sha256"],
            "same_sent_image_bytes": row["sent_image_sha256"] == other["sent_image_sha256"],
            "same_image_id_order": row["image_ids"] == other["image_ids"],
        })
    if not all(all(row[key] for key in ["same_system_prompt", "same_sent_image_bytes", "same_image_id_order"]) for row in checks):
        raise ValueError("The comparison input provenance differs")
    report = {
        "matched_cases": checks,
        "all_equal": True,
        "scope": "System prompt, ordered IDs and JPEG payload hashes match. The final application's name-only user context is a later change. Earlier4B hashes are explicitly reconstructed from their recorded recipe.",
        "runtime": {"name": "llama.cpp", "release": "b12124", "backend": "CUDA13.4", "context_tokens": 12288, "parallel_slots": 1, "image_min_tokens": 1024, "image_max_tokens": 1536, "gpu": "NVIDIA RTX5070 12GB", "driver": "610.88"},
        "model_blobs": {
            "4b": {"model_sha256": "3a859c4dca6883593e389a08987f04762f2a374d475cabc1538360473a72b1da", "projector_sha256": "70ac570fd36b65a64fbb99883c34d5196368c1cf8f63d8402802a34a0ed2b363", "model_bytes": 2497888288, "projector_bytes": 839325760},
            "8b": {"model_sha256": "a0c1f7c1356ebc4135b6d12f726c18487669f1a7099156323d0f7b4ca91aca99", "projector_sha256": "85aa79666ee786bcc4fe69ac343db5ad468b71ad6272c12bfd8dfb29a8bdf18a", "model_bytes": 5028391520, "projector_bytes": 1162568672},
        },
    }
    (ROOT / "provenance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"All {len(checks)} matched-case prompts and image payloads agree.")


if __name__ == "__main__":
    main()
