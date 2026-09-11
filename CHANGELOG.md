# Changelog

All notable changes to youtube-scout are recorded here. The format follows Keep a Changelog
and the project uses semantic versioning.

## 0.1.0 - 2026-09-11

First private release.

### Added

- `/scout <topic>`: YouTube Data API v3 search, statistics, channel, and category lookups,
  ranked by views, engagement, likes, recency, momentum, or breakout.
- Videos sheet in the OWT-Social-Ads layout with 48 columns (64 in append mode), Channels sheet
  for creator outreach, Summary sheet with sample aggregates.
- `--comments [N]`: top comments per video into a Comments sheet plus Top Comment on each row.
- `--hooks [SECONDS]`: yt-dlp probe for hook text, vertical detection, FPS, replay hotspots from
  the "most replayed" curve, chapters, and full transcripts in a Transcripts sheet, with an
  on-disk cache, request pacing, backoff, and a circuit breaker for caption rate limits.
- `--into file.xlsx`: append into an existing workbook with Video ID dedup, re-sort, preserved
  hyperlinks, fonts, and widths, and a timestamped backup written first.
- `--download`: mp4 and thumbnail download with yt-dlp.
- Key lookup from `YOUTUBE_API_KEY`, `SCOUT_ENV_FILE`, `~/.config/scout/.env`, or `./.env`.
- Offline test suite with API-shaped fixtures and a repository hygiene test.
