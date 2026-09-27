#!/usr/bin/env python3
"""
Lovable Opportunity Radar feed aggregator.

What this version does differently:
1) Converts each broad Google News domain feed into a source-specific,
   sector-focused Google News query at runtime.
2) Uses local-language search terms for China/Japan/Korea and major EU markets.
3) Applies an additional relevance guard to broad/general-news sources.
4) Removes old irrelevant items from the rolling JSON on the next run.
5) Exposes the effective query/profile in status.json for auditability.

Outputs:
  docs/feed.xml
  docs/latest.json
  docs/status.json
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
from urllib.parse import urlencode, urlparse
import xml.etree.ElementTree as ET

import feedparser
import requests

ROOT = Path(__file__).resolve().parent
OPML_PATH = ROOT / "sources.opml"
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "docs").strip().strip("/") or "docs"
DOCS = ROOT / OUTPUT_DIR
DOCS.mkdir(parents=True, exist_ok=True)
SOURCE_FOLDER_PREFIX = os.getenv("SOURCE_FOLDER_PREFIX", "").strip()
LOAD_EXISTING = os.getenv("LOAD_EXISTING", "1").strip().lower() not in {"0", "false", "no"}

RETENTION_HOURS = int(os.getenv("RETENTION_HOURS", "72"))
MAX_ITEMS = int(os.getenv("MAX_ITEMS", "1000"))
MAX_PER_SOURCE = int(os.getenv("MAX_PER_SOURCE", "40"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "40"))
FETCH_WORKERS = int(os.getenv("FETCH_WORKERS", "20"))
TIMEOUT = int(os.getenv("FETCH_TIMEOUT", "20"))

UA = (
    "Mozilla/5.0 (compatible; LovableOpportunityRadar/4.0; "
    "+https://github.com/Sadikkucuk/lovable-opportunity-radar)"
)

# Compact profiles: broad enough to discover opportunities, narrow enough to
# remove politics/sports/celebrity/general-news noise.
PROFILE_TERMS_EN = {
    "INDUSTRIAL": [
        "manufacturing", "factory", "industrial software", "automation",
        "robotics", "digital twin", "supply chain", "AI", "energy",
        "semiconductor", "maintenance", "quality"
    ],
    "TECH": [
        "AI", "software", "SaaS", "enterprise", "automation", "cloud",
        "cybersecurity", "semiconductor", "robotics", "data", "API",
        "digital platform"
    ],
    "STARTUP": [
        "startup", "SaaS", "AI", "enterprise software", "marketplace",
        "automation", "fintech", "climate tech", "logistics", "funding",
        "business model", "platform"
    ],
    "SEMICONDUCTOR": [
        "semiconductor", "chip", "electronics", "AI hardware", "EDA",
        "fab", "packaging", "sensor", "memory", "processor", "foundry"
    ],
    "LOGISTICS": [
        "supply chain", "logistics", "freight", "warehouse", "procurement",
        "transportation", "fleet", "automation", "AI", "software",
        "inventory", "shipping"
    ],
    "ENERGY_MOBILITY": [
        "energy", "grid", "battery", "renewable", "EV", "electric vehicle",
        "charging", "fleet", "mobility", "storage", "climate", "software"
    ],
    "ROBOTICS": [
        "robot", "robotics", "automation", "AI", "autonomous", "warehouse",
        "factory", "drone", "machine vision", "humanoid"
    ],
    "BUSINESS_TECH": [
        "technology", "AI", "software", "startup", "automation",
        "semiconductor", "energy", "supply chain", "digital",
        "robotics", "regulation", "platform"
    ],
}

PROFILE_TERMS_LOCAL = {
    "zh": {
        "INDUSTRIAL": ["制造", "工厂", "工业软件", "自动化", "机器人", "数字孪生", "供应链", "人工智能", "新能源", "半导体", "芯片"],
        "TECH": ["人工智能", "AI", "软件", "SaaS", "企业服务", "自动化", "云计算", "网络安全", "半导体", "机器人", "数据"],
        "STARTUP": ["创业", "初创", "融资", "SaaS", "人工智能", "企业服务", "平台", "市场", "物流", "新能源"],
        "SEMICONDUCTOR": ["半导体", "芯片", "电子", "晶圆", "封装", "传感器", "存储", "处理器", "EDA"],
        "LOGISTICS": ["供应链", "物流", "货运", "仓储", "采购", "运输", "车队", "自动化", "软件"],
        "ENERGY_MOBILITY": ["新能源", "电池", "电动车", "充电", "储能", "能源", "电网", "智能驾驶", "软件"],
        "ROBOTICS": ["机器人", "自动化", "人工智能", "无人机", "智能制造", "机器视觉", "人形机器人"],
        "BUSINESS_TECH": ["科技", "人工智能", "软件", "创业", "自动化", "半导体", "新能源", "供应链", "数字化", "机器人"],
    },
    "ja": {
        "INDUSTRIAL": ["製造", "工場", "産業ソフトウェア", "自動化", "ロボット", "デジタルツイン", "サプライチェーン", "AI", "半導体"],
        "TECH": ["AI", "人工知能", "ソフトウェア", "SaaS", "クラウド", "自動化", "サイバーセキュリティ", "半導体", "ロボット"],
        "STARTUP": ["スタートアップ", "SaaS", "AI", "資金調達", "企業向けソフトウェア", "マーケットプレイス", "物流"],
        "SEMICONDUCTOR": ["半導体", "チップ", "電子", "EDA", "ファブ", "パッケージング", "センサー"],
        "LOGISTICS": ["サプライチェーン", "物流", "倉庫", "調達", "輸送", "自動化", "ソフトウェア"],
        "ENERGY_MOBILITY": ["エネルギー", "電池", "EV", "電気自動車", "充電", "蓄電", "モビリティ"],
        "ROBOTICS": ["ロボット", "自動化", "AI", "自律", "倉庫", "工場", "ドローン"],
        "BUSINESS_TECH": ["テクノロジー", "AI", "ソフトウェア", "スタートアップ", "自動化", "半導体", "エネルギー", "物流"],
    },
    "ko": {
        "INDUSTRIAL": ["제조", "공장", "산업 소프트웨어", "자동화", "로봇", "디지털 트윈", "공급망", "AI", "반도체"],
        "TECH": ["AI", "인공지능", "소프트웨어", "SaaS", "클라우드", "자동화", "사이버보안", "반도체", "로봇"],
        "STARTUP": ["스타트업", "SaaS", "AI", "투자", "기업용 소프트웨어", "마켓플레이스", "물류"],
        "SEMICONDUCTOR": ["반도체", "칩", "전자", "EDA", "파운드리", "패키징", "센서"],
        "LOGISTICS": ["공급망", "물류", "창고", "조달", "운송", "자동화", "소프트웨어"],
        "ENERGY_MOBILITY": ["에너지", "배터리", "전기차", "충전", "저장", "모빌리티", "소프트웨어"],
        "ROBOTICS": ["로봇", "자동화", "AI", "자율", "창고", "공장", "드론"],
        "BUSINESS_TECH": ["기술", "AI", "소프트웨어", "스타트업", "자동화", "반도체", "에너지", "공급망", "로봇"],
    },
    "de": {
        "BUSINESS_TECH": ["KI", "Software", "Automatisierung", "Robotik", "Halbleiter", "Industrie", "Startup", "Lieferkette", "Energie", "Digitalisierung"],
        "INDUSTRIAL": ["Produktion", "Fertigung", "Automatisierung", "Robotik", "Industriesoftware", "Lieferkette", "KI", "Halbleiter"],
        "STARTUP": ["Startup", "SaaS", "KI", "Software", "Plattform", "Finanzierung", "Automatisierung"],
        "SEMICONDUCTOR": ["Halbleiter", "Chip", "Elektronik", "Sensor", "EDA", "Fertigung"],
    },
    "fr": {
        "BUSINESS_TECH": ["IA", "logiciel", "automatisation", "robotique", "semi-conducteurs", "industrie", "startup", "logistique", "énergie", "numérique"],
        "INDUSTRIAL": ["industrie", "usine", "production", "automatisation", "robotique", "logiciel industriel", "IA", "semi-conducteurs"],
        "STARTUP": ["startup", "SaaS", "IA", "logiciel", "plateforme", "financement", "automatisation"],
    },
    "it": {
        "BUSINESS_TECH": ["IA", "software", "automazione", "robotica", "semiconduttori", "industria", "startup", "logistica", "energia", "digitale"],
        "STARTUP": ["startup", "SaaS", "IA", "software", "piattaforma", "finanziamento", "automazione"],
    },
    "sv": {
        "INDUSTRIAL": ["industri", "tillverkning", "automation", "robotik", "AI", "halvledare", "energi", "leveranskedja", "mjukvara"],
        "BUSINESS_TECH": ["teknik", "AI", "mjukvara", "startup", "automation", "robotik", "halvledare", "energi"],
    },
    "no": {
        "INDUSTRIAL": ["industri", "produksjon", "automatisering", "robotikk", "AI", "halvleder", "energi", "forsyningskjede", "programvare"],
        "BUSINESS_TECH": ["teknologi", "AI", "programvare", "startup", "automatisering", "robotikk", "halvleder", "energi"],
    },
    "tr": {
        "INDUSTRIAL": ["sanayi", "üretim", "fabrika", "otomasyon", "robotik", "endüstriyel yazılım", "dijital dönüşüm", "tedarik zinciri", "yapay zeka", "enerji", "bakım", "kalite"],
        "TECH": ["yapay zeka", "AI", "yazılım", "SaaS", "bulut", "otomasyon", "siber güvenlik", "veri", "API", "dijital platform", "fintech", "robotik"],
        "STARTUP": ["girişim", "startup", "yatırım", "fonlama", "SaaS", "yapay zeka", "fintech", "pazaryeri", "platform", "iş modeli", "lojistik", "iklim teknolojisi"],
        "SEMICONDUCTOR": ["yarı iletken", "çip", "elektronik", "sensör", "işlemci", "bellek", "paketleme", "üretim"],
        "LOGISTICS": ["lojistik", "tedarik zinciri", "taşımacılık", "nakliye", "depo", "depolama", "filo", "stok", "envanter", "liman", "kargo", "otomasyon"],
        "ENERGY_MOBILITY": ["enerji", "elektrik", "şebeke", "batarya", "yenilenebilir", "güneş", "rüzgar", "elektrikli araç", "şarj", "mobilite", "depolama"],
        "ROBOTICS": ["robot", "robotik", "otomasyon", "yapay zeka", "otonom", "drone", "makine görüşü", "üretim", "depo"],
        "BUSINESS_TECH": ["teknoloji", "yapay zeka", "AI", "yazılım", "girişim", "startup", "otomasyon", "sanayi", "üretim", "enerji", "lojistik", "tedarik zinciri", "e-ticaret", "dijital", "mevzuat", "yönetmelik", "tebliğ", "destek", "teşvik", "yatırım", "KOBİ", "siber güvenlik", "fintech"],
    },
}

# These publications are primarily consumed/indexed in English even though
# their geographic folder is China/Japan/Korea. Querying them only with local-
# language terms can incorrectly return zero items.
ENGLISH_SOURCE_NAMES = {
    "China Daily", "EqualOcean", "Pandaily", "TechNode", "Gasgoo",
    "CnEVPost", "China Money Network", "South China Morning Post — China Tech",
    "Nikkei Asia", "The Japan Times", "JETRO",
    "TheElec", "Korea Herald — Technology/Business", "Pulse by Maeil Business",
}

SOURCE_PROFILE_OVERRIDES = {
    "Webrazzi": "STARTUP",
    "eGirişim": "STARTUP",
    "Startups.watch": "STARTUP",
    "StartupCentrum": "STARTUP",
    "StartupTeknoloji": "STARTUP",
    "FinTech İstanbul": "STARTUP",
    "TechInside": "TECH",
    "ShiftDelete.Net": "TECH",
    "BT Haber": "TECH",
    "ICT Media": "TECH",
    "Turk-internet.com": "TECH",
    "ST Endüstri": "INDUSTRIAL",
    "Sanayi Gazetesi": "INDUSTRIAL",
    "UTA Lojistik": "LOGISTICS",
    "Lojistik Hattı": "LOGISTICS",
    "Deniz Haber": "LOGISTICS",
    "Enerji Günlüğü": "ENERGY_MOBILITY",
    "Enerji Portalı": "ENERGY_MOBILITY",
    "PetroTurk": "ENERGY_MOBILITY",
    "Yeşil Ekonomi": "ENERGY_MOBILITY",
}

# Specialized sources are already narrow; general/broad publications need a
# stronger post-query relevance guard.
STRICT_SOURCE_NAMES = {
    "Reuters Technology", "Caixin", "Yicai / 第一财经", "The Paper / 澎湃新闻",
    "China Daily", "Xinhua", "China Economic Net", "Securities Times / STCN",
    "Cailian Press / CLS", "South China Morning Post — China Tech",
    "Huxiu", "Sohu Technology", "Tencent Technology", "Sina Technology",
    "Handelsblatt", "Les Echos", "Il Sole 24 Ore", "Nikkei Asia",
    "The Japan Times", "JETRO", "The Logic", "Korea Herald — Technology/Business",
    "Pulse by Maeil Business", "Economic Times — Technology",
    "Ekonomim", "Dünya", "Bloomberg HT", "Forbes Türkiye", "Fortune Türkiye",
    "Fast Company Türkiye", "Capital", "Ekonomist", "Marketing Türkiye",
    "MediaCat", "Digital Age", "Perakende.org", "Retail Türkiye", "Gıda Hattı",
    "Resmi Gazete", "Ticaret Bakanlığı", "Sanayi ve Teknoloji Bakanlığı",
    "KOSGEB", "TÜBİTAK", "BTK", "EPDK", "KVKK", "Rekabet Kurumu",
    "SPK", "BDDK", "TCMB", "Trakya Kalkınma Ajansı",
    "Lüleburgaz TSO", "Lüleburgaz Belediyesi", "Kırklareli Valiliği"
}

GENERIC_TITLE_RE = re.compile(
    r"^\s*[-–—|:]*\s*(startupitalia|caixin|搜狐网|财新网|xinhua|reuters|"
    r"china daily|the japan times|handelsblatt|les echos|il sole 24 ore)"
    r"\s*[-–—|:]*\s*$",
    re.I,
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

    if SOURCE_FOLDER_PREFIX:
        feeds = [f for f in feeds if f["folder"].startswith(SOURCE_FOLDER_PREFIX)]

    return feeds

def profile_for(name: str) -> str:
    if name in SOURCE_PROFILE_OVERRIDES:
        return SOURCE_PROFILE_OVERRIDES[name]

    n = name.lower()

    if any(k in n for k in (
        "semiconductor", "ee times", "eefocus", "electronics weekly",
        "bits&chips", "theelec"
    )):
        return "SEMICONDUCTOR"

    if any(k in n for k in (
        "robot report", "robotstart", "robotics & automation"
    )):
        return "ROBOTICS"

    if any(k in n for k in (
        "supply chain", "freightwaves"
    )):
        return "LOGISTICS"

    if any(k in n for k in (
        "utility dive", "trellis", "greenbiz", "electric autonomy",
        "the driven", "cnevpost", "gasgoo"
    )):
        return "ENERGY_MOBILITY"

    if any(k in n for k in (
        "industryweek", "manufacturing", "automation world",
        "control engineering", "machine design", "design news",
        "plant services", "quality magazine", "food engineering",
        "packaging world", "the manufacturer", "the engineer",
        "produktion", "industrie.de", "usine nouvelle", "ny teknik",
        "teknisk ukeblad", "eit manufacturing", "monoist"
    )):
        return "INDUSTRIAL"

    if any(k in n for k in (
        "36kr", "equalocean", "pandaily", "technode", "china money network",
        "sifted", "tech.eu", "eu-startups", "silicon canals", "tnw",
        "maddyness", "startupitalia", "betakit", "innovationaus",
        "startup daily", "tech in asia", "dealstreetasia", "yourstory",
        "inc42", "venturebeat"
    )):
        return "STARTUP"

    if any(k in n for k in (
        "ieee spectrum", "technology review", "techcrunch", "ars technica",
        "the register", "iot world today", "heise", "computerwoche",
        "zdnet", "it world canada", "itnews", "ithome", "ofweek",
        "leiphone", "nikkei xtech", "itmedia", "impress watch", "etnews"
    )):
        return "TECH"

    return "BUSINESS_TECH"

def locale_for(meta: dict[str, str]) -> tuple[str, str, str, str]:
    name = meta["name"]
    folder = meta["folder"]

    if name in ENGLISH_SOURCE_NAMES:
        return ("en", "en-US", "US", "US:en")

    if name == "Ny Teknik":
        return ("sv", "sv", "SE", "SE:sv")
    if name == "Teknisk Ukeblad":
        return ("no", "no", "NO", "NO:no")

    if folder.startswith("Türkiye"):
        return ("tr", "tr", "TR", "TR:tr")

    if folder.startswith("China"):
        return ("zh", "zh-CN", "CN", "CN:zh-Hans")
    if "Japan" in folder:
        return ("ja", "ja", "JP", "JP:ja")
    if "South Korea" in folder:
        return ("ko", "ko", "KR", "KR:ko")

    if name in {"Heise", "Handelsblatt", "Computerwoche", "Produktion", "Industrie.de"}:
        return ("de", "de", "DE", "DE:de")
    if name in {"L'Usine Nouvelle", "Les Echos", "Maddyness", "ZDNet France"}:
        return ("fr", "fr", "FR", "FR:fr")
    if name in {"Il Sole 24 Ore", "StartupItalia"}:
        return ("it", "it", "IT", "IT:it")

    if "Canada" in folder:
        return ("en", "en-CA", "CA", "CA:en")
    if "Australia" in folder:
        return ("en", "en-AU", "AU", "AU:en")
    if "India" in folder:
        return ("en", "en-IN", "IN", "IN:en")
    if "Singapore" in folder:
        return ("en", "en-SG", "SG", "SG:en")
    if folder.startswith("Europe"):
        return ("en", "en-GB", "GB", "GB:en")

    return ("en", "en-US", "US", "US:en")

def domain_for(meta: dict[str, str]) -> str:
    site = meta.get("site_url") or meta.get("feed_url") or ""
    host = urlparse(site).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host

def terms_for(meta: dict[str, str], profile: str, lang: str) -> list[str]:
    local = PROFILE_TERMS_LOCAL.get(lang, {}).get(profile)
    if local:
        return local
    return PROFILE_TERMS_EN[profile]

def effective_feed(meta: dict[str, str]) -> tuple[str, str, str]:
    profile = profile_for(meta["name"])
    lang, hl, gl, ceid = locale_for(meta)
    domain = domain_for(meta)
    terms = terms_for(meta, profile, lang)

    or_terms = []
    for term in terms:
        if " " in term and not (term.startswith('"') and term.endswith('"')):
            or_terms.append(f'"{term}"')
        else:
            or_terms.append(term)

    query = f"site:{domain} (" + " OR ".join(or_terms) + ")"
    url = "https://news.google.com/rss/search?" + urlencode({
        "q": query,
        "hl": hl,
        "gl": gl,
        "ceid": ceid,
    })
    return url, profile, query

def relevance_terms(meta: dict[str, str], profile: str) -> list[str]:
    lang, _, _, _ = locale_for(meta)
    terms = []
    terms.extend(PROFILE_TERMS_EN[profile])
    local = PROFILE_TERMS_LOCAL.get(lang, {}).get(profile, [])
    terms.extend(local)
    return [t.strip('"').lower() for t in terms if t]

def relevant_text(text: str, terms: list[str]) -> bool:
    normalized = text.lower()
    return any(term.lower() in normalized for term in terms)

def is_entry_relevant(meta: dict[str, str], profile: str, title: str, summary: str) -> bool:
    if not title or len(title.strip()) < 6:
        return False
    if GENERIC_TITLE_RE.match(title):
        return False

    # Query-level filtering is enough for specialist sources.
    if meta["name"] not in STRICT_SOURCE_NAMES:
        return True

    combined = f"{title} {summary}"
    return relevant_text(combined, relevance_terms(meta, profile))

def fetch_one(meta: dict[str, str]) -> dict[str, Any]:
    started = time.monotonic()
    effective_url, profile, query = effective_feed(meta)

    result: dict[str, Any] = {
        **meta,
        "effective_feed_url": effective_url,
        "focus_profile": profile,
        "focus_query": query,
        "ok": False,
        "status": None,
        "error": None,
        "raw_items": 0,
        "items": [],
        "elapsed_ms": None,
    }

    try:
        r = requests.get(
            effective_url,
            headers={
                "User-Agent": UA,
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
            },
            timeout=TIMEOUT,
        )
        result["status"] = r.status_code
        r.raise_for_status()

        parsed = feedparser.parse(r.content)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise RuntimeError(str(getattr(parsed, "bozo_exception", "feed parse error")))

        result["raw_items"] = len(parsed.entries)
        entries = []

        for entry in parsed.entries:
            title = clean_text(entry.get("title"))
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            summary = clean_text(entry.get("summary") or entry.get("description") or "")
            if not is_entry_relevant(meta, profile, title, summary):
                continue

            published = parse_entry_date(entry)
            entry_id = str(entry.get("id") or entry.get("guid") or link)

            source_info = entry.get("source") or {}
            publisher_url = str(source_info.get("href") or "").strip()
            publisher_name = clean_text(source_info.get("title") or "")

            entries.append({
                "title": title,
                "url": link,
                "summary": summary[:1200],
                "published_at": iso(published) if published else None,
                "entry_id": entry_id,
                "publisher_url": publisher_url,
                "publisher_name": publisher_name,
            })

            # MAX_PER_SOURCE now means maximum RELEVANT items kept, not merely
            # "look at the first N results". This avoids losing relevant items
            # ranked below noisy/filtered results.
            if len(entries) >= MAX_PER_SOURCE:
                break

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
    if not LOAD_EXISTING:
        return []
    path = DOCS / "latest.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("items", [])
    except Exception:
        pass
    return []

def normalize_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None

def old_item_relevant(item: dict[str, Any]) -> bool:
    # Re-evaluate rolling-history items so irrelevant results from the previous
    # broad-domain version disappear immediately after this upgrade.
    source = item.get("source", "")
    folder = item.get("folder", "")
    meta = {
        "name": source,
        "folder": folder,
        "site_url": item.get("source_site", ""),
        "feed_url": item.get("source_feed", ""),
    }
    profile = profile_for(source)
    return is_entry_relevant(
        meta,
        profile,
        clean_text(item.get("title")),
        clean_text(item.get("summary")),
    )

def merge_items(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = utcnow()
    cutoff = now - timedelta(hours=RETENTION_HOURS)
    all_items: list[dict[str, Any]] = []

    for old in load_existing():
        dt = normalize_date(old.get("published_at")) or normalize_date(old.get("seen_at"))
        if dt and dt >= cutoff and old_item_relevant(old):
            all_items.append(old)

    for result in results:
        for item in result["items"]:
            published = normalize_date(item["published_at"])
            if published and published < cutoff:
                continue

            all_items.append({
                "id": hashlib.sha256(
                    f'{result["name"]}|{item["entry_id"]}'.encode("utf-8")
                ).hexdigest()[:24],
                "title": item["title"],
                "url": item["url"],
                "discovery_url": item["url"],
                "publisher_url": item.get("publisher_url") or result["site_url"],
                "publisher_name": item.get("publisher_name") or result["name"],
                "summary": item["summary"],
                "published_at": item["published_at"],
                "seen_at": iso(now),
                "source": result["name"],
                "source_site": result["site_url"],
                "source_feed": result["effective_feed_url"],
                "source_original_feed": result["feed_url"],
                "folder": result["folder"],
                "focus_profile": result["focus_profile"],
            })

    unique: dict[str, dict[str, Any]] = {}
    for item in all_items:
        key = dedupe_key(item)
        current = unique.get(key)
        if not current:
            unique[key] = item
        elif not current.get("published_at") and item.get("published_at"):
            unique[key] = item

    items = list(unique.values())

    def sort_key(x: dict[str, Any]) -> datetime:
        return (
            normalize_date(x.get("published_at"))
            or normalize_date(x.get("seen_at"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )

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
        "filter_version": "sector-focused-v4-tr",
        "items": items,
    }

    (DOCS / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    status = {
        "generated_at": iso(now),
        "filter_version": "sector-focused-v4-tr",
        "source_count": len(results),
        "successful_sources": sum(1 for r in results if r["ok"]),
        "failed_sources": sum(1 for r in results if not r["ok"]),
        "sources": [
            {
                "name": r["name"],
                "folder": r["folder"],
                "focus_profile": r["focus_profile"],
                "focus_query": r["focus_query"],
                "original_feed_url": r["feed_url"],
                "effective_feed_url": r["effective_feed_url"],
                "site_url": r["site_url"],
                "ok": r["ok"],
                "http_status": r["status"],
                "raw_items_received": r["raw_items"],
                "items_kept": len(r["items"]),
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


def write_batches(items: list[dict[str, Any]]) -> None:
    """Write deterministic smaller JSON files so ChatGPT can consume the
    complete rolling window without relying on one very large latest.json."""
    batch_dir = DOCS / "batches"
    batch_dir.mkdir(exist_ok=True)

    # Remove stale batch files from a previous run.
    for old in batch_dir.glob("batch-*.json"):
        old.unlink()

    batch_rel = batch_dir.relative_to(ROOT).as_posix().rstrip("/") + "/"
    base_raw = "https://raw.githubusercontent.com/Sadikkucuk/lovable-opportunity-radar/main/" + batch_rel
    batches = []

    for start in range(0, len(items), BATCH_SIZE):
        batch_items = items[start:start + BATCH_SIZE]
        number = (start // BATCH_SIZE) + 1
        filename = f"batch-{number:03d}.json"
        payload = {
            "batch_number": number,
            "batch_size": len(batch_items),
            "total_items": len(items),
            "items": batch_items,
        }
        (batch_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        batches.append({
            "batch_number": number,
            "item_count": len(batch_items),
            "path": f"docs/batches/{filename}",
            "url": base_raw + filename,
        })

    index = {
        "generated_at": iso(utcnow()),
        "retention_hours": RETENTION_HOURS,
        "total_items": len(items),
        "batch_size": BATCH_SIZE,
        "batch_count": len(batches),
        "batches": batches,
    }
    (batch_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def rfc2822(dt: datetime) -> str:
    from email.utils import format_datetime
    return format_datetime(dt.astimezone(timezone.utc))

def write_rss(items: list[dict[str, Any]]) -> None:
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "Lovable Opportunity Radar — Focused Combined Feed"
    ET.SubElement(channel, "description").text = (
        "Sector-focused opportunity feed across technology, industry, AI, "
        "automation, startups, logistics, energy and semiconductors."
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
        desc_parts.append(f'Focus: {item.get("focus_profile", "")}')
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
        scope = f" for folder prefix {SOURCE_FOLDER_PREFIX!r}" if SOURCE_FOLDER_PREFIX else ""
        raise RuntimeError("No feeds found in sources.opml" + scope)

    with cf.ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        results = list(pool.map(fetch_one, feeds))

    items = merge_items(results)
    write_json(items, results)
    write_batches(items)
    write_rss(items)

    ok = sum(1 for r in results if r["ok"])
    failed = len(results) - ok
    raw = sum(r["raw_items"] for r in results)
    kept = sum(len(r["items"]) for r in results)
    print(
        f"Sources: {len(results)} | OK: {ok} | Failed: {failed} | "
        f"Raw: {raw} | Kept this run: {kept} | Rolling items: {len(items)}"
    )

    if ok == 0:
        raise SystemExit("All source fetches failed")

if __name__ == "__main__":
    main()
