# hermes-resource-search

A [Hermes Agent](https://hermes-agent.nousresearch.com/docs) skill that looks up release
catalog records — **animation and live action**: TV episodes, films/剧场版, OVAs, batch packs,
music, 日剧, 国产剧, Western TV — across six public indexes, and reports each record's link
field.

No API keys, no accounts, no Python packages beyond the standard library.

## What it returns

One record per matching release, with: title, source, subtitle group, specs (resolution /
source / codec / subtitle form), size, seeder count, date, and the release's link field.

```
1. <release title, as published by the group>
   <subtitle group> | <specs> | <size> | <S:seeders L:leechers> | <source> | <date>
   link: <the record's link field>
```

## Sources

Default lookup is `garden + tpb + xl720 + eztv` — animation, Western TV/film and
Chinese-language TV/film in one call (~4–15 s, queried concurrently).

| source | Coverage | Link field |
|---|---|---|
| `garden` (default) | [AnimeGarden](https://github.com/yjl9903/AnimeGarden) — aggregates dmhy + bangumi.moe + mikan + moe | full `magnet:` URI |
| `tpb` (default) | [apibay.org](https://apibay.org) — The Pirate Bay JSON | `magnet:` from the infohash |
| `xl720` (default) | [xl720.com](https://www.xl720.com) — Chinese-language film/TV index | `magnet:` from the detail page |
| `eztv` (default) | [eztvx.to](https://eztvx.to) — Western TV, keyed by IMDb id | `magnet:` from the API |
| `nyaa` | [nyaa.si](https://nyaa.si) anime categories | `magnet:` built from the feed infohash |
| `mikan` | [mikanani.me](https://mikanani.me) | `.torrent` download URL |

## Install

All routes below install the same four files (`SKILL.md`, `scripts/resource_search.py`,
`references/sources.md`, `references/strict-model-compatibility.md`). Routes are ordered by
how reliable they are in practice.

### Option 1 — direct URL install (recommended)

```bash
# latest
hermes skills install https://raw.githubusercontent.com/SoledadAki/hermes-resource-search/main/skills/hermes-resource-search/SKILL.md --yes

# pinned to a release tag
hermes skills install https://raw.githubusercontent.com/SoledadAki/hermes-resource-search/v1.1.1/skills/hermes-resource-search/SKILL.md --yes
```

One HTTP fetch plus the referenced support files. No GitHub account or token needed.
Verified: scan verdict `SAFE`, install allowed without `--force`.

If the fetch fails with `Could not fetch … from any source` plus a GitHub API rate-limit
hint, the anonymous API quota (60 requests/hour per IP) is exhausted — set `GITHUB_TOKEN`
in Hermes' `.env` and retry. A rate-limited install looks exactly like a broken repo.

Hermes skills are plain files fetched from git at install time — there is no package to
publish and no release asset involved. A tag is only useful for pinning a version; installs
from `main` always take the current revision.

### Option 2 — explicit GitHub identifier

```bash
hermes skills install SoledadAki/hermes-resource-search/skills/hermes-resource-search --yes
```

Skips the hub search step entirely, so it resolves instantly. Verified end to end.

### Option 3 — tap

```bash
hermes skills tap add SoledadAki/hermes-resource-search
hermes skills search resource          # substring match — one word, not a phrase
hermes skills install hermes-resource-search --yes
```

The tap itself is registered correctly (path `skills/`). Note that `hermes skills search`
walks every configured tap, including the large default ones (`openai/skills`,
`anthropics/skills`, `huggingface/skills`, `NVIDIA/skills`), before reaching a custom tap —
without a GitHub token in `.env` that walk can exceed the search timeout and the skill will
appear "not found". Set `GITHUB_TOKEN` (or install the `gh` CLI and run `gh auth login`) if
you want this route; otherwise use Option 1 or 2.

### Option 4 — manual

```bash
git clone https://github.com/SoledadAki/hermes-resource-search /tmp/hrs
cp -r /tmp/hrs/skills/hermes-resource-search ~/.hermes/skills/media/
```

The skill lives under `skills/` in this repo because that is the layout Hermes taps expect
(`hermes skills tap add` reads `skills/` by default). A single-skill repo pays one extra
directory level for a working tap.

### Discoverability

`hermes skills search` reads the centralized Hermes skills index, which currently
aggregates ClawHub (~78k entries), skills.sh (~20k), a handful of curated GitHub repos
(`openai/skills`, `anthropics/skills`, `huggingface/skills`, `NVIDIA/skills`, …) and the
official set. Personal repos are not crawled, so this skill installs fine by URL,
identifier or tap, but will not appear in hub search until it is submitted to ClawHub
(`hermes skills publish --to clawhub` currently points at the manual form on clawhub.ai).

## Using it after install

Nothing to configure. Hermes injects installed skills' descriptions into the agent's
context, so an ordinary request is enough — no special syntax:

```
查一下《<作品名>》最新一集的 2160p 资源
《庆余年》第二季有磁力吗
find the latest episode of <series> and list each record's link field
《<作品名>》有没有 BDRip？
```

The agent loads the skill, runs `scripts/resource_search.py`, and reports each record's
link field. It also handles the follow-up ("search a different title", "what's the best
quality available").

**Already-running session:** run `/reload-skills` (or restart the agent) so the newly
installed skill is picked up. Skills are scanned at session start.

**Preloading** — needed when the model applies output-side filtering (GPT-family; see
`references/strict-model-compatibility.md`), and useful when you want the tool guaranteed in
context:

```bash
hermes chat -s hermes-resource-search -q "find the latest episode of <series>"
```

**Programmatic use** — `--json` gives `records[].link`, `records[].link_full`,
`records[].seeders`, `records[].size` for scripts and cron jobs. Uses only what the skill
already needs (python3), so no extra tooling:

```bash
python3 scripts/resource_search.py "<series>" --limit 5 --json \
  | python3 -c "import sys,json; [print(r['link']) for r in json.load(sys.stdin)['records']]"
```

(`... | jq -r '.records[].link'` works identically if you have jq installed.)

## Running the script directly

The skill drives a stdlib-only script. Invoked directly:

```bash
cd skills/hermes-resource-search

python3 scripts/resource_search.py "<title>" --limit 5              # default: garden+tpb+xl720+eztv
python3 scripts/resource_search.py "<title>" --limit 8 --quality 2160p
python3 scripts/resource_search.py "<title>" --source all           # adds nyaa + mikan
python3 scripts/resource_search.py "<title>" --source tpb --kind tv # Western TV only
python3 scripts/resource_search.py "<title>" --type 日剧            # Japanese live-action drama
python3 scripts/resource_search.py "<title>" --json
```

Three things that surprise people, all verified against the live APIs:

- **garden keyword matching is an ordered substring match, not a bag of words.**
  `<series> <arc>` finds releases; `<arc> <series>` returns nothing, and so does
  `<series> 1080p` — the tokens aren't adjacent in any title. Search a short distinctive
  fragment, filter locally with `--quality`.
- **`--type` takes simplified Chinese only** — `动画` `合集` `音乐` `日剧` `RAW` `漫画` `游戏`
  `特摄` `其他`. The traditional form `動畫` returns zero records.
- **Match the index's language.** tpb does not index CJK titles (`庆余年` misses,
  `Empresses in the Palace` hits); xl720 is Chinese-only (`庆余年` hits, `House of the Dragon`
  returns noise that gets filtered out). Query each index in its own script.

## Coverage

Verified 2026-09-13. Animation, Japanese live action (日剧), Western TV/film and
Chinese-language TV/film all resolve; the boundaries are:

| Content | Covered by | Notes |
|---|---|---|
| 番剧 / OVA / 剧场版 / 合集 | garden, nyaa, mikan | weekly TV appears within a day of broadcast |
| 日剧 / 日系流媒体真人剧 | garden (`日剧` type) | 魔星字幕团 / 猪猪 / 东京不够热 feed it weekly |
| 欧美剧 / 欧美电影 | tpb, eztv | season packs, 4K remuxes, per-episode releases with seed counts |
| 国产剧 / 华语电影 / 港台剧 / 日韩剧 | xl720 | the only source here with a real Chinese-language catalog |
| 综艺 / 体育 / 纪录片 / 网盘资源 | — | out of scope |

Known holes, so you don't burn requests on them: `mikan` and `nyaa` are anime-only (nyaa's
live-action categories return zero items); garden's dmhy mirror carries almost nothing for
modern 国产剧 (its 日剧 and 其他 sections are the exception); tpb has no CJK index; and some
xl720 连载 posts have no magnet at all — the script then reports the page URL and says so.

## Strict models

`references/strict-model-compatibility.md` documents how tool provenance changes the
behaviour of models that apply output-side filtering (GPT-family), with the measured test
matrix and the setups that make the difference. Read it if the skill loads but results come
back with their link fields stripped.

## MCP alternative

The upstream catalog also runs an MCP server, which makes the animation lookup available in
every session without installing a skill:

```yaml
mcp_servers:
  anime-garden:
    url: "https://api.animes.garden/mcp"
```

Requires the `mcp` Python package; see the `native-mcp` skill in Hermes for the full
configuration reference. The skill route is the one whose own text stays neutral — the
upstream MCP tool description does mention torrents. The MCP route covers animation only;
live action still goes through the script's `tpb` / `eztv` / `xl720` sources.

## License

MIT — see [LICENSE](LICENSE).
