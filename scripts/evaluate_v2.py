#!/usr/bin/env python3
"""Compare a BPLL model run with a private reference JSON."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


SINGLE_FIELDS = ["voice_code", "relationship_code", "outcome_code"]
MULTI_FIELDS = [
    "transition_codes",
    "retention_mechanism_codes",
    "exit_mechanism_codes",
    "discourse_codes",
]


def load_annotations(path: Path):
    with path.open(encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    return {item["record_id"]: item for item in payload["annotations"]}


def prf(tp: int, fp: int, fn: int):
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
    return precision, recall, f1


def gwet_ac1(gold, guess):
    """Gwet's AC1 for two raters and nominal categories."""
    categories = sorted(set(gold) | set(guess))
    observed = sum(a == b for a, b in zip(gold, guess)) / len(gold)
    if len(categories) == 1:
        return 1.0
    marginal = Counter(gold + guess)
    probs = [marginal[item] / (2 * len(gold)) for item in categories]
    chance = sum(p * (1 - p) for p in probs) / (len(categories) - 1)
    return (observed - chance) / (1 - chance) if chance != 1 else 1.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--prediction", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    ref = load_annotations(args.reference)
    pred = load_annotations(args.prediction)
    if set(ref) != set(pred):
        missing = sorted(set(ref) - set(pred))
        extra = sorted(set(pred) - set(ref))
        raise SystemExit(f"record_id mismatch: missing={missing}, extra={extra}")

    report = {"n": len(ref), "single_label": {}, "multi_label": {}}
    for field in SINGLE_FIELDS:
        gold = [ref[key][field] for key in ref]
        guess = [pred[key][field] for key in ref]
        correct = sum(a == b for a, b in zip(gold, guess))
        report["single_label"][field] = {
            "agreement": correct / len(ref),
            "gwet_ac1": gwet_ac1(gold, guess),
            "correct": correct,
        }

    exit_tp = exit_fp = exit_fn = 0
    for key in ref:
        gold_exit = ref[key]["relationship_code"] == "R1" and ref[key]["outcome_code"] in {"O3", "O4"}
        pred_exit = pred[key]["relationship_code"] == "R1" and pred[key]["outcome_code"] in {"O3", "O4"}
        exit_tp += int(gold_exit and pred_exit)
        exit_fp += int((not gold_exit) and pred_exit)
        exit_fn += int(gold_exit and (not pred_exit))
    precision, recall, f1 = prf(exit_tp, exit_fp, exit_fn)
    report["derived_existing_customer_exit"] = {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": exit_tp,
        "fp": exit_fp,
        "fn": exit_fn,
    }

    for field in MULTI_FIELDS:
        tp = fp = fn = 0
        jaccards = []
        label_counts = Counter()
        for key in ref:
            gold = set(ref[key][field])
            guess = set(pred[key][field])
            tp += len(gold & guess)
            fp += len(guess - gold)
            fn += len(gold - guess)
            union = gold | guess
            jaccards.append(len(gold & guess) / len(union) if union else 1.0)
            label_counts.update(gold)
        precision, recall, f1 = prf(tp, fp, fn)
        report["multi_label"][field] = {
            "micro_precision": precision,
            "micro_recall": recall,
            "micro_f1": f1,
            "mean_jaccard": sum(jaccards) / len(jaccards),
            "reference_positive_counts": dict(sorted(label_counts.items())),
        }

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

