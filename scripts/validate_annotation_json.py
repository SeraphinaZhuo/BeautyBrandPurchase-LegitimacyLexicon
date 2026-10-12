#!/usr/bin/env python3
"""Dependency-free structural checks for BPLL annotation JSON files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


V = {"V1", "V2", "V3", "V4"}
R = {"R1", "R2", "R3", "R4", "R5"}
O = {"O1", "O2", "O3", "O4", "O5", "O6", "O7"}
T = {f"T{i}" for i in range(1, 8)}
MR = {f"MR{i}" for i in range(1, 8)}
MX = {f"MX{i}" for i in range(1, 9)}
D = {f"D{i}" for i in range(1, 5)}
CONF = {"high", "medium", "low"}
REQUIRED = {
    "record_id", "target_brand", "voice_code", "voice_evidence",
    "relationship_code", "relationship_evidence", "outcome_code",
    "outcome_evidence", "transition_codes", "retention_mechanism_codes",
    "exit_mechanism_codes", "discourse_codes", "multi_label_evidence",
    "annotation_confidence", "uncertainty_note", "e3_hypothesis_note",
}


def load_json(path: Path):
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("files", type=Path, nargs="+")
    args = parser.parse_args()

    load_json(args.schema)  # confirms that the frozen schema is valid JSON and exists
    failed = False
    for path in args.files:
        try:
            payload = load_json(path)
            if payload.get("schema_version") != "2.0":
                raise ValueError("schema_version must be 2.0")
            if not isinstance(payload.get("annotations"), list) or not payload["annotations"]:
                raise ValueError("annotations must be a non-empty array")
            record_ids = [item["record_id"] for item in payload["annotations"]]
            if len(record_ids) != len(set(record_ids)):
                raise ValueError("duplicate record_id")
            for item in payload["annotations"]:
                missing = REQUIRED - set(item)
                extra = set(item) - REQUIRED
                if missing or extra:
                    raise ValueError(f"{item.get('record_id')}: missing={sorted(missing)}, extra={sorted(extra)}")
                if item["target_brand"] not in {"资生堂", "SK-II", "花王"}:
                    raise ValueError(f"{item['record_id']}: invalid target_brand")
                for field, allowed in [("voice_code", V), ("relationship_code", R), ("outcome_code", O), ("annotation_confidence", CONF)]:
                    if item[field] not in allowed:
                        raise ValueError(f"{item['record_id']}: invalid {field}={item[field]}")
                arrays = [
                    ("transition_codes", T), ("retention_mechanism_codes", MR),
                    ("exit_mechanism_codes", MX), ("discourse_codes", D),
                ]
                selected = set()
                for field, allowed in arrays:
                    values = item[field]
                    if not isinstance(values, list) or len(values) != len(set(values)) or not set(values) <= allowed:
                        raise ValueError(f"{item['record_id']}: invalid {field}")
                    selected.update(values)
                evidence_codes = [entry.get("code") for entry in item["multi_label_evidence"]]
                if len(evidence_codes) != len(set(evidence_codes)) or set(evidence_codes) != selected:
                    raise ValueError(f"{item['record_id']}: multi-label evidence does not match selected codes")
                for entry in item["multi_label_evidence"]:
                    if not entry.get("quote") or entry.get("evidence_level") not in {"E1", "E2"}:
                        raise ValueError(f"{item['record_id']}: invalid multi-label evidence")
            print(f"PASS\t{path}\tannotations={len(record_ids)}")
        except Exception as exc:  # report each file without hiding later failures
            failed = True
            print(f"FAIL\t{path}\t{exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

