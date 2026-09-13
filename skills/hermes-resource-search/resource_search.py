#!/usr/bin/env python3
"""Release-catalog search across public index mirrors — animation **and** live action.

Stdlib only — works on any Python 3.8+ install, no dependencies.

Animation sources:
  garden  https://api.animes.garden   (dmhy + bangumi.moe + mikan + moe mirror; magnet included)
  nyaa    https://nyaa.si             (RSS; infohash included)
  mikan   https://mikanani.me         (RSS; .torrent URL included)

Live-action sources:
  tpb     https://apibay.org          (The Pirate Bay JSON; movies + TV, magnet included)
  eztv    https://eztvx.to            (TV JSON API by IMDb id; magnet included)
  xl720   https://www.xl720.com       (Chinese movie/TV index; magnet included)

Default sources: garden + tpb + xl720 + eztv. `--source all` adds nyaa + mikan.

Usage:
  python3 resource_search.py "<title>"
  python3 resource_search.py "<title>" --limit 5 --quality 2160p
  python3 resource_search.py "<title>" --source tpb --kind tv
  python3 resource_search.py "<title>" --source all
  python3 resource_search.py "<title>" --json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = "Mozilla/5.0 (compatible; hermes-resource-search/2.0)"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
TIMEOUT = 25

GARDEN = "https://api.animes.garden/resources"
NYAA = "https://nyaa.si/"
MIKAN = "https://mikanani.me/RSS/Search"
APITBAY = "https://apibay.org/q.php"
EZTV = "https://eztvx.to/api/get-torrents"
IMDB_SUGGEST = "https://v3.sg.media-imdb.com/suggestion/x/{}.json"
XL720 = "https://www.xl720.com/"

# Simplified-only enum values. Traditional variants ("動畫") return zero results.
GARDEN_TYPES = ["动画", "合集", "音乐", "日剧", "RAW", "漫画", "游戏", "特摄", "其他"]

# The Pirate Bay category ids: 200 = all video, 201 = movies, 205 = TV shows.
TPB_CATS = {"": "200", "movie": "201", "tv": "205"}

SPEC_PATTERNS = [
    ("res", r"\b(4320p|2160p|1440p|1080p|720p|480p|4K|8K)\b"),
    ("src", r"\b(BDRemux|BDRip|BDrip|BluRay|Blu-ray|WEB-DL|WEBRip|WebRip|Webrip|WEB|HDTV|DVDRip|UHDrip|UHDRip|AMZN|NF|DSNP)\b"),
    ("codec", r"\b(HEVC|x265|x264|H\.?264|H\.?265|AVC|AV1|VP9)\b"),
    ("depth", r"\b(8bit|10bit|12bit)\b"),
    ("sub", r"(简繁日|简繁|简体|繁体|简中|繁中|内嵌|外挂|内封|中字|国语|双语|中英双字)"
            r"|(?:CHS|CHT|Baha|B-Global|CR|NF|ABEMA|ViuTV|BILIBILI|HKTV)\b"),
]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:([A-Za-z0-9]{32,40})")


def fetch(url: str, params: dict | None = None, ua: str = UA) -> bytes:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, encoding='utf-8')}"
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
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


def from_unix(ts) -> str:
    try:
        return _dt.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return ""


def link_of(rec: dict) -> str:
    return rec.get("magnet") or rec.get("torrent") or rec.get("page") or ""


def record(title, link, fansub="", size=0, provider="", page="", date="",
           seeders=None, extra="", link_full=""):
    return {
        "title": WS_RE.sub(" ", title).strip(),
        "fansub": fansub,
        "size": size,
        "size_human": human_size(size) if size else "?",
        "specs": extract_specs(title),
        "link": link,
        "link_full": link_full or link,
        "provider": provider,
        "page": page,
        "date": normalize_date(date) or date,
        "seeders": seeders,
        "extra": extra,
    }


def plain(markup: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", TAG_RE.sub(" ", markup))).strip()


def tokens_of(keyword: str) -> list[str]:
    return [t for t in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", keyword.lower()) if t]


def matches_keyword(title: str, keyword: str) -> bool:
    """Client-side relevance guard.

    apibay answers an unmatched query with a 'popular uploads' fallback list, and xl720's
    search is fuzzy (it happily returns an unrelated Korean drama for 'House of the Dragon'),
    so both sources are filtered by token presence rather than trusted verbatim.
    """
    toks = tokens_of(keyword)
    if not toks:
        return True
    low = title.lower()
    return all(t in low for t in toks)


def compact_magnet(link: str) -> str:
    """Reduce a magnet URI to its btih hash — keeps report lines readable.

    The full URI (dn + tracker list) is preserved as `link_full` and is available in --json.
    """
    m = MAGNET_RE.search(link or "")
    return f"magnet:?xt=urn:btih:{m.group(1)}" if m else (link or "")


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
            seeders=int(item.findtext("nyaa:seeders", "0", ns) or 0),
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


# ----------------------------------------------------------------------------- tpb


def search_tpb(keyword: str, limit: int, kind: str = "") -> list[dict]:
    """The Pirate Bay via apibay.org. Live-action movies and TV, plus everything else.

    apibay answers an unmatched query with a 'popular uploads' fallback list instead of an
    empty array, so results are filtered client-side by token presence.
    """
    rows = json.loads(fetch(APITBAY, {"q": keyword, "cat": TPB_CATS.get(kind, "200")})
                      .decode("utf-8", "replace"))
    if not rows or (len(rows) == 1 and rows[0].get("name") == "No results returned"):
        return []
    toks = tokens_of(keyword)
    out = []
    for r in rows:
        title = html.unescape(r.get("name", ""))
        if toks and not matches_keyword(title, keyword):
            continue  # fallback noise, not a real match
        iname = r.get("info_hash", "")
        out.append(record(
            title=title,
            link=f"magnet:?xt=urn:btih:{iname}" if iname else "",
            size=int(r.get("size") or 0),
            provider="tpb",
            page=f"https://thepiratebay.org/description.php?id={r.get('id', '')}",
            date=from_unix(r.get("added")),
            seeders=int(r.get("seeders") or 0),
            extra=f"S:{r.get('seeders', '0')} L:{r.get('leechers', '0')}",
        ))
    out.sort(key=lambda r: -(r.get("seeders") or 0))
    return out[:limit] if limit else out


# ---------------------------------------------------------------------------- eztv


def imdb_series(title: str) -> tuple[str, str]:
    """Resolve a title to (numeric IMDb series id, canonical title).

    eztv wants the id without the 'tt' prefix. The canonical title is returned so callers can
    verify eztv's answer — eztv's own imdb_id lookup is unreliable for some ids (e.g. 0903747
    returns a completely different show), so results must be checked against the title.
    """
    try:
        data = json.loads(fetch(IMDB_SUGGEST.format(urllib.parse.quote(title))).decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - lookup is best-effort
        return "", ""
    for it in data.get("d", []):
        if str(it.get("id", "")).startswith("tt") and it.get("qid") in ("tvSeries", "tvMiniSeries"):
            return it["id"][2:], it.get("l", "")
    return "", ""


def search_eztv(keyword: str, limit: int, imdb: str = "", expect: str = "") -> list[dict]:
    """EZTV TV index, keyed by IMDb id. Pass `imdb` to skip the title lookup.

    Rows are filtered against the canonical IMDb title (or the caller's expectation), because
    eztv's imdb_id lookup returns unrelated shows for some ids. A tt-prefixed id must never be
    sent — eztv silently ignores it and dumps its whole 1M-torrent archive.
    """
    canon = ""
    if not imdb:
        imdb, canon = imdb_series(keyword)
    if not imdb:
        return []
    imdb = imdb[2:] if imdb.lower().startswith("tt") else imdb
    expect = expect or canon or keyword
    if any(ord(c) > 127 for c in expect):  # CJK expectation: no reliable client-side filter
        expect = ""
    data = json.loads(fetch(EZTV, {"imdb_id": imdb, "limit": max(limit * 4, 20), "page": 1})
                      .decode("utf-8", "replace"))
    rows = data.get("torrents") or []
    rows.sort(key=lambda t: -(int(t.get("date_released_unix") or 0)))
    out = []
    for t in rows:
        title = t.get("title") or t.get("filename", "")
        if expect and not matches_keyword(title, expect):
            continue  # eztv answered with the wrong series
        ih = t.get("hash", "")
        season, ep = t.get("season"), t.get("episode")
        tag = f"S{int(season):02d}E{int(ep):02d}" if str(season).isdigit() and str(ep).isdigit() else ""
        full = t.get("magnet_url") or (f"magnet:?xt=urn:btih:{ih}" if ih else "")
        out.append(record(
            title=title,
            link=compact_magnet(full),
            link_full=full,
            size=int(t.get("size_bytes") or 0),
            provider="eztv",
            page=f"https://eztvx.to/{(t.get('filename') or '').replace(' ', '-')}",
            date=from_unix(t.get("date_released_unix")),
            seeders=int(t.get("seeds") or 0),
            extra=f"S:{t.get('seeds', 0)} L:{t.get('peers', 0)}" + (f" {tag}" if tag else ""),
        ))
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- xl720


def _xl720_detail(title: str, url: str) -> str | None:
    """Fetch one detail page; None on failure so one dead page can't kill the run."""
    try:
        return fetch(url, ua=BROWSER_UA).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return None


def search_xl720(keyword: str, limit: int) -> list[dict]:
    """迅雷电影天堂 — Chinese-language movie/TV index. Search page -> detail page magnet.

    Titles carry the useful metadata (year / country / quality / subtitle tags); the detail
    page carries the magnet(s), the 文件大小 field and the 发布 date. Episode-based series
    publish one magnet per episode, so the first magnet is the delivered link and the total
    count is reported alongside it.
    """
    text = fetch(XL720, {"s": keyword}, ua=BROWSER_UA).decode("utf-8", "replace")
    hits, seen = [], set()
    for m in re.finditer(
            r'<a[^>]+href="(https?://www\.xl720\.com/thunder/(\d+)\.html)"[^>]*>([\s\S]{1,300}?)</a>',
            text, re.I):
        title = plain(m.group(3))
        if not title or "查看详情" in title or m.group(2) in seen:
            continue
        if not matches_keyword(title, keyword):
            continue  # xl720 search is fuzzy — drop unrelated hits
        seen.add(m.group(2))
        hits.append((m.group(2), title, m.group(1)))
        if len(hits) >= max(limit, 1):
            break

    out = []
    with ThreadPoolExecutor(max_workers=min(4, max(len(hits), 1))) as ex:
        pages = list(ex.map(lambda h: _xl720_detail(h[1], h[2]), hits))
    for (post_id, title, url), page in zip(hits, pages):
        if page is None:
            out.append(record(title=title, link=url, provider="xl720", page=url,
                              extra="详情页读取失败，仅页面链接"))
            continue
        fulls = list(dict.fromkeys(
            html.unescape(x) for x in
            re.findall(r'magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}[^"\'\s<>]*', page)))
        hashes = MAGNET_RE.findall(page)
        size_m = re.search(r"文件大小\u3000?\s*([\d.]+\s*[KMGT]?i?B)", page)
        date_m = re.search(r"发布[：:]\s*(\d{4})-(\d{1,2})-(\d{1,2})", page)
        date = (f"{date_m.group(1)}-{int(date_m.group(2)):02d}-{int(date_m.group(3)):02d}"
                if date_m else "")
        if len(hashes) > 1:
            extra = f"共{len(hashes)}个磁力(按集/分段)"
        elif not hashes:
            extra = "该详情页无磁力，仅页面链接"
        else:
            extra = ""
        out.append(record(
            title=re.sub(r"[《》]", "", title),
            link=compact_magnet(fulls[0]) if fulls else url,
            link_full=fulls[0] if fulls else url,
            size=parse_size(size_m.group(1)) if size_m else 0,
            provider="xl720",
            page=url,
            date=date,
            extra=extra,
        ))
    return out


# ------------------------------------------------------------------------ pipeline

SOURCES = {
    "garden": search_garden,
    "nyaa": search_nyaa,
    "mikan": search_mikan,
    "tpb": search_tpb,
    "eztv": search_eztv,
    "xl720": search_xl720,
}
ANIME_SOURCES = ["garden", "nyaa", "mikan"]
LIVE_ACTION_SOURCES = ["tpb", "eztv", "xl720"]
# The default set. garden alone covers animation well but says nothing about live action
# (e.g. a 'Game of Thrones' query resolves to season 8 reposts only), so the two live-action
# indexes that answer reliably are queried every time. Add nyaa/mikan with --source all.
DEFAULT_SOURCES = ["garden", "tpb", "xl720", "eztv"]


def dedupe(records: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in records:
        key = (r["link"].split("btih:")[-1].lower() if "btih:" in r["link"]
               else r["title"][:60].lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def run_source(src: str, keyword: str, limit: int, args, errors: list[str]) -> list[dict]:
    try:
        if src == "garden":
            return search_garden(keyword, limit, args.type)
        if src == "tpb":
            return search_tpb(keyword, limit, args.kind)
        if src == "eztv":
            return search_eztv(keyword, limit, args.imdb)
        return SOURCES[src](keyword, limit)
    except urllib.error.URLError as e:
        errors.append(f"{src}: network error ({e})")
    except ET.ParseError as e:
        errors.append(f"{src}: unparsable feed ({e})")
    except Exception as e:  # noqa: BLE001 - report, never crash the agent run
        errors.append(f"{src}: {type(e).__name__}: {e}")
    return []


def render(records: list[dict], keyword: str, sources: list[str]) -> str:
    if not records:
        return (f"No records found for {keyword!r} (sources: {', '.join(sources)}).\n"
                "Try a shorter keyword — on the anime indexes matching is an ordered substring, "
                "so extra words in the wrong order produce zero hits. For live action, try the "
                "original-language title as well as the English one (--source tpb / xl720), and "
                "remember CJK titles are generally not indexed on TPB.")
    lines = [f"## Results for {keyword!r} — {len(records)} record(s)",
             f"_sources: {', '.join(sources)}_", ""]
    for i, r in enumerate(records, 1):
        head = f"{i}. {r['title']}"
        meta = " | ".join(x for x in (r["fansub"], r["specs"], r["size_human"],
                                      r.get("extra", ""), r["provider"], r["date"]) if x)
        lines.append(head)
        if meta:
            lines.append(f"   {meta}")
        lines.append(f"   link: {r['link']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Search public release catalogs: animation (garden/nyaa/mikan) "
                    "and live action (tpb/eztv/xl720).")
    ap.add_argument("keyword", nargs="+", help="Search term. Use the title order that appears in release names.")
    ap.add_argument("--source", action="append", choices=sorted(SOURCES) + ["all"], default=None,
                    help="Source to query (repeatable). 'all' = every source (adds nyaa + mikan). "
                         "Default: garden + tpb + xl720 + eztv.")
    ap.add_argument("--limit", type=int, default=8, help="Max results per source (default 8).")
    ap.add_argument("--type", default="", help=f"garden only. One of: {', '.join(GARDEN_TYPES)}")
    ap.add_argument("--kind", default="", choices=["", "movie", "tv"],
                    help="tpb only: restrict to movies (201) or TV shows (205). Default: all video.")
    ap.add_argument("--imdb", default="", help="eztv only: numeric IMDb series id (e.g. 0944947) to skip title lookup.")
    ap.add_argument("--quality", default="", help="Post-filter: keep titles matching this token, e.g. 1080p / 2160p / BDRip.")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = ap.parse_args()

    keyword = " ".join(args.keyword).strip()
    if args.source is None:
        sources = list(DEFAULT_SOURCES)
    elif "all" in args.source:
        sources = ANIME_SOURCES + LIVE_ACTION_SOURCES
    else:
        sources = list(dict.fromkeys(args.source))

    records: list[dict] = []
    errors: list[str] = []
    queried = list(sources)
    # Sources are independent HTTP endpoints — query them concurrently so the run costs the
    # slowest source (garden, Cloudflare) rather than the sum of all of them.
    if len(queried) > 1:
        per_source: dict[str, list[dict]] = {}
        with ThreadPoolExecutor(max_workers=len(queried)) as ex:
            futures = {ex.submit(run_source, src, keyword, args.limit, args, errors): src
                       for src in queried}
            for fut in as_completed(futures):
                per_source[futures[fut]] = fut.result()
        for src in queried:
            records += per_source.get(src, [])
    else:
        for src in queried:
            records += run_source(src, keyword, args.limit, args, errors)

    records = dedupe(records)
    if args.quality:
        needle = args.quality.lower()
        records = [r for r in records if needle in r["title"].lower()]
    records = records[: max(args.limit, 1) * len(queried)]

    if args.json:
        print(json.dumps({"keyword": keyword, "sources": queried,
                          "errors": errors, "records": records},
                         ensure_ascii=False, indent=2))
    else:
        print(render(records, keyword, queried))
        for err in errors:
            print(f"[warn] {err}", file=sys.stderr)
    return 0 if records else 1


if __name__ == "__main__":
    sys.exit(main())
