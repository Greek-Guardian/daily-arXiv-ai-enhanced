"""Fetch arXiv metadata for one or more historical submission dates."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
API_URL = "https://export.arxiv.org/api/query"
PAGE_SIZE = 500
MAX_RANGE_DAYS = 14


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--output-dir", default="data", type=Path)
    parser.add_argument("--force-fetch", action="store_true")
    return parser.parse_args()


def dates_between(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("结束日期不能早于开始日期")
    days = (end - start).days + 1
    if days > MAX_RANGE_DAYS:
        raise ValueError(f"单次最多补跑 {MAX_RANGE_DAYS} 天，当前选择了 {days} 天")
    return [start + timedelta(days=offset) for offset in range(days)]


def text(entry: ET.Element, tag: str) -> str:
    value = entry.findtext(tag, default="")
    return " ".join(value.split())


def entry_to_paper(entry: ET.Element) -> dict:
    entry_id = text(entry, f"{ATOM}id").rsplit("/", 1)[-1]
    paper_id = re.sub(r"v\d+$", "", entry_id)
    links = {
        link.attrib.get("title", link.attrib.get("rel", "")): link.attrib.get("href", "")
        for link in entry.findall(f"{ATOM}link")
    }
    return {
        "id": paper_id,
        "pdf": links.get("pdf", f"https://arxiv.org/pdf/{paper_id}"),
        "abs": f"https://arxiv.org/abs/{paper_id}",
        "authors": [text(author, f"{ATOM}name") for author in entry.findall(f"{ATOM}author")],
        "title": text(entry, f"{ATOM}title"),
        "categories": [node.attrib["term"] for node in entry.findall(f"{ATOM}category")],
        "comment": text(entry, f"{ARXIV}comment"),
        "summary": text(entry, f"{ATOM}summary"),
    }


def fetch_day(target: date, categories: list[str]) -> list[dict]:
    start_stamp = target.strftime("%Y%m%d0000")
    end_stamp = target.strftime("%Y%m%d2359")
    category_query = " OR ".join(f"cat:{category}" for category in categories)
    query = f"({category_query}) AND submittedDate:[{start_stamp} TO {end_stamp}]"
    papers: dict[str, dict] = {}
    offset = 0

    while True:
        params = {
                "search_query": query,
                "start": offset,
                "max_results": PAGE_SIZE,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
        }
        # export.arxiv.org rejects query strings where spaces are encoded as
        # '+'. Force RFC 3986 '%20' encoding instead of requests' default.
        request_url = f"{API_URL}?{urlencode(params, quote_via=quote)}"
        request = Request(
            request_url,
            headers={
                "User-Agent": (
                    "daily-arxiv-ai-enhanced/1.0 "
                    "(mailto:Greek-Guardian@users.noreply.github.com)"
                )
            },
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urlopen(request, timeout=60) as response:
                    root = ET.fromstring(response.read())
                break
            except (HTTPError, URLError, TimeoutError) as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(3 * (attempt + 1))
        else:  # pragma: no cover - defensive; the loop either breaks or raises.
            raise RuntimeError(f"arXiv API request failed: {last_error}")
        entries = root.findall(f"{ATOM}entry")
        total = int(root.findtext(f"{OPENSEARCH}totalResults", default="0"))
        for entry in entries:
            paper = entry_to_paper(entry)
            papers[paper["id"]] = paper
        offset += len(entries)
        if not entries or offset >= total:
            break
        time.sleep(3)

    return list(papers.values())


def main() -> int:
    args = parse_args()
    end = args.end_date or args.start_date
    try:
        targets = dates_between(args.start_date, end)
    except ValueError as exc:
        print(f"日期范围错误：{exc}", file=sys.stderr)
        return 2

    categories = [value.strip() for value in os.getenv("CATEGORIES", "cs.CV,cs.CL").split(",") if value.strip()]
    if not categories:
        print("CATEGORIES 不能为空", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    empty: list[str] = []
    ready: list[str] = []

    for index, target in enumerate(targets):
        if index:
            # arXiv asks API clients not to make back-to-back requests.
            time.sleep(3)
        output = args.output_dir / f"{target.isoformat()}.jsonl"
        if output.exists() and output.stat().st_size > 0 and not args.force_fetch:
            print(f"复用已有原始数据：{output}")
            ready.append(target.isoformat())
            continue
        try:
            print(f"从 arXiv API 回抓 {target.isoformat()}：{', '.join(categories)}")
            papers = fetch_day(target, categories)
            if not papers:
                empty.append(target.isoformat())
                print(f"{target.isoformat()} 没有匹配论文")
                continue
            with output.open("w", encoding="utf-8") as handle:
                for paper in papers:
                    handle.write(json.dumps(paper, ensure_ascii=False) + "\n")
            ready.append(target.isoformat())
            print(f"已保存 {len(papers)} 篇：{output}")
        except Exception as exc:
            failed.append(target.isoformat())
            print(f"{target.isoformat()} 回抓失败：{exc}", file=sys.stderr)

    print(f"补抓汇总：可处理={ready or '无'}；无论文={empty or '无'}；失败={failed or '无'}")
    # A partial range remains useful. Fail only when no date can be processed.
    return 0 if ready or empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
