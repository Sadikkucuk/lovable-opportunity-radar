#!/usr/bin/env python3
"""
Merge all RSS/Atom feeds listed in sources.opml into:
  docs/feed.xml
  docs/latest.json
  docs/status.json

Designed for GitHub Actions. The OPML may contain nested folders.
"""

from __future__ import annotations

import calendar
import concurrent.futures as cf
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import feedparser
import requests

ROOT = Path(__file__).resolve().parent
OPML_PATH = ROOT / "sources.opml"
DOCS = ROOT / "docs"
DOCS.mkdir(exist_ok=True)

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "72"))
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "1000"))
MAX_PER_SOURCE = int(os.getenv("MAX_PER_SOURCE", "30"))
FETCH_WORKERS = int(os.getenv("FETCH_WORKERS", "20"))
TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "20"))

UA = (
    "Mozilla/5.0 (compatible; LovableOpportunityRadar/1.0; "
    "+https://github.com/)"
)

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()

def parse_entry_date(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        tm = entry.get(key)
        if tm:
            try:
                return datetime.fromtimestamp(calendar.timegm(tm), tz=timezone.utc)
            except Exception:
                pass
    return None

def parse_opml() -> list[dict[str, str]]:
    tree = ET.parse(OPML_PATH)
    body = tree.getroot().find("body")
    if body is None:
        raise RuntimeError("Invalid OPML: missing <body>")

    feeds: list[dict[str, str]] = []

    def walk(node: ET.Element, folders: list[str]) -> None:
        children = list(node.findall("outline"))
        xml_url = node.attrib.get("xmlUrl")
        if xml_url:
            feeds.append({
                "name": node.attrib.get("title") or node.attrib.get("text") or xml_url,
                "feed_url": xml_url,
                "site_url": node.attrib.get("htmlUrl", ""),
                "folder": " / ".join(folders),
            })
            return

        name = node.attrib.get("title") or node.attrib.get("text")
        next_folders = folders + ([name] if name else [])
        for child in children:
            walk(child, next_folders)

    for child in body.findall("outline"):
        walk(child, [])

    return feeds

def fetch_one(meta: dict[str, str]) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        **meta,
        "ok": False,
        "status": None,
        "error": None,
        "items": [],
        "elapsed_ms": None,
    }
    try:
        r = requests.get(
            meta["feed_url"],
            headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"},
            timeout=TIMEOUT,
        )
        result["status"] = r.status_code
        r.raise_for_status()

        parsed = feedparser.parse(r.content)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise RuntimeError(str(getattr(parsed, "bozo_exception", "feed parse error")))

        entries = []
        for entry in parsed.entries[:MAX_PER_SOURCE]:
            title = clean_text(entry.get("title"))
            link = entry.get("link", "").strip()
            if not title or not link:
                continue
            published = parse_entry_date(entry)
            summary = clean_text(entry.get("summary") or entry.get("description") or "")
            entry_id = str(entry.get("id") or entry.get("guid") or link)
            entries.append({
                "title": title,
                "url": link,
                "summary": summary[:1200],
                "published_at": iso(published) if published else None,
                "entry_id": entry_id,
            })

        result["items"] = entries
        result["ok"] = True
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return result

def dedupe_key(item: dict[str, Any]) -> str:
    raw = (item.get("url") or "") + "\n" + (item.get("title") or "").lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def load_existing() -> list[dict[str, Any]]:
    path = DOCS / "latest.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("items", [])
        return []
    except Exception:
        return []

def normalize_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None

def merge_items(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = utcnow()
    cutoff = now - timedelta(hours=RETENTION_HOURS)
    all_items: list[dict[str, Any]] = []

    # Keep recent historical items so a temporary feed failure does not erase them.
    for old in load_existing():
        dt = normalize_date(old.get("published_at")) or normalize_date(old.get("seen_at"))
        if dt and dt >= cutoff:
            all_items.append(old)

    for result in results:
        for item in result["items"]:
            published = normalize_date(item["published_at"])
            # Undated items are retained because some feeds omit timestamps.
            if published and published < cutoff:
                continue

            all_items.append({
                "id": hashlib.sha256(
                    f'{result["name"]}|{item["entry_id"]}'.encode("utf-8")
                ).hexdigest()[:24],
                "title": item["title"],
                "url": item["url"],
                "summary": item["summary"],
                "published_at": item["published_at"],
                "seen_at": iso(now),
                "source": result["name"],
                "source_site": result["site_url"],
                "source_feed": result["feed_url"],
                "folder": result["folder"],
            })

    unique: dict[str, dict[str, Any]] = {}
    for item in all_items:
        key = dedupe_key(item)
        current = unique.get(key)
        if not current:
            unique[key] = item
        else:
            # Prefer the copy with an explicit publication timestamp.
            if not current.get("published_at") and item.get("published_at"):
                unique[key] = item

    items = list(unique.values())

    def sort_key(x: dict[str, Any]) -> datetime:
        return normalize_date(x.get("published_at")) or normalize_date(x.get("seen_at")) or datetime.min.replace(tzinfo=timezone.utc)

    items.sort(key=sort_key, reverse=True)
    return items[:MAX_ITEMS]

def write_json(items: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
    now = utcnow()
    payload = {
        "generated_at": iso(now),
        "retention_hours": RETENTION_HOURS,
        "source_count": len(results),
        "successful_sources": sum(1 for r in results if r["ok"]),
        "failed_sources": sum(1 for r in results if not r["ok"]),
        "item_count": len(items),
        "items": items,
    }
    (DOCS / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    status = {
        "generated_at": iso(now),
        "source_count": len(results),
        "successful_sources": sum(1 for r in results if r["ok"]),
        "failed_sources": sum(1 for r in results if not r["ok"]),
        "sources": [
            {
                "name": r["name"],
                "folder": r["folder"],
                "feed_url": r["feed_url"],
                "site_url": r["site_url"],
                "ok": r["ok"],
                "http_status": r["status"],
                "items_received": len(r["items"]),
                "elapsed_ms": r["elapsed_ms"],
                "error": r["error"],
            }
            for r in sorted(results, key=lambda x: (x["folder"], x["name"].lower()))
        ],
    }
    (DOCS / "status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def rfc2822(dt: datetime) -> str:
    from email.utils import format_datetime
    return format_datetime(dt.astimezone(timezone.utc))

def write_rss(items: list[dict[str, Any]]) -> None:
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Lovable Opportunity Radar — Combined Feed"
    ET.SubElement(channel, "description").text = (
        "Combined recent articles from the Lovable Opportunity Radar source universe."
    )
    ET.SubElement(channel, "language").text = "en"
    ET.SubElement(channel, "lastBuildDate").text = rfc2822(utcnow())

    for item in items:
        node = ET.SubElement(channel, "item")
        ET.SubElement(node, "title").text = f'[{item["source"]}] {item["title"]}'
        ET.SubElement(node, "link").text = item["url"]
        guid = ET.SubElement(node, "guid", isPermaLink="false")
        guid.text = item["id"]

        dt = normalize_date(item.get("published_at")) or normalize_date(item.get("seen_at"))
        if dt:
            ET.SubElement(node, "pubDate").text = rfc2822(dt)

        desc_parts = []
        if item.get("summary"):
            desc_parts.append(item["summary"])
        desc_parts.append(f'Source: {item["source"]}')
        if item.get("folder"):
            desc_parts.append(f'Folder: {item["folder"]}')
        if item.get("source_site"):
            desc_parts.append(f'Source site: {item["source_site"]}')
        ET.SubElement(node, "description").text = "\n".join(desc_parts)

        if item.get("folder"):
            ET.SubElement(node, "category").text = item["folder"]

    ET.indent(rss, space="  ")
    ET.ElementTree(rss).write(
        DOCS / "feed.xml",
        encoding="utf-8",
        xml_declaration=True,
    )

def main() -> None:
    feeds = parse_opml()
    if not feeds:
        raise RuntimeError("No feeds found in sources.opml")

    with cf.ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        results = list(pool.map(fetch_one, feeds))

    items = merge_items(results)
    write_json(items, results)
    write_rss(items)

    ok = sum(1 for r in results if r["ok"])
    failed = len(results) - ok
    print(f"Sources: {len(results)} | OK: {ok} | Failed: {failed} | Items: {len(items)}")

    # Don't fail the whole workflow for a few unavailable sources.
    if ok == 0:
        raise SystemExit("All source fetches failed")

if __name__ == "__main__":
    main()
