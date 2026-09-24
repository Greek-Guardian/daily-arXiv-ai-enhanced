"""Fetch arXiv metadata for one or more historical submission dates."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from lxml import html


ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
OPENSEARCH = "{http://a9.com/-/spec/opensearch/1.1/}"
API_URL = "https://export.arxiv.org/api/query"
PAGE_SIZE = 500
MAX_RANGE_DAYS = 14
USER_AGENT = (
    "daily-arxiv-ai-enhanced/1.0 "
    "(https://github.com/Greek-Guardian/daily-arXiv-ai-enhanced)"
)


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


def read_url(url: str) -> bytes:
    """Read an arXiv page with retries for transient throttling."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=60) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("unreachable")
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
        root = ET.fromstring(read_url(request_url))
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


def metadata_from_abstract(paper_id: str) -> tuple[date, dict]:
    tree = html.fromstring(read_url(f"https://arxiv.org/abs/{paper_id}"))

    def meta(name: str) -> str:
        values = tree.xpath(f'//meta[@name="{name}"]/@content')
        return " ".join(values[0].split()) if values else ""

    submitted = date.fromisoformat(meta("citation_date").replace("/", "-"))
    subjects = " ".join(tree.cssselect("td.tablecell.subjects")[0].itertext()) if tree.cssselect("td.tablecell.subjects") else ""
    comments = " ".join(tree.cssselect("td.tablecell.comments")[0].itertext()) if tree.cssselect("td.tablecell.comments") else ""
    return submitted, {
        "id": paper_id,
        "pdf": meta("citation_pdf_url") or f"https://arxiv.org/pdf/{paper_id}",
        "abs": f"https://arxiv.org/abs/{paper_id}",
        "authors": tree.xpath('//meta[@name="citation_author"]/@content'),
        "title": meta("citation_title"),
        "categories": re.findall(r"\(([^)]+)\)", subjects),
        "comment": " ".join(comments.split()),
        "summary": meta("citation_abstract"),
    }


def monthly_ids(category: str, target: date) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    skip = 0
    page_size = 2000
    while True:
        url = f"https://arxiv.org/list/{category}/{target:%Y-%m}?skip={skip}&show={page_size}"
        tree = html.fromstring(read_url(url))
        page_ids = [
            href.rsplit("/", 1)[-1]
            for href in tree.xpath('//a[@title="Abstract"]/@href')
        ]
        new_ids = [paper_id for paper_id in page_ids if paper_id not in seen]
        result.extend(new_ids)
        seen.update(new_ids)
        page_text = " ".join(tree.xpath("//small//text()"))
        total_match = re.search(r"total of\s+([0-9,]+)\s+entries", page_text)
        total = int(total_match.group(1).replace(",", "")) if total_match else len(result)
        if not new_ids or len(result) >= total:
            break
        skip += len(page_ids)
    return result


def recent_ids(category: str, target: date) -> tuple[bool, list[str]]:
    """Return IDs from the dated sections of arXiv's past-week page."""
    url = f"https://arxiv.org/list/{category}/pastweek?show=2000"
    tree = html.fromstring(read_url(url))
    expected = target.strftime("%a, %d %b %Y")
    for heading in tree.xpath("//h3"):
        heading_text = " ".join(" ".join(heading.itertext()).split())
        if heading_text.startswith(expected):
            ids: list[str] = []
            sibling = heading.getnext()
            while sibling is not None and sibling.tag.lower() != "h3":
                if sibling.tag.lower() == "dt":
                    ids.extend(
                        href.rsplit("/", 1)[-1]
                        for href in sibling.xpath('.//a[@title="Abstract"]/@href')
                    )
                sibling = sibling.getnext()
            return True, ids
    return False, []


def fetch_day_from_html(target: date, categories: list[str]) -> list[dict]:
    """Fallback for CI networks rejected by export.arxiv.org."""
    recent_matches: list[str] = []
    recent_page_has_target = False
    for category in categories:
        found, ids = recent_ids(category, target)
        recent_page_has_target = recent_page_has_target or found
        recent_matches.extend(ids)

    if recent_page_has_target:
        unique_ids = list(dict.fromkeys(recent_matches))
        print(f"网页兜底：pastweek 日期分组定位到 {len(unique_ids)} 篇当日候选")
        with ThreadPoolExecutor(max_workers=8) as executor:
            records = list(executor.map(metadata_from_abstract, unique_ids))
        # The dated heading is the arXiv announcement date used by this site's
        # daily files; individual papers were usually submitted the day before.
        return [
            paper
            for _, paper in records
            if paper.get("categories") and paper["categories"][0] in categories
        ]

    metadata_cache: dict[str, tuple[date, dict]] = {}
    selected_ids: list[str] = []

    def record(paper_id: str) -> tuple[date, dict]:
        if paper_id not in metadata_cache:
            metadata_cache[paper_id] = metadata_from_abstract(paper_id)
        return metadata_cache[paper_id]

    def first_index(ids: list[str], predicate) -> int:
        low, high = 0, len(ids)
        while low < high:
            middle = (low + high) // 2
            if predicate(record(ids[middle])[0]):
                high = middle
            else:
                low = middle + 1
        return low

    for category in categories:
        ids = monthly_ids(category, target)
        if not ids:
            continue
        # Monthly lists are oldest-first. Two binary searches isolate the
        # contiguous block submitted on the requested date.
        start = first_index(ids, lambda submitted: submitted >= target)
        end = first_index(ids, lambda submitted: submitted > target)
        selected_ids.extend(ids[start:end])

    unique_ids = list(dict.fromkeys(selected_ids))
    if not unique_ids:
        return []

    print(f"网页兜底：定位到 {len(unique_ids)} 篇当日候选")
    missing_ids = [paper_id for paper_id in unique_ids if paper_id not in metadata_cache]
    with ThreadPoolExecutor(max_workers=8) as executor:
        fetched = list(executor.map(metadata_from_abstract, missing_ids))
    metadata_cache.update(zip(missing_ids, fetched))
    return [metadata_cache[paper_id][1] for paper_id in unique_ids if metadata_cache[paper_id][0] == target]


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
            try:
                papers = fetch_day(target, categories)
            except Exception as api_exc:
                print(f"arXiv API 不可用（{api_exc}），改用官方网页回抓")
                papers = fetch_day_from_html(target, categories)
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
