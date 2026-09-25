import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from daily_arxiv.incremental import finalize, prepare, read_jsonl


def write(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


class IncrementalMergeTest(unittest.TestCase):
    def test_prepare_only_emits_unseen_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing.jsonl"
            history = root / "history.jsonl"
            fetched = root / "fetched.jsonl"
            merged = root / "merged.jsonl"
            new = root / "new.jsonl"
            write(existing, [{"id": "today"}])
            write(history, [{"id": "old"}])
            write(fetched, [{"id": "old"}, {"id": "today"}, {"id": "new"}])

            prepare(Namespace(
                existing_raw=existing,
                history=[history],
                fetched=fetched,
                output_raw=merged,
                output_new=new,
            ))

            self.assertEqual([item["id"] for item in read_jsonl(new)], ["new"])
            self.assertEqual(
                [item["id"] for item in read_jsonl(merged)],
                ["today", "new"],
            )

    def test_finalize_preserves_previous_filtered_results(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing-ai.jsonl"
            new = root / "new-ai.jsonl"
            output = root / "all-ai.jsonl"
            write(existing, [{"id": "a", "AI": {"score": 8}}])
            write(new, [{"id": "b", "AI": {"score": 9}}])

            finalize(Namespace(
                existing_enhanced=existing,
                new_enhanced=new,
                output_enhanced=output,
            ))

            self.assertEqual([item["id"] for item in read_jsonl(output)], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
