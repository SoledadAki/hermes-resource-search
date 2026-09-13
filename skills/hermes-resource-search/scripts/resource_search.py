#!/usr/bin/env python3
"""Anime release search across public catalog mirrors.

Stdlib only — works on any Python 3.8+ install, no dependencies.

Sources:
  garden  https://api.animes.garden   (dmhy + bangumi.moe + mikan + moe mirror; magnet included)
  nyaa    https://nyaa.si             (RSS; infohash included)
  mikan   https://mikanani.me         (RSS; .torrent URL included)

Usage:
  python3 resource_search.py "<series name>"
  python3 resource_search.py "<series name>" --limit 5 --quality 2160p
  python3 resource_search.py "<romaji title>" --source nyaa --source mikan
  python3 resource_search.py "<series name>" --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = "Mozilla/5.0 (compatible; hermes-resource-search/1.0)"
TIMEOUT = 25

GARDEN = "https://api.animes.garden/resources"
NYAA = "https://nyaa.si/"
MIKAN = "https://mikanani.me/RSS/Search"

# Simplified-only enum values. Traditional variants ("動畫") return zero results.
GARDEN_TYPES = ["动画", "合集", "音乐", "日剧", "RAW", "漫画", "游戏", "特摄", "其他"]

SPEC_PATTERNS = [
    ("res", r"\b(4320p|2160p|1440p|1080p|720p|480p|4K|8K)\b"),
    ("src", r"\b(BDRemux|BDRip|BDrip|BluRay|Blu-ray|WEB-DL|WEBRip|WebRip|Webrip|WEB|HDTV|DVDRip|UHDrip|UHDRip)\b"),
    ("codec", r"\b(HEVC|x265|x264|H\.?264|H\.?265|AVC|AV1|VP9)\b"),
    ("depth", r"\b(8bit|10bit|12bit)\b"),
    ("sub", r"(简繁日|简繁|简体|繁体|简中|繁中|内嵌|外挂|内封)"
            r"|\b(CHS|CHT|Baha|B-Global|CR|NF|ABEMA|ViuTV|BILIBILI|HKTV)\b"),
]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def fetch(url: str, params: dict | None = None) -> bytes:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, encoding='utf-8')}"
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024 or unit == "TB":
            return f"{num_bytes:.2f} {unit}" if unit != "B" else f"{int(num_bytes)} B"
        num_bytes /= 1024
    return f"{num_bytes:.2f} TB"


def parse_size(text: str) -> int:
    """Parse '1.5 GiB' / '5.3 GiB' / '12.2 GB' style strings into bytes."""
    m = re.match(r"([\d.]+)\s*([KMGTP]?)i?B", text.strip(), re.I)
    if not m:
        return 0
    value = float(m.group(1))
    power = {"": 0, "K": 1, "M": 2, "G": 3, "T": 4, "P": 5}[m.group(2).upper()]
    return int(value * (1024 ** power))


def extract_specs(title: str) -> str:
    parts = []
    for _, pattern in SPEC_PATTERNS:
        for hit in re.findall(pattern, title, re.I):
            token = hit if isinstance(hit, str) else hit[0]
            if token and token.lower() not in (p.lower() for p in parts):
                parts.append(token)
    return " ".join(parts)


def normalize_date(raw: str) -> str:
    """RFC-2822 ('Tue, 11 Aug 2026 10:43:21 -0000') or ISO-8601 -> 'YYYY-MM-DD'."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(raw).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001 - fall through to ISO handling
        pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else raw[:10]


def link_of(rec: dict) -> str:
    return rec.get("magnet") or rec.get("torrent") or rec.get("page") or ""


def record(title, link, fansub="", size=0, provider="", page="", date=""):
    return {
        "title": WS_RE.sub(" ", title).strip(),
        "fansub": fansub,
        "size": size,
        "size_human": human_size(size) if size else "?",
        "specs": extract_specs(title),
        "link": link,
        "provider": provider,
        "page": page,
        "date": normalize_date(date),
    }


# --------------------------------------------------------------------------- garden


def search_garden(keyword: str, limit: int, rtype: str = "") -> list[dict]:
    params = {"keyword": keyword, "pageSize": min(max(limit * 3, 10), 50)}
    if rtype:
        params["type"] = rtype
    data = json.loads(fetch(GARDEN, params).decode("utf-8", "replace"))
    out = []
    for r in data.get("resources", []):
        out.append(record(
            title=r.get("title", ""),
            link=r.get("magnet", ""),
            fansub=(r.get("fansub") or {}).get("name", ""),
            size=r.get("size", 0),
            provider=r.get("provider", "garden"),
            page=r.get("href", ""),
            date=r.get("createdAt", ""),
        ))
    return out


# ---------------------------------------------------------------------------- nyaa


def search_nyaa(keyword: str, limit: int, category: str = "1_2") -> list[dict]:
    """category 1_2 = Anime / English-translated (all-language index)."""
    xml = fetch(NYAA, {"page": "rss", "q": keyword, "c": category, "f": "0"})
    root = ET.fromstring(xml)
    ns = {"nyaa": "https://nyaa.si/xmlns/nyaa"}
    out = []
    for item in root.iter("item"):
        title = item.findtext("title", "").strip()
        infohash = (item.findtext("nyaa:infoHash", "", ns) or "").strip()
        size = parse_size(item.findtext("nyaa:size", "0 B", ns) or "0 B")
        link = f"magnet:?xt=urn:btih:{infohash}" if infohash else item.findtext("link", "")
        out.append(record(
            title=title,
            link=link,
            size=size,
            provider="nyaa",
            page=item.findtext("guid", ""),
            date=item.findtext("pubDate", ""),
        ))
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- mikan


MIKAN_NS = "{https://mikanani.me/0.1/}"


def search_mikan(keyword: str, limit: int) -> list[dict]:
    xml = fetch(MIKAN, {"searchstr": keyword})
    root = ET.fromstring(xml)
    out = []
    for item in root.iter("item"):
        title = item.findtext("title", "").strip()
        page = item.findtext("link", "")
        torrent = ""
        for enc in item.iter("enclosure"):
            if enc.get("type") == "application/x-bittorrent" or enc.get("url", "").endswith(".torrent"):
                torrent = enc.get("url", "")
                break
        size = 0
        node = item.find(f"{MIKAN_NS}torrent")
        if node is None:
            node = item.find("torrent")
        if node is not None:
            raw = node.findtext(f"{MIKAN_NS}contentLength") or node.findtext("contentLength") or "0"
            size = int(raw) if raw.isdigit() else 0
        if not size:
            m = re.search(r"\[([\d.]+\s*[KMGT]i?B)\]", item.findtext("description", "") or "")
            size = parse_size(m.group(1)) if m else 0
        out.append(record(
            title=title,
            link=torrent or page,
            size=size,
            provider="mikan",
            page=page,
            date=node.findtext(f"{MIKAN_NS}pubDate", "") if node is not None else "",
        ))
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------------ pipeline

SOURCES = {
    "garden": search_garden,
    "nyaa": search_nyaa,
    "mikan": search_mikan,
}


def dedupe(records: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in records:
        key = r["link"].split("btih:")[-1].lower() if "btih:" in r["link"] else r["title"][:60].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def render(records: list[dict], keyword: str, sources: list[str]) -> str:
    if not records:
        return (f"No records found for {keyword!r} (sources: {', '.join(sources)}).\n"
                "Try a shorter keyword — matching is an ordered substring, so "
                "extra words in the wrong order produce zero hits.")
    lines = [f"## Results for {keyword!r} — {len(records)} record(s)",
             f"_sources: {', '.join(sources)}_", ""]
    for i, r in enumerate(records, 1):
        head = f"{i}. {r['title']}"
        meta = " | ".join(x for x in (r["fansub"], r["specs"], r["size_human"],
                                      r["provider"], r["date"]) if x)
        lines.append(head)
        if meta:
            lines.append(f"   {meta}")
        lines.append(f"   link: {r['link']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Search public anime release catalogs.")
    ap.add_argument("keyword", nargs="+", help="Search term. Use the title order that appears in release names.")
    ap.add_argument("--source", action="append", choices=sorted(SOURCES), default=None,
                    help="Source to query (repeatable). Default: garden, then nyaa + mikan as fallback.")
    ap.add_argument("--limit", type=int, default=8, help="Max results per source (default 8).")
    ap.add_argument("--type", default="", help=f"garden only. One of: {', '.join(GARDEN_TYPES)}")
    ap.add_argument("--quality", default="", help="Post-filter: keep titles matching this token, e.g. 1080p / 2160p / BDRip.")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = ap.parse_args()

    keyword = " ".join(args.keyword).strip()
    sources = args.source or ["garden"]
    records: list[dict] = []
    errors: list[str] = []

    for src in sources:
        try:
            if src == "garden":
                records += search_garden(keyword, args.limit, args.type)
            else:
                records += SOURCES[src](keyword, args.limit)
        except urllib.error.URLError as e:
            errors.append(f"{src}: network error ({e})")
        except ET.ParseError as e:
            errors.append(f"{src}: unparsable feed ({e})")
        except Exception as e:  # noqa: BLE001 - report, never crash the agent run
            errors.append(f"{src}: {type(e).__name__}: {e}")

    records = dedupe(records)
    if args.quality:
        needle = args.quality.lower()
        records = [r for r in records if needle in r["title"].lower()]
    records = records[: max(args.limit, 1) * len(sources)]

    if args.json:
        print(json.dumps({"keyword": keyword, "sources": sources,
                          "errors": errors, "records": records},
                         ensure_ascii=False, indent=2))
    else:
        print(render(records, keyword, sources))
        for err in errors:
            print(f"[warn] {err}", file=sys.stderr)
    return 0 if records else 1


if __name__ == "__main__":
    sys.exit(main())
