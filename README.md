# hermes-resource-search

A [Hermes Agent](https://hermes-agent.nousresearch.com/docs) skill that looks up anime
release catalog records — TV episodes, films/剧场版, OVAs, batch packs, music — across three
public indexes, and reports each record's link field.

No API keys, no accounts, no Python packages beyond the standard library.

## What it returns

One record per matching release, with: title, subtitle group, specs (resolution / source /
codec / subtitle form), size, date, and the release's link field.

```
1. <release title, as published by the group>
   <subtitle group> | <specs> | <size> | <tracker> | <date>
   link: <the record's link field>
```

## Sources

| source | Coverage | Link field |
|---|---|---|
| `garden` (default) | [AnimeGarden](https://github.com/yjl9903/AnimeGarden) — aggregates dmhy + bangumi.moe + mikan + moe | full `magnet:` URI |
| `nyaa` | [nyaa.si](https://nyaa.si) anime categories | `magnet:` built from the feed infohash |
| `mikan` | [mikanani.me](https://mikanani.me) | `.torrent` download URL |

## Install

All four routes below install the same four files (`SKILL.md`, `scripts/resource_search.py`,
`references/sources.md`, `references/strict-model-compatibility.md`). Routes are ordered by
how reliable they are in practice.

### Option 1 — direct URL install (recommended)

```bash
# latest
hermes skills install https://raw.githubusercontent.com/SoledadAki/hermes-resource-search/main/skills/hermes-resource-search/SKILL.md --yes

# pinned to a release tag
hermes skills install https://raw.githubusercontent.com/SoledadAki/hermes-resource-search/v1.0.0/skills/hermes-resource-search/SKILL.md --yes
```

One HTTP fetch plus the referenced support files. No GitHub account or token needed.
Verified: scan verdict `SAFE`, install allowed without `--force`.

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

**Programmatic use** — `--json` gives `records[].link`, `records[].size`, `records[].specs`
for scripts and cron jobs. Uses only what the skill already needs (python3), so no extra
tooling:

```bash
python3 scripts/resource_search.py "<series>" --limit 5 --json \
  | python3 -c "import sys,json; [print(r['link']) for r in json.load(sys.stdin)['records']]"
```

(`... | jq -r '.records[].link'` works identically if you have jq installed.)

## Running the script directly

The skill drives a stdlib-only script. Invoked directly:

```bash
cd skills/hermes-resource-search

python3 scripts/resource_search.py "<series name>" --limit 5
python3 scripts/resource_search.py "<series name>" --limit 8 --quality 2160p
python3 scripts/resource_search.py "<romaji title>" --source garden --source nyaa
python3 scripts/resource_search.py "<series name>" --json
```

Two things that surprise people, both verified against the live API:

- **Keyword matching is an ordered substring match, not a bag of words.** `<series> <arc>`
  finds releases; `<arc> <series>` returns nothing, and so does `<series> 1080p` — the tokens
  aren't adjacent in any title. Search a short distinctive fragment, filter locally.
- **`--type` takes simplified Chinese only** — `动画` `合集` `音乐` `日剧` `RAW` `漫画` `游戏`
  `特摄` `其他`. The traditional form `動畫` returns zero records.

## Coverage

Anime. Live-action films and TV series are effectively not in these indexes — AnimeGarden
carries anime trackers, and Nyaa's live-action section is thin.

## Strict models

`references/strict-model-compatibility.md` documents how tool provenance changes the
behaviour of models that apply output-side filtering (GPT-family), with the measured test
matrix and the setups that make the difference. Read it if the skill loads but results come
back with their link fields stripped.

## MCP alternative

The upstream catalog also runs an MCP server, which makes the tool available in every
session without installing a skill:

```yaml
mcp_servers:
  anime-garden:
    url: "https://api.animes.garden/mcp"
```

Requires the `mcp` Python package; see the `native-mcp` skill in Hermes for the full
configuration reference. The skill route is the one whose own text stays neutral — the
upstream MCP tool description does mention torrents.

## License

MIT — see [LICENSE](LICENSE).
