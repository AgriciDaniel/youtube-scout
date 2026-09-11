---
name: scout
description: Scout a topic on YouTube. Searches YouTube Data API v3 for the most relevant videos, ranks them by views (or engagement, likes, recency, momentum, breakout), and writes a research workbook in the OWT-Social-Ads layout with Videos, Channels, and Summary sheets, plus optional Comments and Transcripts (hooks, replay hotspots) sheets. Can also append into an existing sheet. Use when the user says "scout <topic>", wants a spreadsheet of top YouTube videos on a topic, wants creator or hook research, or wants YouTube rows added to their social ads sheet.
argument-hint: "<topic> [--max 50] [--since month] [--length short] [--sort views] [--comments] [--hooks] [--into file.xlsx] [--download] [--dry-run]"
allowed-tools: Bash, Read
user-invocable: true
---

# /scout

One topic in, one ranked research workbook out. The script does the whole job; your role is
to run it with the right flags, then relay the result.

## Step 1: Run

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/scout.py" <topic words> [flags]
```

Pass the user's topic as words after the script (quotes optional, the script joins them).
The API key is read from `YOUTUBE_API_KEY` in the environment, then from the file named by
`SCOUT_ENV_FILE`, then `~/.config/scout/.env`, then `./.env`. If the user keeps keys in another
env file, load it into the environment first (for example `set -a; . <keyfile>; set +a` in the
same Bash call) rather than copying the key anywhere. Never echo the key. The run prints
progress lines to stderr; a full run with `--hooks` on 50 videos takes a few minutes because
yt-dlp probes each video, so allow a long Bash timeout.

If the script reports that openpyxl is missing, run once:

```bash
pip install -r "${CLAUDE_SKILL_DIR}/requirements.txt" --quiet
```

## Flags

| Flag | Default | Meaning |
|---|---|---|
| `--max N` | 50 | Videos to collect, 1 to 200. Each block of 50 costs 100 quota units and one of the 100 daily search calls. |
| `--since` | any | `hour`, `today`, `week`, `month`, `year`, `any` |
| `--length` | any | `short` (under 4 min), `medium` (4 to 20), `long` (over 20) |
| `--sort` | views | `views`, `engagement`, `likes`, `recent`, `momentum` (views per day), `breakout` (views per subscriber) |
| `--comments [N]` | off | Top N comments per video (default 20) into a Comments sheet, plus Top Comment on each video row. 1 quota unit per video. |
| `--hooks [SECONDS]` | off | yt-dlp probe per video, no quota: Hook (first SECONDS of captions, default 15), Vertical, FPS, Most Replayed s, Replay Hotspots, Chapters, and a Transcripts sheet with the full transcript. |
| `--out PATH` | `./scout-<topic>-<date>.xlsx` | Write a new workbook |
| `--into PATH` | off | Append into an existing workbook's `Videos` sheet, skip Video IDs already present, re-sort. Comments and Transcripts sheets are created or extended there too. A timestamped `.backup-` copy is written next to the file first. The file must be closed in Excel. |
| `--download` | off | Download mp4s and thumbnails with yt-dlp into `./downloads/`, fill Local File and Thumbnail File |
| `--dry-run` | off | Fetch and print only |
| `--json` | off | Also print rows as JSON |

Mapping user phrasing: "this month" means `--since month`, "shorts" means `--length short`,
"what are people saying" or "objections" means `--comments`, "hooks", "scripts", "openers",
"transcripts" or "most replayed" means `--hooks`, "creators to reach out to" means look at the
Channels sheet, "add to my sheet" means `--into <that file>`. "Everything" or "full research"
means `--comments --hooks`. When the user names no file and no flags, use the defaults.

## Step 2: Report

The script prints a top-10 table to stdout and status lines to stderr. Relay:

- The output path and the sheet list (or rows added and skipped for `--into`).
- The top-10 table as-is in a code block.
- Quota units used, and any `warning:` lines (a few yt-dlp probe failures are normal).
- Two or three observations worth acting on, read from the Summary sheet and the table: for
  example the Shorts share, a breakout creator (high Views/Sub), or a recurring hook pattern.

Mention once, when relevant, that Shares, Spark Code, Sheet Views, and Ad Status stay blank for
YouTube rows: YouTube's API exposes no share count, and the other three are manual columns in the
user's sheet. Engagement % for YouTube rows is (likes + comments) / views. Click-through rate,
retention, impressions, and demographics are not available for other people's videos; the
replay heatmap from `--hooks` is the closest public proxy for retention.

## Exit codes

| Code | Meaning | What to tell the user |
|---|---|---|
| 0 | success | relay the report |
| 1 | usage error | fix the flags and rerun |
| 2 | no API key | export `YOUTUBE_API_KEY`, or put it in `~/.config/scout/.env`, or point `SCOUT_ENV_FILE` at the key file |
| 3 | quota exhausted | resets at midnight Pacific; try a smaller `--max` tomorrow |
| 4 | invalid API key | check the `YOUTUBE_API_KEY` value in the key file |
| 5 | other API or network error | show the message, suggest retry |
| 6 | file error | the `--into` file is missing or openpyxl is not installed |

## Sheet layout

**Videos**: the base columns follow `OWT-Social-Ads.xlsx` (Platform, Creator, Handle, Video ID,
Video Link, Posted as Unix epoch, Views, Likes, Comments, Shares, Engagement %, Duration s,
Spark Code, Local File, Sheet Views, Ad Status). In a new workbook, columns that would be blank
on every row are left out (Shares, Spark Code, Sheet Views, Ad Status always; Local File and
Thumbnail File without `--download`; the comment and hook columns without their flags). In
`--into` mode the full layout is kept so it lines up with the existing sheet. Then:

- Performance: Title, Published, Relevance # (position in YouTube's relevance results), Format
  (Short, Video, Live), Age d, Views/day, Views/Sub, Like %, Comment %.
- Channel: Channel URL, Subscribers, Channel Videos, Channel Views, Avg Views/Video, Channel
  Country, Channel Created, Channel Keywords, Channel Topics.
- Metadata: Category, Tags, Tag Count, Language, Captions, HD, Licensed, Embeddable, Made for
  Kids, Paid Promotion (creator-declared), AI Disclosure (creator-declared synthetic media),
  License, Live, Topics, Blocked Regions, Description (first 300 chars), Desc Links, Location,
  Thumbnail.
- With `--comments`: Top Comment, Top Comment Likes, Comments Off.
- With `--hooks`: Hook, Vertical, FPS, Most Replayed s, Replay Hotspots (true peaks of the
  "most replayed" curve, the opening decay is ignored), Chapters, Transcript Words. Format is
  corrected to Video when a short clip turns out to be horizontal. Hook and Transcript stay blank
  when a video has no captions at all, and the replay columns stay blank when YouTube has not
  published a heatmap for it (it needs enough views), so partial coverage is normal.

`--hooks` caches every yt-dlp probe and caption under `~/.cache/scout/` for 7 days, so a rerun
of the same topic (or a `--into` run on the same videos) only fetches what is missing. YouTube
rate-limits caption downloads after bursts (HTTP 429); the script paces fetches 1.5 s apart and
retries with backoff, and if some still fail it prints one warning with the count. Tell the
user to rerun the same command in about an hour to fill the gaps. `SCOUT_CAPTION_DELAY` and
`SCOUT_CACHE_DIR` override the pacing and cache location.

Usually blank, kept for the rare hit: AI Disclosure (YouTube only returns it in some cases),
Live, Blocked Regions, Location, Paid Promotion. Tags are blank when the creator added none.
- With `--download`: Thumbnail File (and Local File in column N).

**Channels**: one row per channel in the sample, sorted by sample views: handle, subscribers,
channel totals, country, created, videos in sample, sample views, sample average engagement,
best video and link, keywords, topics. This is the creator outreach list.

**Summary**: topic, run date, filters, quota, totals, median and mean views, average
engagement, median duration, Shorts share, paid promotion share, captions share, published
range, top video, top channels, top tags, categories, languages, channel countries.

**Comments** (flag): Video ID, Handle, Title, Author, Comment, Likes, Replies, Published, link.

**Transcripts** (flag): Video ID, Handle, Title, Language, Transcript Words, Hook, full
Transcript (capped at 32,000 characters), link.

Header styling, frozen header, autofilter, number formats, and hyperlinks are reproduced on
every sheet. New workbooks only get Channels and Summary; `--into` leaves those out because
aggregates over a mixed sheet would mislead.
