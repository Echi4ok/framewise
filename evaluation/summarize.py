"""Summarize the two frozen-prompt development series without model calls."""

import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANUAL = json.loads((ROOT / "manual-review.json").read_text(encoding="utf-8"))


def summarize_candidate(size):
    label = f"{size}b-production-final"
    rows = json.loads((ROOT / "results" / label / "summary.json").read_text(encoding="utf-8"))
    positive = [row for row in rows if row["case"] in ["cap-single", "cap-multi", "suitcase-multi", "nike-conflict", "demix-annotations"]]
    negatives = [row for row in rows if row["case"].startswith("negative-")]
    selections = [row for row in rows if row["case"].endswith("select")]
    grounding_rows = json.loads((ROOT / f"results/qwen3-vl-{size}b-instruct-ground/summary.json").read_text(encoding="utf-8"))
    targets = [target for row in grounding_rows for target in row["grounding"]]
    return {
        "series": label,
        "model": f"qwen3-vl:{size}b-instruct",
        "total_calls": len(rows),
        "first_response_contract_valid": sum(row["valid"] for row in rows),
        "positive_calls": len(positive),
        "positive_first_response_contract_valid": sum(row["valid"] for row in positive),
        "negative_controls": len(negatives),
        "negative_correct_abstentions": sum(row["result"]["status"] == "insufficient_evidence" for row in negatives),
        "selection_calls": len(selections),
        "selection_valid_ids": sum(row["valid"] for row in selections),
        "median_positive_seconds": round(statistics.median(row["seconds"] for row in positive), 3),
        "grounding_targets": len(targets),
        "grounding_iou_at_least_50": sum(target["pass_iou_50"] for target in targets),
        "grounding_mean_iou": round(statistics.mean(target["iou"] for target in targets), 4),
        "manual": MANUAL[label]["totals"],
    }


def main():
    report = {
        "date": "2026-11-05",
        "scope": "Small manually selected development set. Prompts were adjusted on these photos. First-response validation is measured before application repair. Manual labels are subjective. Fixed-target localization is a separate task from feature generation. Native llama.cpp timings depend on warmup and caches.",
        "candidates": [summarize_candidate(4), summarize_candidate(8)],
        "second_pass": {
            "cases": ["cap-multi", "demix-annotations"],
            "extra_seconds": [8.703, 9.641],
            "focused_boxes_before": 5,
            "focused_boxes_after": 5,
            "total_features": 8,
            "unsupported_claims_or_duplicates_rejected_by_model": 0,
            "adopted": False,
        },
        "name_only_exploration": {
            "cases_each_strategy": ["target-jacket", "nike-conflict"],
            "additional_name_only_control": "negative-chart",
            "observation": "Both strategies focused jacket. Name-only retained visible Nike details and correctly abstained on size chart that no-name analyzed as table. Product descriptions remained excluded.",
        },
        "ocr_ban_probe": {
            "case": "cap-multi",
            "observation": "Appended no-transcription instruction did not eliminate guessed tape text. No demonstrated improvement; not adopted.",
        },
    }
    (ROOT / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
