"""Merge repeated arXiv scans without paying to analyse the same paper twice."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable


def read_jsonl(path: Path | None) -> list[dict]:
    if path is None or not path.exists():
        return []
    records: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if record.get("id"):
                records.append(record)
    return records


def merge_by_id(*groups: Iterable[dict]) -> list[dict]:
    """Keep stable ordering while allowing later records to refresh metadata."""
    merged: dict[str, dict] = {}
    for group in groups:
        for record in group:
            paper_id = record.get("id")
            if paper_id:
                merged[paper_id] = record
    return list(merged.values())


def write_jsonl(path: Path, records: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def prepare(args: argparse.Namespace) -> int:
    existing = read_jsonl(args.existing_raw)
    fetched = read_jsonl(args.fetched)
    historical_ids = {
        record["id"]
        for path in args.history
        for record in read_jsonl(path)
    }
    known_ids = {record["id"] for record in existing} | historical_ids
    new_records = [record for record in fetched if record["id"] not in known_ids]

    write_jsonl(args.output_raw, merge_by_id(existing, new_records))
    write_jsonl(args.output_new, new_records)
    print(
        f"增量扫描：本日已有 {len(existing)} 篇，本次抓到 {len(fetched)} 篇，"
        f"发现新论文 {len(new_records)} 篇"
    )
    return 0


def finalize(args: argparse.Namespace) -> int:
    existing = read_jsonl(args.existing_enhanced)
    newly_enhanced = read_jsonl(args.new_enhanced)
    merged = merge_by_id(existing, newly_enhanced)
    write_jsonl(args.output_enhanced, merged)
    print(
        f"AI 结果合并：保留已有 {len(existing)} 篇，"
        f"本次筛选后新增 {len(newly_enhanced)} 篇，共 {len(merged)} 篇"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--fetched", required=True, type=Path)
    prepare_parser.add_argument("--existing-raw", type=Path)
    prepare_parser.add_argument("--history", nargs="*", default=[], type=Path)
    prepare_parser.add_argument("--output-raw", required=True, type=Path)
    prepare_parser.add_argument("--output-new", required=True, type=Path)
    prepare_parser.set_defaults(func=prepare)

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--existing-enhanced", type=Path)
    finalize_parser.add_argument("--new-enhanced", required=True, type=Path)
    finalize_parser.add_argument("--output-enhanced", required=True, type=Path)
    finalize_parser.set_defaults(func=finalize)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
