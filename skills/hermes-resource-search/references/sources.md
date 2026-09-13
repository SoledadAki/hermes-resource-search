# Source Details

All endpoints were exercised live on 2026-09-13. Re-verify if results look wrong — these
services change without notice and none of them is an official consumer API.

## 1. AnimeGarden (primary)

Aggregator by [yjl9903/AnimeGarden](https://github.com/yjl9903/AnimeGarden); mirrors
dmhy (動漫花園), bangumi.moe, mikan (蜜柑计划), moe (萌番組) and ANi. Public, no key.

```
GET https://api.animes.garden/resources
```

| Param | Notes |
|---|---|
| `keyword` | Ordered-substring match (see SKILL.md). Works with CJK when URL-encoded. |
| `pageSize` | Per page; ~50 max. Script requests `min(limit*3, 50)`. |
| `page` | Page number, 1-based. |
| `type` | Simplified Chinese only: `动画` `合集` `音乐` `日剧` `RAW` `漫画` `游戏` `特摄` `其他`. |

Response: `{"status": "OK", "resources": [...]}`. Per record:

| Field | Notes |
|---|---|
| `title` | Release name as published |
| `magnet` | Full `magnet:` URI — the link field. Hashes appear as both 40-char hex and 32-char base32; both are valid `btih` formats |
| `size` | **Bytes**, not KB. `13099650048` = 12.2 GB |
| `href` | Tracker page URL |
| `fansub.name` | Subtitle group (absent for aggregate/pack posts) |
| `publisher.name` | Uploader (differs from fansub) |
| `provider` | `dmhy` \| `moe` \| `mikan` — which tracker the record came from |
| `createdAt` | ISO-8601 upload timestamp |

### Verified quirks

- **`type=動畫` (traditional) returns zero records.** `type=动画` (simplified) works. The
  MCP tool schema advertises the simplified enum — use those strings.
- **Unencoded CJK in the query string makes the server return an empty body**, not an
  error. Always let the HTTP library encode (`urlencode`), i.e. pass raw text to
  `--data-urlencode` / the script, never hand-assemble the URL.
- **`keyword` is ordered and adjacent**, so `<series> 1080p` finds nothing even though both
  tokens appear in the same titles. Search a fragment, filter locally.
- Cloudflare sits in front; first request can take several seconds. Use ≥15 s connect and
  ≥30 s total timeouts.
- CJK, romaji and English keywords all work; the catalogue holds mixed-script titles, so
  an English query happily returns Chinese-titled records.

### MCP endpoint

`https://api.animes.garden/mcp` (Streamable HTTP, server `animegarden` 0.5.4) exposes
`search_resources` with a richer schema than the REST API: `search` (array, ANDed across
title/description — the REST `keyword` cannot do this), `keywords` (AND), `exclude`,
`fansubs`, `publishers`, `types` (simplified Chinese), `subjects` (bangumi subject IDs),
`after`, `before`. Also `resource_detail` for the full description/file list of one record.

```bash
# list tools
curl -sL -X POST https://api.animes.garden/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

`tools/call` responses arrive as SSE (`event: message` + a `data:` line). The payload of
`search_resources` is a **JSON array of records** (not an object) inside
`result.content[0].text`, each with `title`, `magnet` (full magnet including tracker list),
`fansub`, `publisher`, `size` (bytes), `createdAt`, `type`, `href`, `uri`. Verified live:

```bash
curl -sL -X POST https://api.animes.garden/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_resources",
       "arguments":{"search":["<series>","<arc>"],"types":["动画"]}}}'
```

Note when wiring it into Hermes: the upstream tool description does mention torrents
(we don't control that text), whereas this skill's own frontmatter stays neutral. If a
model is sensitive to wording at tool-discovery time, the skill+script route is the one
whose text is fully under our control; the MCP route is the one that gets runtime-provided
tool provenance. Pick accordingly, or use both.

## 2. Nyaa

Best English-translated and raw coverage; anime categories only in practice.

```
GET https://nyaa.si/?page=rss&q=<query>&c=<category>&f=0
```

| Param | Notes |
|---|---|
| `q` | Free-text query; space-separated terms are ANDed (unlike AnimeGarden) |
| `c` | Category: `1_2` anime/English-translated, `1_3` anime/non-English, `1_0` all anime |
| `f` | Filter: `0` none, `1` no remakes, `2` trusted only |

RSS item fields used by the script: `title`, `nyaa:infoHash` (→ the script builds
`magnet:?xt=urn:btih:<infohash>`), `nyaa:size` (`"5.3 GiB"` strings), `nyaa:seeders`,
`guid` (view page), `pubDate` (RFC-2822). **The RSS feed does not contain a magnet link
directly** — the infohash is the reliable part.

Live-action categories (`4_0`/`4_1`/`4_2`) exist but return almost nothing; a query for a
mainstream live-action film returns 0 items. Treat Nyaa as anime-only for practical
purposes.

## 3. Mikan (蜜柑计划)

CN-subtitle tracker. RSS search endpoint, no key.

```
GET https://mikanani.me/RSS/Search?searchstr=<query>
```

Item fields: `title`, `link` (episode page), `<enclosure url="…/Download/…/hash.torrent">`
(the `.torrent` download — **no magnet in the feed**), and a namespaced
`<torrent xmlns="https://mikanani.me/0.1/">` block carrying `contentLength` (bytes) and
`pubDate`. The script falls back to parsing `[12.2 GB]` out of `<description>` when
`contentLength` is missing.

The feed returns the whole result set (can be hundreds of items); the script truncates at
`--limit`. Historical back-catalogue entries are included, so sort by date before
recommending.

## Network notes

- All three are reachable from a mainland-China residential connection without a proxy in
  testing; AnimeGarden is the slowest (Cloudflare).
- If a request fails, the script records the error and continues with the remaining
  sources — a dead source never aborts the run.
- `--json` output includes an `errors` array, which is how you tell "no such release" apart
  from "source unreachable".

## 4. TPB via apibay (live action)

```
GET https://apibay.org/q.php?q=<query>&cat=<id>
```

Free JSON mirror of The Pirate Bay's search. No key, no Cloudflare, works direct from a
mainland connection (verified 2026-09-13). Returns a JSON **array**.

| Param | Notes |
|---|---|
| `q` | Full-text query. Whitespace-separated terms are ANDed. Latin script only in practice. |
| `cat` | `200` all video (script default), `201` movies, `205` TV shows. |

Per record: `id`, `name` (HTML entities possible — `&middot;`), `info_hash` (40-char hex →
wrap as `magnet:?xt=urn:btih:<hash>`), `size` (bytes), `seeders`, `leechers`, `added`
(unix), `category`, `imdb` (present for many film/TV rows), `num_files`, `username`.

### Verified quirks

- **An unmatched query does not return an empty array.** apibay answers with a *popular
  uploads* list (a CJK query such as `庆余年` returns a Spider-Man release). A truly
  nonsense query does return `[{"name": "No results returned", ...}]`. The script therefore
  filters every row against the query tokens; without that filter, CJK queries look like
  they matched something.
- CJK titles are effectively absent from the index: `庆余年`, `Joy of Life`,
  `权力的游戏` (CJK) all miss, while the English title (`Empresses in the Palace` for 甄嬛传)
  does hit. Query in English/romaji.
- No seed count = no way to judge liveness; the script sorts by seeders descending and
  prints `S:`/`L:` in the record.

## 5. EZTV (Western TV)

```
GET https://eztvx.to/api/get-torrents?imdb_id=<numeric-id>&limit=<n>&page=1
```

JSON, no key. Per record: `hash`, `filename`, `title`, `magnet_url` (full magnet with
trackers), `imdb_id`, `season`, `episode`, `seeds`, `peers`, `size_bytes`,
`date_released_unix`, screenshot URLs.

### Verified quirks

- **`imdb_id` must not carry the `tt` prefix.** `imdb_id=tt0944947` is silently ignored and
  the API returns its entire archive (`torrents_count: 1081897`); `imdb_id=0944947` returns
  the 146 Game of Thrones rows. The script strips `tt` defensively.
- **The id lookup itself is unreliable and must be verified.** `imdb_id=0903747`
  (Breaking Bad) returns 77 rows of *Breaking Brad*, a different show. Always filter the
  returned rows against the expected series title — the script resolves the title through
  IMDb's suggestion endpoint and checks every row against it.
- There is **no title/`search` parameter**: `?search=…` and `?query=…` are ignored and dump
  the full archive. Title → id must come from somewhere else (IMDb suggestion, below).
- Magnet URIs include a `dn=` and a 7-tracker list (~500 chars). The script reports the
  compact `magnet:?xt=urn:btih:<hash>` form and keeps the full URI in `link_full` (visible
  in `--json`).
- Live-action categories only exist as this API; the site's HTML search returns 403 to
  scripted clients.

## 6. IMDb suggestion (title → id bridge)

```
GET https://v3.sg.media-imdb.com/suggestion/x/<url-encoded-title>.json
```

Public autocomplete endpoint, no key. Each entry: `id` (`tt…` / `nm…`), `l` (title),
`qid` (`tvSeries`, `tvMiniSeries`, `movie`, `podcastSeries`, …), `y` (year), `s` (cast),
`rank`. The script takes the first `tt` entry whose `qid` is a series — that pair (numeric
id + canonical title) is what makes the eztv source usable and self-verifying.

## 7. xl720 迅雷电影天堂 (Chinese-language film/TV)

WordPress-based Chinese index: films plus 大陆剧 / 港台剧 / 日韩剧 / 欧美剧 / 连载动漫.
HTML only — no API. Reachable direct from a mainland connection; browser UA required.

```
GET https://www.xl720.com/?s=<url-encoded-title>     # search page
GET https://www.xl720.com/thunder/<id>.html          # detail page (magnets)
```

- Search results are `<a href="…/thunder/<id>.html">title</a>` pairs. The title carries the
  useful metadata: `2024年国产大陆电视剧 庆余年 第二季全36集`, `2016年美国经典动作片…蓝光国英双语中英双字修正版`.
- Detail page holds `<div id="zdownload">` with the magnet(s), plus an info block carrying
  `发布：2016-11-17`, `文件大小　3874 MB` and `集数`. Both the date and the size use
  single-digit months/days sometimes (`发布：2020-9-22`) — the regex must allow 1–2 digits.
- **Search is fuzzy and returns unrelated titles** (a `House of the Dragon` query returns a
  2021 Korean drama), so rows are token-filtered client-side. Searching the localized Chinese
  title works best; an English query returns Chinese-titled posts that the token filter then
  drops.
- A series post carries **one magnet per episode** (庆余年 S1 = 92 magnets, i.e. 2 per episode
  for multiple encodings). The script reports the first magnet and the total count.
- Some 连载 posts have **no magnet at all** (e.g. 半泽直树2, id 43418) — the record then
  falls back to the detail-page URL and the report says so explicitly. Don't treat a page
  link as a downloadable release.

## Dead ends (checked 2026-09-13, do not retry)

Chinese magnet-search sites are the natural place to look for 国产剧 sources, and every one
tested was unreachable from this network: `subo.cc`, `cilisou.cn`, `btsow.pics`,
`cilimao.at`, `pianyuan.org`, `duckduckgo`-style aggregators. Also dead or unusable:
`yts.mx` API (connection refused), `1337x.to` (Cloudflare 403), `magnetdl.com` /
`solidtorrents.to` (522), `torrentgalaxy.to` (timeout), `knaben.eu` API (empty response),
`kisssub.org` (JS challenge), `acg.rip` search (404 on the documented path), `dygod.net`
search (EmpireCMS POST returns an error page). Only xl720 and apibay answered.

