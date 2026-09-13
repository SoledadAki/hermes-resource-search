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
